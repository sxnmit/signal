"""Persistence, the v1 migration, and retention."""

from __future__ import annotations

import sqlite3

from signal_agent.models import Digest, RunStats, Section, Story, utcnow
from signal_agent.store import SCHEMA_VERSION, Store


def _v1_database(path) -> None:
    """Build a database in the exact shape v1 left behind."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            content_hash TEXT NOT NULL,
            published_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE sent_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            sent_date TEXT NOT NULL
        );
        INSERT INTO articles (title, url, content_hash, published_at, created_at)
        VALUES ('Old story', 'https://old.example.com/a', 'hash-a', NULL, '2026-01-01T00:00:00'),
               ('Unsent story', 'https://old.example.com/b', 'hash-b', NULL, '2026-01-02T00:00:00');
        INSERT INTO sent_articles (article_id, sent_date) VALUES (1, '2026-01-01');
        """
    )
    conn.commit()
    conn.close()


class TestMigration:
    def test_fresh_database_is_current(self, tmp_path):
        store = Store(tmp_path / "new.db")
        assert store.migrate() == 0
        with store.connect() as conn:
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION

    def test_upgrades_a_v1_database(self, tmp_path):
        path = tmp_path / "v1.db"
        _v1_database(path)
        store = Store(path)

        assert store.migrate() == 1

        stats = store.stats()
        assert stats.articles == 2
        assert stats.sent == 1  # the send history survived the upgrade

    def test_v1_send_history_is_preserved(self, tmp_path, article_factory):
        path = tmp_path / "v1.db"
        _v1_database(path)
        store = Store(path)
        store.migrate()

        sent = article_factory("Old story", url="https://old.example.com/a")
        unsent = article_factory("Unsent story", url="https://old.example.com/b")

        already = store.already_sent([sent, unsent])
        assert sent.url in already
        assert unsent.url not in already

    def test_migration_is_idempotent(self, tmp_path):
        path = tmp_path / "v1.db"
        _v1_database(path)
        store = Store(path)
        store.migrate()
        assert store.migrate() == SCHEMA_VERSION

    def test_legacy_table_is_removed(self, tmp_path):
        path = tmp_path / "v1.db"
        _v1_database(path)
        Store(path).migrate()
        conn = sqlite3.connect(path)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        assert "sent_articles" not in names


class TestSeenAndSent:
    def test_record_seen_counts_only_new_rows(self, store, article_factory):
        articles = [article_factory("One"), article_factory("Two")]
        assert store.record_seen(articles) == 2
        assert store.record_seen(articles) == 0

    def test_seeing_is_not_sending(self, store, article_factory):
        # v1's bug: an article the summarizer passed over was buried forever.
        articles = [article_factory("One")]
        store.record_seen(articles)
        assert store.already_sent(articles) == set()

    def test_mark_sent_then_filtered(self, store, article_factory):
        article = article_factory("One")
        store.record_seen([article])
        assert store.mark_sent([article.url]) == 1
        assert store.already_sent([article]) == {article.url}

    def test_mark_sent_is_idempotent(self, store, article_factory):
        article = article_factory("One")
        store.record_seen([article])
        store.mark_sent([article.url])
        assert store.mark_sent([article.url]) == 0

    def test_already_sent_matches_on_fingerprint(self, store, article_factory):
        original = article_factory("Wire story", url="https://a.com/1", summary="Body.")
        store.record_seen([original])
        store.mark_sent([original.url])

        # Same words, republished at a different URL.
        copy = article_factory("Wire story", url="https://b.com/2", summary="Body.")
        assert copy.url in store.already_sent([copy])

    def test_empty_inputs(self, store):
        assert store.record_seen([]) == 0
        assert store.mark_sent([]) == 0
        assert store.already_sent([]) == set()

    def test_times_seen_increments(self, store, article_factory):
        article = article_factory("Repeat")
        store.record_seen([article])
        store.record_seen([article])
        with store.connect() as conn:
            row = conn.execute(
                "SELECT times_seen FROM articles WHERE url = ?", (article.url,)
            ).fetchone()
        assert row["times_seen"] == 2


class TestRetention:
    def test_prune_removes_old_rows(self, tmp_store, article_factory):
        article = article_factory("Ancient")
        tmp_store.record_seen([article])
        with tmp_store.connect() as conn:
            conn.execute(
                "UPDATE articles SET created_at = '2020-01-01T00:00:00+00:00',"
                " last_seen_at = '2020-01-01T00:00:00+00:00'"
            )

        assert tmp_store.prune(90) == 1
        assert tmp_store.stats().articles == 0

    def test_prune_keeps_recent_rows(self, tmp_store, article_factory):
        tmp_store.record_seen([article_factory("Fresh")])
        assert tmp_store.prune(90) == 0

    def test_prune_disabled(self, tmp_store, article_factory):
        tmp_store.record_seen([article_factory("Fresh")])
        assert tmp_store.prune(0) == 0


class TestDigestHistory:
    def test_record_and_read_back(self, store):
        digest = Digest(
            generated_at=utcnow(),
            sections=[
                Section(
                    topic="World",
                    slug="world",
                    icon="🌍",
                    stories=[Story(headline="H", summary="S", url="https://a.com/x", source="BBC")],
                )
            ],
            stats=RunStats(fetched=10, summarizer="extractive"),
        )
        store.record_digest(digest)

        recent = store.recent_digests()
        assert len(recent) == 1
        assert recent[0]["story_count"] == 1
        assert store.stats().digests == 1

    def test_rerunning_a_day_replaces_it(self, store):
        digest = Digest(generated_at=utcnow(), sections=[])
        store.record_digest(digest)
        store.record_digest(digest)
        assert store.stats().digests == 1


def test_in_memory_store_persists_across_operations():
    # SQLite gives each connection a private in-memory database, so the store
    # has to hold one open for this to work at all.
    store = Store(Store.MEMORY)
    store.migrate()
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO articles (url, content_hash, title, created_at, last_seen_at)"
            " VALUES ('u', 'h', 't', 'now', 'now')"
        )
    assert store.stats().articles == 1
    store.close()
