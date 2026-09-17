"""Hacker News front page, via the public Algolia search API.

No key, no quota. This is what keeps Signal useful for someone who clones the
repo and runs it without signing up for anything.
"""

from __future__ import annotations

import time
from datetime import timedelta

import requests

from ..config import FetchConfig, HackerNewsConfig
from ..models import Article, utcnow
from .base import SourceResult, parse_timestamp

__all__ = ["fetch_hackernews"]

_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"
_ITEM_URL = "https://news.ycombinator.com/item?id={}"


def fetch_hackernews(
    session: requests.Session, hn: HackerNewsConfig, cfg: FetchConfig
) -> SourceResult:
    """Fetch recent, well-upvoted HN stories. Never raises."""
    started = time.monotonic()
    name = "hackernews"

    if not hn.enabled:
        return SourceResult(name=name, elapsed=0.0)

    since = int((utcnow() - timedelta(hours=cfg.window_hours)).timestamp())
    params: dict[str, str | int] = {
        "tags": "story",
        "numericFilters": f"created_at_i>{since},points>={hn.min_points}",
        "hitsPerPage": max(1, min(hn.max_articles, 100)),
    }

    try:
        response = session.get(_ENDPOINT, params=params, timeout=cfg.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return SourceResult(name=name, error=str(exc), elapsed=time.monotonic() - started)
    except ValueError as exc:
        return SourceResult(name=name, error=f"bad JSON: {exc}", elapsed=time.monotonic() - started)

    articles: list[Article] = []
    for hit in payload.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title:
            continue

        # Ask HN and similar have no external link; point at the discussion.
        url = (hit.get("url") or "").strip() or _ITEM_URL.format(hit.get("objectID", ""))
        points = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)

        articles.append(
            Article.create(
                title=title,
                url=url,
                source="Hacker News",
                summary=f"{points} points, {comments} comments on Hacker News.",
                published=parse_timestamp(hit.get("created_at")),
                origin="hackernews",
                # Front-page consensus is a real signal, so let points nudge rank.
                source_weight=min(1.4, 0.9 + points / 1000.0),
            )
        )

    return SourceResult(name=name, articles=articles, elapsed=time.monotonic() - started)
