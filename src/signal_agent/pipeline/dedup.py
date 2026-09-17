"""Exact-duplicate removal, before the more expensive clustering pass."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import Article

__all__ = ["drop_duplicates", "within_window"]


def drop_duplicates(articles: Iterable[Article]) -> list[Article]:
    """Collapse articles sharing a canonical URL or a content fingerprint.

    Canonicalisation already stripped tracking parameters, so this catches the
    same link arriving from two feeds. The fingerprint check additionally
    catches wire copy republished at different URLs with identical text.

    Where copies compete, the one from the higher-weighted source wins, and a
    copy carrying a real timestamp beats one without.
    """
    best: dict[str, Article] = {}
    order: list[str] = []

    for article in articles:
        if not article.url or not article.title:
            continue

        for key in (f"url:{article.url}", f"hash:{article.fingerprint}"):
            existing = best.get(key)
            if existing is None:
                best[key] = article
                if key.startswith("url:"):
                    order.append(key)
            elif _prefer(article, existing):
                best[key] = article

    # Walk the URL keys in arrival order, skipping anything a fingerprint
    # collision has already demoted.
    seen_fingerprints: set[str] = set()
    result: list[Article] = []
    for key in order:
        winner = best[key]
        fingerprint_winner = best[f"hash:{winner.fingerprint}"]
        if fingerprint_winner.url != winner.url:
            continue
        if winner.fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(winner.fingerprint)
        result.append(winner)

    return result


def _prefer(candidate: Article, incumbent: Article) -> bool:
    """Whether ``candidate`` is the better copy of a duplicate pair."""
    if candidate.source_weight != incumbent.source_weight:
        return candidate.source_weight > incumbent.source_weight
    if (candidate.published is None) != (incumbent.published is None):
        return incumbent.published is None
    if len(candidate.summary) != len(incumbent.summary):
        return len(candidate.summary) > len(incumbent.summary)
    return False


def within_window(articles: Iterable[Article], window_hours: int) -> list[Article]:
    """Keep articles published inside the window.

    Undated articles are kept: plenty of feeds omit timestamps, and dropping
    them would silently lose whole outlets.
    """
    if window_hours <= 0:
        return list(articles)
    return [a for a in articles if a.published is None or a.age_hours <= window_hours]
