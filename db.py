"""SQLite persistence layer for article storage and send tracking."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

DEFAULT_DB_PATH = os.environ.get("NEWS_DIGEST_DB_PATH", "news_digest.db")


@contextmanager
def get_connection(db_path: str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Yield a SQLite connection with Row mapping enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create the database schema if it does not yet exist."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                content_hash TEXT NOT NULL,
                published_at TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sent_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id INTEGER NOT NULL,
                sent_date TEXT NOT NULL,
                FOREIGN KEY(article_id) REFERENCES articles(id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sent_articles_article_id ON sent_articles(article_id)"
        )


def article_exists(url: str, content_hash: str, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Return True when an article with matching URL or content hash is already stored."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id
            FROM articles
            WHERE url = ? OR content_hash = ?
            LIMIT 1
            """,
            (url, content_hash),
        ).fetchone()
        return row is not None


def insert_article(article: dict[str, Any], db_path: str = DEFAULT_DB_PATH) -> int | None:
    """Insert a new article row and return its id.

    Returns None if the row violates the unique URL constraint.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO articles (title, url, content_hash, published_at, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    article["title"],
                    article["url"],
                    article["content_hash"],
                    article.get("published"),
                    created_at,
                ),
            )
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            return None


def mark_as_sent(article_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    """Record that an article was included in a digest email today."""
    with get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO sent_articles (article_id, sent_date) VALUES (?, ?)",
            (article_id, date.today().isoformat()),
        )


def get_unsent_articles(limit: int = 10, db_path: str = DEFAULT_DB_PATH) -> list[dict[str, Any]]:
    """Fetch persisted articles that have never been sent."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.title, a.url, a.content_hash, a.published_at, a.created_at
            FROM articles a
            LEFT JOIN sent_articles s ON s.article_id = a.id
            WHERE s.id IS NULL
            ORDER BY COALESCE(a.published_at, a.created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]