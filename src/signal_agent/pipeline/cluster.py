"""Group articles that are covering the same underlying event.

This is the feature that makes Signal a digest rather than a link dump: when
four outlets run the same story, the reader should see one entry with four
sources attached, not four entries.

The approach is a blocked pairwise comparison. Building an inverted index over
rare tokens means each article is only compared against the handful of others
that share distinctive vocabulary, so the cost stays near-linear instead of
quadratic in the corpus size.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from ..models import Article, Cluster
from .text import entity_vocabulary, idf_weights, similarity, tokenize

__all__ = ["cluster_articles"]

# Tokens appearing in more than this share of the corpus are useless for
# blocking — they would put every article in the same candidate bucket. The
# floor matters: on a small run, the tokens that define a cluster are a large
# fraction of the corpus by definition, and a purely proportional cap would
# throw away exactly the pairs worth comparing. Comparing everything is cheap
# at this size anyway.
_MAX_BLOCK_DF = 0.20
_MIN_BLOCK_DF_FLOOR = 8
# A candidate pair must share at least this many blocking tokens.
_MIN_SHARED_TOKENS = 2
# How much the headline counts relative to the body when scoring a pair.
_TITLE_SHARE = 0.65
# A headline match this far above the threshold merges on its own.
_TITLE_SHORTCUT = 0.12
# Two articles sharing this many rare named entities are the same story.
_MIN_SHARED_ENTITIES = 2
# An entity counts as rare when it appears in no more than this share of the
# corpus, with a floor so the rule still fires on small runs: an entity naming
# a story that six outlets covered is exactly the case this is meant to catch.
_MAX_ENTITY_DF = 0.08
_MIN_ENTITY_DF_FLOOR = 6
# How much agreement between summaries can lift a borderline headline match.
_BODY_BOOST = 0.30


class _UnionFind:
    """Disjoint sets, used to turn pairwise matches into transitive groups."""

    def __init__(self, size: int) -> None:
        self._parent = list(range(size))
        self._rank = [0] * size

    def find(self, item: int) -> int:
        while self._parent[item] != item:
            self._parent[item] = self._parent[self._parent[item]]  # path halving
            item = self._parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a == b:
            return
        if self._rank[a] < self._rank[b]:
            a, b = b, a
        self._parent[b] = a
        if self._rank[a] == self._rank[b]:
            self._rank[a] += 1


def cluster_articles(articles: Sequence[Article], threshold: float = 0.62) -> list[Cluster]:
    """Group articles into events.

    ``threshold`` is the IDF-weighted cosine similarity at which two headlines
    are judged to be the same story. Each returned cluster has its strongest
    article first, so ``cluster.lead`` is the copy worth linking to.
    """
    items = list(articles)
    if not items:
        return []
    if len(items) == 1:
        return [Cluster(members=list(items))]

    title_tokens = [tokenize(a.title) for a in items]
    body_tokens = [tokenize(f"{a.title} {a.summary}") for a in items]
    weights = idf_weights(body_tokens)

    # Rare named entities are the strongest evidence in news: two outlets that
    # both say "Nvidia" and "Rubin" are covering one event even when the rest of
    # their headlines share nothing.
    entities = entity_vocabulary([a.title for a in items])
    document_frequency = Counter(token for tokens in title_tokens for token in set(tokens))
    max_entity_df = max(_MIN_ENTITY_DF_FLOOR, int(len(items) * _MAX_ENTITY_DF))
    rare_entities = [
        {t for t in tokens if t in entities and document_frequency[t] <= max_entity_df}
        for tokens in title_tokens
    ]

    # -- block on rare tokens --------------------------------------------
    postings: dict[str, list[int]] = defaultdict(list)
    for index, tokens in enumerate(title_tokens):
        for token in set(tokens):
            postings[token].append(index)

    max_df = max(_MIN_BLOCK_DF_FLOOR, int(len(items) * _MAX_BLOCK_DF))
    candidates: dict[int, set[int]] = defaultdict(set)
    shared_counts: dict[tuple[int, int], int] = defaultdict(int)

    for indices in postings.values():
        if len(indices) > max_df:
            continue
        for position, left in enumerate(indices):
            for right in indices[position + 1 :]:
                shared_counts[(left, right)] += 1

    for (left, right), count in shared_counts.items():
        if count >= _MIN_SHARED_TOKENS:
            candidates[left].add(right)

    # -- compare the surviving pairs --------------------------------------
    groups = _UnionFind(len(items))
    for left, rights in candidates.items():
        for right in rights:
            if _same_story(
                left, right, title_tokens, body_tokens, rare_entities, weights, threshold
            ):
                groups.union(left, right)

    buckets: dict[int, list[int]] = defaultdict(list)
    for index in range(len(items)):
        buckets[groups.find(index)].append(index)

    clusters: list[Cluster] = []
    for indices in buckets.values():
        members = _order_members(indices, items, title_tokens, weights)
        clusters.append(Cluster(members=members))

    # Biggest stories first; ranking refines this per topic later.
    clusters.sort(key=lambda c: (c.corroboration, -c.lead.age_hours), reverse=True)
    return clusters


def _same_story(
    left: int,
    right: int,
    titles: list[list[str]],
    bodies: list[list[str]],
    entities: list[set[str]],
    weights: dict[str, float],
    threshold: float,
) -> bool:
    """Decide whether two candidate articles cover the same event.

    Three pieces of evidence, in descending order of reliability:

    1. **Shared rare entities.** Two headlines that both name "Nvidia" and
       "Rubin" are covering one story, full stop — this is what catches an
       analysis piece whose headline shares no other vocabulary with the news
       report it is responding to.
    2. **Headline similarity**, the general case.
    3. **Summary agreement**, which can only lift a borderline headline match,
       never sink it. Feed summaries are noisy and long, so blending them in
       directly drags every score toward zero.
    """
    if len(entities[left] & entities[right]) >= _MIN_SHARED_ENTITIES:
        return True

    title_score = similarity(titles[left], titles[right], weights)
    if title_score >= threshold + _TITLE_SHORTCUT:
        return True

    body_score = similarity(bodies[left], bodies[right], weights)
    return title_score * (1.0 + _BODY_BOOST * body_score) >= threshold


def _order_members(
    indices: list[int],
    items: list[Article],
    title_tokens: list[list[str]],
    weights: dict[str, float],
) -> list[Article]:
    """Order a cluster's articles, most representative first.

    Source weight alone picks badly: the most *trusted* outlet in a cluster is
    often the one running analysis ("Rubin: Nvidia bets the next era of AI is
    about serving"), which makes a poor headline for a news digest. Centrality —
    how much a headline resembles the rest of its cluster — picks the copy that
    states the story plainly, which is what a reader wants to click.

    Source weight still breaks ties, so among equally representative write-ups
    the better outlet leads.
    """
    if len(indices) == 1:
        return [items[indices[0]]]

    def centrality(index: int) -> float:
        others = [i for i in indices if i != index]
        return sum(
            similarity(title_tokens[index], title_tokens[other], weights) for other in others
        ) / len(others)

    ranked = sorted(
        indices,
        key=lambda i: (
            centrality(i) * (0.7 + 0.3 * items[i].source_weight),
            -items[i].age_hours,
        ),
        reverse=True,
    )
    return [items[i] for i in ranked]
