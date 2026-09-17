"""Route clusters to topics and decide which ones are worth publishing.

Ranking happens *before* summarising, which is the point: the expensive stage
only ever sees stories that already earned their place. A run that fetches 600
articles might summarise 40.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..config import RankConfig, Topic
from ..models import Cluster
from .text import keyword_overlap

__all__ = ["assign_topics", "score_cluster", "select"]

# Headlines are far more indicative of subject than feed summaries, which are
# often boilerplate.
_TITLE_SHARE = 0.75


def relevance(cluster: Cluster, topic: Topic) -> float:
    """How strongly a cluster belongs to a topic, 0.0 to 1.0.

    Measured against the cluster's lead article, then nudged up when other
    members independently match the same topic — agreement across outlets is
    evidence the routing is right, not just that one headline used a keyword.
    """
    if not topic.keywords:
        return 0.0

    lead = cluster.lead
    _, title_strength = keyword_overlap(lead.title, topic.keywords)
    _, body_strength = keyword_overlap(lead.summary, topic.keywords)
    score = _TITLE_SHARE * title_strength + (1.0 - _TITLE_SHARE) * body_strength

    if len(cluster.members) > 1:
        agreeing = sum(
            1
            for member in cluster.members[1:]
            if keyword_overlap(member.title, topic.keywords)[0] > 0
        )
        score *= 1.0 + 0.10 * agreeing

    return min(score, 1.0)


def assign_topics(
    clusters: Sequence[Cluster], topics: Sequence[Topic], *, min_relevance: float = 0.05
) -> dict[str, list[Cluster]]:
    """Put every cluster in its single best-matching topic.

    One topic per story, deliberately. A story about an AI chip genuinely
    belongs under both "Artificial Intelligence" and "Chips", but a reader who
    meets it twice in one email experiences that as padding, not coverage.

    Clusters matching nothing are dropped — that is the filter that keeps a
    digest from becoming a feed reader.
    """
    buckets: dict[str, list[Cluster]] = {topic.slug: [] for topic in topics}

    for cluster in clusters:
        best_topic: Topic | None = None
        best_score = 0.0

        for topic in topics:
            score = relevance(cluster, topic)
            # Ties go to the narrower topic: "Chips" is more informative than
            # the broader bucket that also happens to match.
            if score > best_score or (
                score == best_score
                and best_topic is not None
                and len(topic.keywords) < len(best_topic.keywords)
            ):
                best_topic, best_score = topic, score

        if best_topic is None or best_score < min_relevance:
            continue

        cluster.topic = best_topic.slug
        cluster.score = best_score
        buckets[best_topic.slug].append(cluster)

    return buckets


def score_cluster(cluster: Cluster, cfg: RankConfig) -> float:
    """Final publication score for a cluster.

    Three multiplied factors, each on its own scale:

    * **relevance** — how well it matches its topic (set by :func:`assign_topics`);
    * **recency** — an exponential decay, so a twelve-hour-old story is worth
      meaningfully less than a two-hour-old one but is not discarded;
    * **corroboration** — how many independent outlets ran it, which is the
      closest thing a feed reader has to an importance signal.
    """
    recency = 0.5 ** (cluster.lead.age_hours / max(cfg.recency_half_life_hours, 1e-6))
    # Floor the recency term: an older story that three outlets ran still beats
    # a fresh one that nobody else picked up.
    recency_factor = 0.35 + 0.65 * recency

    import math

    corroboration = 1.0 + cfg.corroboration_weight * math.log2(max(cluster.corroboration, 1))
    authority = max(member.source_weight for member in cluster.members)

    return float(cluster.score * recency_factor * corroboration * authority)


def select(
    buckets: dict[str, list[Cluster]], topics: Sequence[Topic], cfg: RankConfig
) -> dict[str, list[Cluster]]:
    """Score, filter, and cap each topic's clusters.

    Returns only topics that still have something to say, so empty sections
    never reach the digest.
    """
    selected: dict[str, list[Cluster]] = {}

    for topic in topics:
        clusters = buckets.get(topic.slug, [])
        if not clusters:
            continue

        for cluster in clusters:
            cluster.score = score_cluster(cluster, cfg)

        ranked = sorted(clusters, key=lambda c: c.score, reverse=True)
        kept = [c for c in ranked if c.score >= cfg.min_score]
        limit = min(topic.max_stories, cfg.max_stories_per_topic)
        kept = kept[:limit]

        if kept:
            selected[topic.slug] = kept

    return _apply_global_cap(selected, cfg.max_clusters_per_run)


def _apply_global_cap(selected: dict[str, list[Cluster]], cap: int) -> dict[str, list[Cluster]]:
    """Trim the weakest stories overall if a run would exceed the summariser budget."""
    total = sum(len(clusters) for clusters in selected.values())
    if cap <= 0 or total <= cap:
        return selected

    survivors = {
        id(cluster)
        for cluster in sorted(
            (c for clusters in selected.values() for c in clusters),
            key=lambda c: c.score,
            reverse=True,
        )[:cap]
    }

    trimmed = {
        slug: [c for c in clusters if id(c) in survivors] for slug, clusters in selected.items()
    }
    return {slug: clusters for slug, clusters in trimmed.items() if clusters}
