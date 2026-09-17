"""Run every enabled provider and gather the results into one report."""

from __future__ import annotations

import time

from ..config import Config
from ..logs import get_logger
from ..models import Article
from .base import FetchReport, SourceResult, build_session
from .hackernews import fetch_hackernews
from .newsapi import fetch_newsapi
from .rss import fetch_feeds

__all__ = ["collect"]

log = get_logger(__name__)


def collect(config: Config) -> FetchReport:
    """Fetch from every configured provider, once, in parallel.

    Providers are independent and none of them raise, so a failing feed shows
    up as one line in the report rather than a dead run.
    """
    report = FetchReport()
    started = time.monotonic()
    session = build_session(config.fetch.user_agent)

    try:
        report.extend(fetch_feeds(list(config.feeds), session, config.fetch))

        if config.hackernews.enabled:
            report.add(fetch_hackernews(session, config.hackernews, config.fetch))

        if config.newsapi.configured:
            report.extend(fetch_newsapi(list(config.topics), session, config.newsapi, config.fetch))
        elif config.newsapi.enabled:
            log.debug("NewsAPI skipped: %s is not set", config.newsapi.api_key_env)
    finally:
        session.close()

    for failure in report.failures:
        log.warning("Source %s failed: %s", failure.name, failure.error)

    log.info(
        "Fetched %d article(s) from %d/%d source(s) in %.1fs",
        len(report.articles),
        report.ok_count,
        len(report.results),
        time.monotonic() - started,
    )
    return report


def dedupe_by_url(articles: list[Article]) -> list[Article]:
    """Collapse exact URL repeats, keeping the first (highest-weighted) copy."""
    seen: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        if not article.url or article.url in seen:
            continue
        seen.add(article.url)
        unique.append(article)
    return unique


def probe(config: Config) -> list[SourceResult]:
    """Check every source and report status — what ``signal sources`` prints."""
    session = build_session(config.fetch.user_agent)
    results: list[SourceResult] = []
    try:
        results.extend(fetch_feeds(list(config.feeds), session, config.fetch))
        if config.hackernews.enabled:
            results.append(fetch_hackernews(session, config.hackernews, config.fetch))
        if config.newsapi.configured and config.topics:
            results.extend(
                fetch_newsapi(list(config.topics)[:1], session, config.newsapi, config.fetch)
            )
    finally:
        session.close()
    return results
