"""The summariser contract.

A summariser turns ranked clusters into publishable :class:`Story` values. It
never invents a URL: links always come from the fetched article, so no
summariser — least of all a language model — can send a reader somewhere that
does not exist.
"""

from __future__ import annotations

from typing import Protocol

from ..config import Topic
from ..models import Cluster, Story

__all__ = ["Summarizer", "story_from_cluster"]


class Summarizer(Protocol):
    """Writes the digest copy for one topic's clusters."""

    name: str

    def write(self, topic: Topic, clusters: list[Cluster]) -> list[Story]:
        """Return one story per cluster, in the order given."""
        ...


def story_from_cluster(cluster: Cluster, *, headline: str = "", summary: str = "") -> Story:
    """Build a :class:`Story` from a cluster, keeping every link authoritative.

    ``headline`` and ``summary`` are the only things a summariser may supply.
    The URL, outlet, timestamp and corroboration list are copied from the
    fetched articles.
    """
    lead = cluster.lead
    return Story(
        headline=headline.strip() or lead.title,
        summary=summary.strip() or lead.summary,
        url=lead.url,
        source=lead.source,
        score=cluster.score,
        published=lead.published,
        corroboration=cluster.corroboration,
        also_covered_by=[(a.source, a.url) for a in cluster.others],
    )
