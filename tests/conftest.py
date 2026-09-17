"""Shared fixtures. Nothing here touches the network or the real filesystem."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from signal_agent.config import Config
from signal_agent.models import Article, utcnow
from signal_agent.store import Store


@pytest.fixture
def now():
    return utcnow()


@pytest.fixture
def article_factory(now):
    """Build an :class:`Article` with sensible defaults."""

    def make(
        title: str,
        *,
        url: str | None = None,
        source: str = "Example News",
        summary: str = "",
        hours_ago: float = 1.0,
        weight: float = 1.0,
        origin: str = "rss",
    ) -> Article:
        slug = "".join(c if c.isalnum() else "-" for c in title.lower())[:50]
        host = "".join(c for c in source.lower() if c.isalnum()) or "news"
        return Article.create(
            title=title,
            url=url or f"https://{host}.example.com/{slug}",
            source=source,
            summary=summary,
            published=now - timedelta(hours=hours_ago),
            origin=origin,
            source_weight=weight,
        )

    return make


@pytest.fixture
def config() -> Config:
    """The packaged defaults, with every external channel switched off."""
    base = Config.load()
    return dataclasses.replace(
        base,
        email=dataclasses.replace(base.email, enabled=False),
        webhook=dataclasses.replace(base.webhook, enabled=False, url=""),
        newsapi=dataclasses.replace(base.newsapi, enabled=False),
        hackernews=dataclasses.replace(base.hackernews, enabled=False),
        store=dataclasses.replace(base.store, path=Store.MEMORY),
    )


@pytest.fixture
def store() -> Iterator[Store]:
    """A migrated, in-memory database."""
    store = Store(Store.MEMORY)
    store.migrate()
    yield store
    store.close()


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    """A migrated database on disk, for tests that need file behaviour."""
    store = Store(tmp_path / "signal.db")
    store.migrate()
    return store


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Keep ambient credentials and config out of every test."""
    for name in (
        "GROQ_API_KEY",
        "NEWS_API_KEY",
        "SENDER_EMAIL",
        "SENDER_PASSWORD",
        "RECIPIENT_EMAILS",
        "SMTP_HOST",
        "SMTP_PORT",
        "SIGNAL_CONFIG",
        "SIGNAL_WEBHOOK_URL",
        "SIGNAL_DB_PATH",
        "NEWS_DIGEST_DB_PATH",
        "SIGNAL_SUMMARIZER",
        "SIGNAL_RECIPIENTS",
    ):
        monkeypatch.delenv(name, raising=False)
