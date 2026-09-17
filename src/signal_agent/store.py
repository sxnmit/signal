"""SQLite persistence: what we have seen, what we have sent, what we shipped.

Two jobs:

* remember articles so the same story is never delivered twice, and
* keep a compact run history for ``signal stats``.

Schema changes are handled by numbered migrations keyed off ``PRAGMA
user_version``, so a v1 database upgrades in place without losing its send
history.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from .logs import get_logger
from .models import Article, Digest, utcnow

__all__ = ["SCHEMA_VERSION", "Store", "StoreStats"]

log = get_logger(__name__)

SCHEMA_VERSION = 2


@dataclass(slots=True)
class StoreStats:
    """Summary of what the database currently holds."""

    articles: int = 0
    sent: int = 0
    digests: int = 0
    stories_published: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    size_bytes: int = 0
    top_sources: list[tuple[str, int]] = field(default_factory=list)


class Store:
    """A SQLite-backed record of every article Signal has considered."""

    MEMORY = ":memory:"
    """Path for a throwaway database that never touches disk."""

    def __init__(self, path: str | Path = "news_digest.db") -> None:
        self.path = Path(path)
        self._shared: sqlite3.Connection | None = None

    @property
    def in_memory(self) -> bool:
        return str(self.path) == self.MEMORY

    # -- connection ------------------------------------------------------

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection, commit on success, always close.

        An in-memory database is the exception: SQLite gives each connection its
        own private database, so one is opened once and held for the life of the
        store. That is what makes ``Store(Store.MEMORY)`` usable as a real
        store in ``signal demo`` and in tests.
        """
        if self.in_memory:
            conn = self._shared or self._open()
            self._shared = conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return

        if self.path.parent and str(self.path.parent) not in ("", "."):
            self.path.parent.mkdir(parents=True, exist_ok=True)

        conn = self._open()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def close(self) -> None:
        """Release a held in-memory connection, discarding its contents."""
        if self._shared is not None:
            self._shared.close()
            self._shared = None

    # -- schema ----------------------------------------------------------

    def migrate(self) -> int:
        """Bring the database up to :data:`SCHEMA_VERSION`; return the version applied from."""
        with self.connect() as conn:
            current = int(conn.execute("PRAGMA user_version").fetchone()[0])

            # A v1 database predates user_version, so detect it by its tables.
            if current == 0 and self._table_exists(conn, "sent_articles"):
                current = 1

            started_at = current

            if current < 1:
                self._create_schema(conn)
                current = SCHEMA_VERSION
            elif current < 2:
                self._migrate_v1_to_v2(conn)
                current = 2

            conn.execute(f"PRAGMA user_version = {current}")

        if started_at and started_at < SCHEMA_VERSION:
            log.info("Migrated database schema v%d → v%d", started_at, SCHEMA_VERSION)
        return started_at

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                url           TEXT NOT NULL UNIQUE,
                content_hash  TEXT NOT NULL,
                title         TEXT NOT NULL,
                source        TEXT NOT NULL DEFAULT '',
                published_at  TEXT,
                created_at    TEXT NOT NULL,
                last_seen_at  TEXT NOT NULL,
                times_seen    INTEGER NOT NULL DEFAULT 1,
                sent_at       TEXT
            );

            CREATE TABLE IF NOT EXISTS digests (
                date            TEXT PRIMARY KEY,
                generated_at    TEXT NOT NULL,
                story_count     INTEGER NOT NULL DEFAULT 0,
                section_count   INTEGER NOT NULL DEFAULT 0,
                fetched         INTEGER NOT NULL DEFAULT 0,
                summarizer      TEXT NOT NULL DEFAULT '',
                duration_seconds REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(content_hash);
            CREATE INDEX IF NOT EXISTS idx_articles_sent ON articles(sent_at);
            CREATE INDEX IF NOT EXISTS idx_articles_created ON articles(created_at);
            """
        )

    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """Add the v2 columns to a v1 ``articles`` table and fold in send history.

        v1 kept sends in a separate ``sent_articles`` table and recorded an
        article the moment it was *fetched* — which meant anything the
        summarizer passed over was never reconsidered. v2 stores the send
        timestamp on the article itself and only marks rows as sent once they
        actually ship, so nothing gets silently buried.
        """
        existing = self._columns(conn, "articles")
        now = utcnow().isoformat()

        if "source" not in existing:
            conn.execute("ALTER TABLE articles ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        if "last_seen_at" not in existing:
            conn.execute("ALTER TABLE articles ADD COLUMN last_seen_at TEXT")
            conn.execute("UPDATE articles SET last_seen_at = COALESCE(created_at, ?)", (now,))
        if "times_seen" not in existing:
            conn.execute("ALTER TABLE articles ADD COLUMN times_seen INTEGER NOT NULL DEFAULT 1")
        if "sent_at" not in existing:
            conn.execute("ALTER TABLE articles ADD COLUMN sent_at TEXT")

        if self._table_exists(conn, "sent_articles"):
            # Carry every historical send across, keeping the earliest date.
            conn.execute(
                """
                UPDATE articles
                   SET sent_at = (
                       SELECT MIN(s.sent_date) FROM sent_articles s WHERE s.article_id = articles.id
                   )
                 WHERE sent_at IS NULL
                   AND EXISTS (SELECT 1 FROM sent_articles s WHERE s.article_id = articles.id)
                """
            )
            conn.execute("DROP TABLE sent_articles")

        self._create_schema(conn)

    # -- reads -----------------------------------------------------------

    def already_sent(self, articles: Iterable[Article]) -> set[str]:
        """Return the canonical URLs, of those given, that have already shipped.

        Matches on URL *or* content fingerprint, so syndicated copies of a
        story that already went out are caught even under a different link.
        """
        items = list(articles)
        if not items:
            return set()

        urls = {a.url for a in items if a.url}
        hashes = {a.fingerprint for a in items}

        sent_urls: set[str] = set()
        sent_hashes: set[str] = set()

        with self.connect() as conn:
            for chunk in _chunks(sorted(urls), 400):
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT url FROM articles WHERE sent_at IS NOT NULL "
                    f"AND url IN ({placeholders})",
                    chunk,
                )
                sent_urls.update(row["url"] for row in rows)

            for chunk in _chunks(sorted(hashes), 400):
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT content_hash FROM articles "
                    f"WHERE sent_at IS NOT NULL AND content_hash IN ({placeholders})",
                    chunk,
                )
                sent_hashes.update(row["content_hash"] for row in rows)

        return {a.url for a in items if a.url in sent_urls or a.fingerprint in sent_hashes}

    def stats(self) -> StoreStats:
        """Everything ``signal stats`` prints."""
        self.migrate()
        with self.connect() as conn:
            totals = conn.execute(
                """
                SELECT COUNT(*) AS articles,
                       SUM(CASE WHEN sent_at IS NOT NULL THEN 1 ELSE 0 END) AS sent,
                       MIN(created_at) AS first_seen,
                       MAX(last_seen_at) AS last_seen
                  FROM articles
                """
            ).fetchone()
            digests = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(story_count), 0) AS stories FROM digests"
            ).fetchone()
            sources = conn.execute(
                """
                SELECT source, COUNT(*) AS n
                  FROM articles
                 WHERE source != ''
                 GROUP BY source
                 ORDER BY n DESC
                 LIMIT 8
                """
            ).fetchall()

        return StoreStats(
            articles=totals["articles"] or 0,
            sent=totals["sent"] or 0,
            digests=digests["n"] or 0,
            stories_published=digests["stories"] or 0,
            first_seen=totals["first_seen"],
            last_seen=totals["last_seen"],
            size_bytes=(
                self.path.stat().st_size if not self.in_memory and self.path.exists() else 0
            ),
            top_sources=[(row["source"], row["n"]) for row in sources],
        )

    def recent_digests(self, limit: int = 10) -> list[dict[str, Any]]:
        """The most recent runs, newest first."""
        self.migrate()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM digests ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    # -- writes ----------------------------------------------------------

    def record_seen(self, articles: Iterable[Article]) -> int:
        """Upsert every article as seen. Returns how many rows were new.

        Seeing an article is deliberately *not* the same as sending it: a story
        that misses today's cut stays eligible tomorrow, when more outlets may
        have picked it up.
        """
        items = [a for a in articles if a.url]
        if not items:
            return 0

        now = utcnow().isoformat()

        with self.connect() as conn:
            known = self._known_urls(conn, [a.url for a in items])
            conn.executemany(
                """
                INSERT INTO articles
                    (url, content_hash, title, source, published_at, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at,
                    times_seen   = times_seen + 1,
                    title        = excluded.title,
                    source       = CASE WHEN articles.source = ''
                                        THEN excluded.source ELSE articles.source END
                """,
                [
                    (
                        a.url,
                        a.fingerprint,
                        a.title,
                        a.source,
                        a.published.isoformat() if a.published else None,
                        now,
                        now,
                    )
                    for a in items
                ],
            )

        return len({a.url for a in items} - known)

    @staticmethod
    def _known_urls(conn: sqlite3.Connection, urls: list[str]) -> set[str]:
        """Which of ``urls`` the database already holds."""
        found: set[str] = set()
        for chunk in _chunks(sorted(set(urls)), 400):
            placeholders = ",".join("?" * len(chunk))
            rows = conn.execute(f"SELECT url FROM articles WHERE url IN ({placeholders})", chunk)
            found.update(row["url"] for row in rows)
        return found

    def mark_sent(self, urls: Iterable[str]) -> int:
        """Record that these URLs went out in a digest. Returns rows updated."""
        items = [u for u in dict.fromkeys(urls) if u]
        if not items:
            return 0

        now = utcnow().isoformat()
        updated = 0
        with self.connect() as conn:
            for chunk in _chunks(items, 400):
                placeholders = ",".join("?" * len(chunk))
                cursor = conn.execute(
                    f"UPDATE articles SET sent_at = ? "
                    f"WHERE sent_at IS NULL AND url IN ({placeholders})",
                    [now, *chunk],
                )
                updated += cursor.rowcount or 0
        return updated

    def record_digest(self, digest: Digest) -> None:
        """Store (or replace) the summary row for one edition."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO digests
                    (date, generated_at, story_count, section_count, fetched,
                     summarizer, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    generated_at     = excluded.generated_at,
                    story_count      = excluded.story_count,
                    section_count    = excluded.section_count,
                    fetched          = excluded.fetched,
                    summarizer       = excluded.summarizer,
                    duration_seconds = excluded.duration_seconds
                """,
                (
                    digest.date_slug,
                    digest.generated_at.isoformat(),
                    digest.story_count,
                    len(digest.sections),
                    digest.stats.fetched,
                    digest.stats.summarizer,
                    digest.stats.duration_seconds,
                ),
            )

    def vacuum(self) -> None:
        """Reclaim free pages so the committed database stays small."""
        if self.in_memory:
            return
        # VACUUM cannot run inside a transaction, so it gets its own connection.
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("VACUUM")
        finally:
            conn.close()

    def prune(self, retention_days: int, *, vacuum: bool = True) -> int:
        """Delete articles older than the retention window. Returns rows removed.

        Keeps the committed database small enough to live in git. Feeds only
        surface recent items, so a months-old row can no longer collide with
        anything being fetched.
        """
        if retention_days <= 0:
            return 0

        cutoff = (utcnow() - timedelta(days=retention_days)).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM articles WHERE COALESCE(last_seen_at, created_at) < ?", (cutoff,)
            )
            removed = cursor.rowcount or 0

        if removed and vacuum:
            self.vacuum()

        if removed:
            log.debug("Pruned %d article(s) older than %d days", removed, retention_days)
        return removed


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    """Split a list into SQLite-parameter-sized batches."""
    for start in range(0, len(items), size):
        yield items[start : start + size]
