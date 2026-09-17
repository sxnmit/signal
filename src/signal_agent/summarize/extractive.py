"""Summarising without an API key.

Signal's default. It scores each sentence available for a cluster by how much
significant vocabulary it shares with the cluster's headlines, then keeps the
best couple. The result is not as fluent as a language model's, but it is
free, instant, offline, and — because every sentence is quoted verbatim from
the source — incapable of inventing a fact.
"""

from __future__ import annotations

from ..config import Topic
from ..models import Cluster, Story
from ..pipeline.text import idf_weights, sentences, tokenize
from .base import story_from_cluster

__all__ = ["ExtractiveSummarizer"]

_MAX_SENTENCES = 2
_MAX_CHARS = 320
_MIN_SENTENCE_TOKENS = 4


class ExtractiveSummarizer:
    """Picks the most representative sentences already present in the sources."""

    name = "extractive"

    def write(self, topic: Topic, clusters: list[Cluster]) -> list[Story]:  # noqa: ARG002
        # `topic` is unused here but required by the Summarizer protocol: the
        # language-model summarizer needs it, this one works purely from the
        # text the sources already provide.
        return [story_from_cluster(c, summary=self._summarize(c)) for c in clusters]

    def _summarize(self, cluster: Cluster) -> str:
        """Choose the sentences that best represent a cluster."""
        candidates: list[str] = []
        for article in cluster.members:
            candidates.extend(sentences(article.summary))

        candidates = [s for s in candidates if len(tokenize(s)) >= _MIN_SENTENCE_TOKENS]
        if not candidates:
            return cluster.lead.summary[:_MAX_CHARS]

        # Weight against the whole cluster: a sentence that echoes vocabulary
        # every member uses is describing the event, not one outlet's angle.
        headline_tokens = {t for a in cluster.members for t in tokenize(a.title)}
        tokenized = [tokenize(s) for s in candidates]
        weights = idf_weights(tokenized)

        def score(index: int) -> float:
            tokens = set(tokenized[index])
            if not tokens:
                return 0.0
            overlap = sum(weights.get(t, 1.0) for t in tokens & headline_tokens)
            # Normalise by length so a long sentence cannot win on volume alone,
            # with a mild preference for sentences carrying real content.
            return float(overlap / (len(tokens) ** 0.5))

        order = sorted(range(len(candidates)), key=score, reverse=True)

        chosen: list[tuple[int, str]] = []
        used_tokens: set[str] = set()
        for index in order:
            if len(chosen) >= _MAX_SENTENCES:
                break
            tokens = set(tokenized[index])
            # Skip anything that mostly repeats a sentence already chosen.
            if tokens and used_tokens and len(tokens & used_tokens) / len(tokens) > 0.7:
                continue
            chosen.append((index, candidates[index]))
            used_tokens |= tokens

        # Restore source order so the two sentences read as a paragraph.
        chosen.sort(key=lambda pair: pair[0])
        text = " ".join(sentence for _, sentence in chosen)

        if len(text) > _MAX_CHARS:
            text = text[:_MAX_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        return text
