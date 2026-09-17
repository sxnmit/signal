"""The pipeline: fetch, dedupe, cluster, rank, summarise, deliver.

One function, :func:`run`, executes a complete edition. It is written so that
every expensive or irreversible step is explicit and skippable, which is what
makes ``--dry-run`` a genuine rehearsal rather than a different code path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .archive import Archive
from .config import Config
from .deliver import post_digest, send_digest
from .logs import get_logger
from .models import Article, Digest, RunStats, Section, Story, utcnow
from .pipeline.cluster import cluster_articles
from .pipeline.dedup import drop_duplicates, within_window
from .pipeline.rank import assign_topics, select
from .sources import collect
from .sources.registry import dedupe_by_url
from .store import Store
from .summarize import get_summarizer

__all__ = ["RunOutcome", "run"]

log = get_logger(__name__)


@dataclass(slots=True)
class RunOutcome:
    """Everything a caller might want to know about a completed run."""

    digest: Digest
    delivered: int = 0
    archived: bool = False
    skipped_as_sent: int = 0

    @property
    def stats(self) -> RunStats:
        return self.digest.stats


def run(
    config: Config,
    *,
    dry_run: bool = False,
    deliver: bool = True,
    articles: list[Article] | None = None,
    store: Store | None = None,
) -> RunOutcome:
    """Assemble one edition.

    ``dry_run`` performs every read but no write: nothing is emailed, archived,
    marked as sent, or recorded. One exception, and it is deliberate: the
    database schema is still brought up to date, because deciding what has
    already been delivered requires reading it.

    ``articles`` injects a corpus instead of fetching and ``store`` substitutes
    the database, which together let ``signal demo`` and the tests exercise the
    real pipeline with no network and no files touched.
    """
    started = time.monotonic()
    stats = RunStats()

    store = store or Store(config.store.path)
    archive = Archive(config.archive.directory)
    store.migrate()

    # -- 1. fetch --------------------------------------------------------
    if articles is None:
        report = collect(config)
        raw = report.articles
        stats.sources_ok = report.ok_count
        stats.sources_failed = len(report.failures)
    else:
        raw = list(articles)
        stats.sources_ok = 1

    stats.fetched = len(raw)
    if not raw:
        log.warning("No articles fetched — nothing to do")
        return RunOutcome(digest=_empty_digest(config, stats, started))

    # -- 2. dedupe -------------------------------------------------------
    fresh = drop_duplicates(dedupe_by_url(within_window(raw, config.fetch.window_hours)))

    # Anything already delivered is dropped here, not at fetch time. v1 recorded
    # articles the moment it saw them, so a story the summarizer passed over was
    # buried forever; now only delivery marks a story as spent.
    already = store.already_sent(fresh) | _archive_backstop(store, archive, config)
    before = len(fresh)
    fresh = [a for a in fresh if a.url not in already]
    skipped = before - len(fresh)
    stats.after_dedup = len(fresh)

    log.info(
        "%d article(s) after dedup (%d duplicate, %d already sent)",
        len(fresh),
        len(raw) - before,
        skipped,
    )

    if not fresh:
        return RunOutcome(digest=_empty_digest(config, stats, started), skipped_as_sent=skipped)

    if not dry_run:
        store.record_seen(fresh)

    # -- 3. cluster and rank ---------------------------------------------
    clusters = cluster_articles(fresh, config.dedup.similarity_threshold)
    stats.clusters = len(clusters)

    selected = select(assign_topics(clusters, config.topics), config.topics, config.rank)
    chosen = sum(len(c) for c in selected.values())
    log.info(
        "%d cluster(s) from %d article(s); %d selected across %d topic(s)",
        len(clusters),
        len(fresh),
        chosen,
        len(selected),
    )

    if not selected:
        return RunOutcome(digest=_empty_digest(config, stats, started), skipped_as_sent=skipped)

    # -- 4. summarise ----------------------------------------------------
    summarizer = get_summarizer(config.summarize)
    stats.summarizer = summarizer.name
    log.info("Summarising %d story group(s) with %s", chosen, summarizer.name)

    sections: list[Section] = []
    for topic in config.topics:
        topic_clusters = selected.get(topic.slug)
        if not topic_clusters:
            continue

        stories: list[Story] = summarizer.write(topic, topic_clusters)
        stories = [s for s in stories if s.headline and s.url]
        if stories:
            sections.append(
                Section(topic=topic.name, slug=topic.slug, icon=topic.icon, stories=stories)
            )

    stats.published = sum(len(s.stories) for s in sections)
    stats.duration_seconds = time.monotonic() - started

    digest = Digest(generated_at=utcnow(), sections=sections, stats=stats, title=config.title)

    if dry_run:
        log.info("Dry run — nothing delivered, archived, or recorded")
        return RunOutcome(digest=digest, skipped_as_sent=skipped)

    # -- 5. deliver, then record ------------------------------------------
    delivered = 0
    if deliver and not digest.is_empty:
        delivered = _deliver(digest, config)

    archived = False
    if config.archive.enabled and not digest.is_empty:
        archive.write(digest)
        archived = True

    store.record_digest(digest)

    # Only mark stories as sent once they have actually gone somewhere — an
    # SMTP failure must not silently consume a day's news.
    if delivered or archived:
        urls = [s.url for section in digest.sections for s in section.stories]
        urls += [
            url
            for section in digest.sections
            for story in section.stories
            for _, url in story.also_covered_by
        ]
        store.mark_sent(urls)

    store.prune(config.dedup.retention_days)

    return RunOutcome(
        digest=digest, delivered=delivered, archived=archived, skipped_as_sent=skipped
    )


def _deliver(digest: Digest, config: Config) -> int:
    """Send through every configured channel. Returns recipients reached."""
    delivered = 0

    if config.email.enabled:
        result = send_digest(digest, config.email, base_url=config.site.base_url)
        delivered += result.sent

    if config.webhook.configured and post_digest(digest, config.webhook):
        delivered += 1

    return delivered


def _archive_backstop(store: Store, archive: Archive, config: Config) -> set[str]:
    """Every URL the archive shows as already published.

    The archive, not the database, is Signal's durable record of what went out.
    It is small, diffable JSON that belongs in git anyway, which means CI never
    has to commit a binary database just to remember yesterday — and a database
    lost to a fresh checkout or a wiped laptop costs nothing.

    The two sources are unioned rather than used as fallbacks: the database
    knows about runs whose archive file has not been committed yet, and the
    archive knows about runs this checkout's database never saw.
    """
    if not config.archive.enabled:
        return set()

    # Bounded by the retention window: editions older than that can no longer
    # collide with anything a feed is still serving.
    urls = archive.sent_urls(limit=max(1, config.dedup.retention_days))
    if urls and store.stats().sent == 0:
        log.info("No send history in the database; %d URL(s) recovered from the archive", len(urls))
    return urls


def _empty_digest(config: Config, stats: RunStats, started: float) -> Digest:
    stats.duration_seconds = time.monotonic() - started
    return Digest(generated_at=utcnow(), sections=[], stats=stats, title=config.title)
