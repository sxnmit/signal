"""RSS and Atom feeds.

Signal fetches every feed exactly once per run, in parallel, and routes the
results to topics afterwards. v1 re-parsed the whole feed list once per topic —
16 topics x 16 feeds meant 256 downloads for 16 feeds' worth of news.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import feedparser
import requests

from ..config import Feed, FetchConfig
from ..logs import get_logger
from ..models import Article
from .base import SourceResult, parse_timestamp

__all__ = ["fetch_feed", "fetch_feeds"]

log = get_logger(__name__)

# Feeds that hand back an entire article body would otherwise dominate the
# summarizer's context window.
_SUMMARY_LIMIT = 600


def _entry_summary(entry: object) -> str:
    """Pull the best available blurb out of a feed entry."""
    get = getattr(entry, "get", None)
    if get is None:
        return ""

    for key in ("summary", "description", "subtitle"):
        value = get(key)
        if isinstance(value, str) and value.strip():
            return _strip_html(value)[:_SUMMARY_LIMIT]

    content = get("content")
    if isinstance(content, list) and content:
        value = content[0].get("value", "")
        if isinstance(value, str) and value.strip():
            return _strip_html(value)[:_SUMMARY_LIMIT]

    return ""


def _strip_html(value: str) -> str:
    """Flatten feed HTML into plain text.

    Feeds carry markup of wildly varying quality, so this stays deliberately
    forgiving: drop tags, unescape entities, collapse whitespace.
    """
    import html
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_feed(feed: Feed, session: requests.Session, cfg: FetchConfig) -> SourceResult:
    """Fetch and parse one feed. Never raises."""
    started = time.monotonic()
    name = feed.name or feed.url

    try:
        response = session.get(feed.url, timeout=cfg.timeout_seconds)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
    except requests.RequestException as exc:
        return SourceResult(name=name, error=str(exc), elapsed=time.monotonic() - started)
    except Exception as exc:  # noqa: BLE001 - a malformed feed must not end the run
        return SourceResult(
            name=name, error=f"parse failed: {exc}", elapsed=time.monotonic() - started
        )

    # feedparser sets `bozo` for malformed XML but often still recovers entries,
    # so only treat it as fatal when nothing came back.
    entries = getattr(parsed, "entries", []) or []
    if not entries:
        detail = getattr(parsed, "bozo_exception", None)
        message = f"no entries ({detail})" if detail else "no entries"
        return SourceResult(name=name, error=message, elapsed=time.monotonic() - started)

    feed_title = ""
    if hasattr(parsed, "feed"):
        feed_title = str(parsed.feed.get("title", "") or "")
    outlet = feed.name or feed_title or feed.url

    articles: list[Article] = []
    for entry in entries:
        title = str(entry.get("title", "") or "").strip()
        link = str(entry.get("link", "") or "").strip()
        if not title or not link:
            continue

        published = parse_timestamp(
            entry.get("published_parsed")
            or entry.get("updated_parsed")
            or entry.get("published")
            or entry.get("updated")
        )

        articles.append(
            Article.create(
                title=title,
                url=link,
                source=outlet,
                summary=_entry_summary(entry),
                published=published,
                origin="rss",
                source_weight=feed.weight,
            )
        )

    return SourceResult(name=name, articles=articles, elapsed=time.monotonic() - started)


def fetch_feeds(
    feeds: list[Feed], session: requests.Session, cfg: FetchConfig
) -> list[SourceResult]:
    """Fetch every feed concurrently, preserving the configured order."""
    if not feeds:
        return []

    workers = max(1, min(cfg.max_workers, len(feeds)))
    log.debug("Fetching %d feed(s) with %d worker(s)", len(feeds), workers)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="signal-rss") as pool:
        return list(pool.map(lambda f: fetch_feed(f, session, cfg), feeds))
