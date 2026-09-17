"""NewsAPI.org keyword search.

Optional: without ``NEWS_API_KEY`` the provider reports itself as skipped and
the run continues on feeds alone.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import requests

from ..config import FetchConfig, NewsAPIConfig, Topic
from ..logs import get_logger
from ..models import Article, utcnow
from .base import SourceResult, parse_timestamp

__all__ = ["fetch_newsapi", "fetch_topic"]

log = get_logger(__name__)

_ENDPOINT = "https://newsapi.org/v2/everything"


def fetch_topic(
    topic: Topic,
    session: requests.Session,
    api: NewsAPIConfig,
    cfg: FetchConfig,
) -> SourceResult:
    """Run one topic's query against NewsAPI. Never raises."""
    started = time.monotonic()
    name = f"newsapi:{topic.slug}"
    query = topic.query or topic.name

    since = (utcnow() - timedelta(hours=cfg.window_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    params: dict[str, str | int] = {
        "q": query,
        "from": since,
        "sortBy": "publishedAt",
        "language": api.language,
        "pageSize": max(1, min(api.page_size, 100)),
        "apiKey": api.api_key,
    }

    try:
        response = session.get(_ENDPOINT, params=params, timeout=cfg.timeout_seconds)
        payload = response.json()
    except requests.RequestException as exc:
        return SourceResult(name=name, error=str(exc), elapsed=time.monotonic() - started)
    except ValueError as exc:
        return SourceResult(name=name, error=f"bad JSON: {exc}", elapsed=time.monotonic() - started)

    if payload.get("status") != "ok":
        # NewsAPI reports quota exhaustion and bad keys in the body, not the status code.
        message = payload.get("message") or f"HTTP {response.status_code}"
        return SourceResult(name=name, error=str(message), elapsed=time.monotonic() - started)

    articles: list[Article] = []
    for item in payload.get("articles", [])[: api.max_articles]:
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        # NewsAPI leaves tombstones behind for pulled articles.
        if not title or not url or "[Removed]" in title:
            continue

        articles.append(
            Article.create(
                title=title,
                url=url,
                source=(item.get("source") or {}).get("name") or "NewsAPI",
                summary=(item.get("description") or "").strip(),
                published=parse_timestamp(item.get("publishedAt")),
                origin="newsapi",
            )
        )

    return SourceResult(name=name, articles=articles, elapsed=time.monotonic() - started)


def fetch_newsapi(
    topics: list[Topic],
    session: requests.Session,
    api: NewsAPIConfig,
    cfg: FetchConfig,
) -> list[SourceResult]:
    """Query NewsAPI once per topic, concurrently."""
    if not api.configured or not topics:
        return []

    workers = max(1, min(cfg.max_workers, len(topics)))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="signal-newsapi") as pool:
        return list(pool.map(lambda t: fetch_topic(t, session, api, cfg), topics))
