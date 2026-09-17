"""Article providers.

Each provider turns some remote thing — an RSS feed, a JSON API — into
:class:`~signal_agent.models.Article` values. They all share one contract:
never raise, always return a list, and report failures through
:class:`FetchReport` so one dead feed cannot take down a run.
"""

from __future__ import annotations

from .base import FetchReport, SourceResult, build_session
from .hackernews import fetch_hackernews
from .newsapi import fetch_newsapi
from .registry import collect
from .rss import fetch_feeds

__all__ = [
    "FetchReport",
    "SourceResult",
    "build_session",
    "collect",
    "fetch_feeds",
    "fetch_hackernews",
    "fetch_newsapi",
]
