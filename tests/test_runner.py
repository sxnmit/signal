"""End-to-end pipeline behaviour, driven entirely offline."""

from __future__ import annotations

import dataclasses

import pytest

from signal_agent.archive import Archive
from signal_agent.runner import run
from signal_agent.sample_data import sample_articles
from signal_agent.store import Store


@pytest.fixture
def offline(config, tmp_path):
    """Config with the archive pointed at a temporary directory."""
    return dataclasses.replace(
        config,
        archive=dataclasses.replace(config.archive, directory=str(tmp_path / "archive")),
        site=dataclasses.replace(config.site, enabled=False),
    )


class TestFullRun:
    def test_produces_a_digest(self, offline):
        outcome = run(offline, articles=sample_articles(), store=Store(Store.MEMORY))

        assert not outcome.digest.is_empty
        assert outcome.digest.sections
        assert outcome.stats.fetched == len(sample_articles())

    def test_clusters_appear_as_one_story(self, offline):
        outcome = run(offline, articles=sample_articles(), store=Store(Store.MEMORY))
        stories = [s for section in outcome.digest.sections for s in section.stories]

        best = max(s.corroboration for s in stories)
        assert best >= 3  # the sample corpus contains a story four outlets ran

    def test_stories_carry_real_urls(self, offline):
        outcome = run(offline, articles=sample_articles(), store=Store(Store.MEMORY))
        source_urls = {a.url for a in sample_articles()}

        for section in outcome.digest.sections:
            for story in section.stories:
                assert story.url in source_urls

    def test_writes_the_archive(self, offline):
        run(offline, articles=sample_articles(), store=Store(Store.MEMORY))
        assert Archive(offline.archive.directory).dates()

    def test_records_the_run(self, offline):
        store = Store(Store.MEMORY)
        run(offline, articles=sample_articles(), store=store)
        assert store.stats().digests == 1

    def test_no_articles(self, offline):
        outcome = run(offline, articles=[], store=Store(Store.MEMORY))
        assert outcome.digest.is_empty
        assert outcome.stats.fetched == 0


class TestDryRun:
    def test_changes_nothing(self, offline, tmp_path):
        store = Store(Store.MEMORY)
        outcome = run(offline, dry_run=True, articles=sample_articles(), store=store)

        assert not outcome.digest.is_empty
        assert store.stats().articles == 0
        assert store.stats().digests == 0
        assert not Archive(offline.archive.directory).dates()

    def test_produces_the_same_stories_as_a_real_run(self, offline):
        dry = run(offline, dry_run=True, articles=sample_articles(), store=Store(Store.MEMORY))
        wet = run(offline, articles=sample_articles(), store=Store(Store.MEMORY))
        assert dry.digest.story_count == wet.digest.story_count


class TestDeduplicationAcrossRuns:
    def test_a_story_is_not_sent_twice(self, offline):
        store = Store(Store.MEMORY)
        first = run(offline, articles=sample_articles(), store=store)
        second = run(offline, articles=sample_articles(), store=store)

        assert first.digest.story_count > 0
        assert second.digest.is_empty

    def test_unpublished_articles_stay_eligible(self, offline, article_factory):
        # The v1 bug: an article recorded at fetch time but never selected was
        # buried permanently. Seeing must not imply sending.
        store = Store(Store.MEMORY)
        unrelated = [article_factory("Local bakery wins a county fair ribbon")]

        first = run(offline, articles=unrelated, store=store)
        assert first.digest.is_empty  # matched no topic

        # Now it arrives alongside enough context to be publishable.
        second = run(offline, articles=unrelated + sample_articles(), store=store)
        assert not second.digest.is_empty

    def test_archive_can_rebuild_send_history(self, offline):
        # CI runs on a fresh checkout with no database; the archive is enough.
        run(offline, articles=sample_articles(), store=Store(Store.MEMORY))

        fresh_store = Store(Store.MEMORY)
        second = run(offline, articles=sample_articles(), store=fresh_store)
        assert second.digest.is_empty


class TestDelivery:
    def test_disabled_channels_deliver_nothing(self, offline):
        outcome = run(offline, articles=sample_articles(), store=Store(Store.MEMORY))
        assert outcome.delivered == 0
        assert outcome.archived

    def test_no_send_skips_delivery(self, offline):
        outcome = run(offline, deliver=False, articles=sample_articles(), store=Store(Store.MEMORY))
        assert outcome.delivered == 0


class TestStats:
    def test_are_populated(self, offline):
        stats = run(offline, articles=sample_articles(), store=Store(Store.MEMORY)).stats

        assert stats.fetched > 0
        assert stats.after_dedup > 0
        assert stats.clusters > 0
        assert stats.published > 0
        assert stats.summarizer == "extractive"
        assert stats.duration_seconds >= 0

    def test_clustering_reduces_the_count(self, offline):
        stats = run(offline, articles=sample_articles(), store=Store(Store.MEMORY)).stats
        assert stats.clusters < stats.after_dedup
