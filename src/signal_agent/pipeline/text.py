"""Text utilities behind clustering and ranking.

Everything here is deliberately dependency-free. Pulling in scikit-learn to
compare a few thousand headlines a day would cost more than it buys, and an
IDF-weighted cosine over title tokens turns out to separate "same story,
different outlet" from "different story" remarkably well.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

__all__ = [
    "STOPWORDS",
    "idf_weights",
    "keyword_overlap",
    "sentences",
    "similarity",
    "tokenize",
]

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'’\-]*")
_POSSESSIVE_RE = re.compile(r"['’]s$")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'“])")

# Function words plus the filler that headlines are made of. Removing them
# stops "the" and "says" from making every pair of headlines look related.
_STOPWORD_TEXT = """
    a about above after again against all also am an and any are aren't as at be because been
    before being below between both but by can cannot could couldn't did didn't do does doesn't
    doing don't down during each few for from further had hadn't has hasn't have haven't having
    he her here hers herself him himself his how i if in into is isn't it its itself just let's
    me more most mustn't my myself new no nor not of off on once only or other ought our ours
    ourselves out over own report reports said same say says shan't she should shouldn't so some
    such than that that's the their theirs them themselves then there these they this those
    through to too under until up very was wasn't we were weren't what when where which while who
    whom why with won't would wouldn't you your yours yourself yourselves amid via first
    """

STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str, *, keep_stopwords: bool = False, min_length: int = 2) -> list[str]:
    """Split text into comparable lowercase tokens.

    Two deliberate choices, both learned from headlines that failed to match:

    * possessives are folded, so ``Nvidia's`` and ``Nvidia`` are one token;
    * the minimum length is 2, because ``AI``, ``EU``, ``UN`` and ``US`` are
      among the most load-bearing tokens in news writing. Short function words
      are removed by the stopword list instead.
    """
    tokens: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        token = _POSSESSIVE_RE.sub("", match.group(0)).strip("-'’")
        if not token:
            continue
        if not keep_stopwords and token in STOPWORDS:
            continue
        if len(token) < min_length and not token.isdigit():
            continue
        tokens.append(token)
    return tokens


def idf_weights(documents: Sequence[Sequence[str]]) -> dict[str, float]:
    """Smoothed inverse document frequency for every token in the corpus.

    Rare tokens ("nvidia", "ceasefire") end up weighted far above common ones
    ("company", "new"), which is exactly the discrimination clustering needs.
    """
    total = max(len(documents), 1)
    counts: Counter[str] = Counter()
    for tokens in documents:
        counts.update(set(tokens))

    return {token: math.log((total + 1) / (count + 1)) + 1.0 for token, count in counts.items()}


def similarity(
    left: Iterable[str],
    right: Iterable[str],
    weights: dict[str, float] | None = None,
    *,
    containment: float = 0.6,
) -> float:
    """How likely two token sets describe the same thing. 0.0 to 1.0.

    Blends two measures, because neither works alone for headlines:

    * **cosine** is symmetric and well behaved, but punishes a short headline
      paired with a long one even when the short one is entirely contained in
      the long one — which is the single most common way two outlets cover the
      same story.
    * **containment** (the weighted overlap coefficient) handles exactly that
      case, but on its own will happily match a three-word headline against
      anything that includes those three words.

    ``containment`` sets the blend. Tokens are weighted by IDF when ``weights``
    is supplied, so sharing "nvidia" counts for far more than sharing "report".
    """
    a, b = set(left), set(right)
    if not a or not b:
        return 0.0

    shared = a & b
    if not shared:
        return 0.0

    def mass(tokens: set[str]) -> float:
        if weights is None:
            return float(len(tokens))
        # Linear, not squared: squaring over-amplifies IDF, which perversely
        # penalises the shared entity tokens that signal a match in the first
        # place (they recur across the cluster, so their IDF is lower).
        return sum(weights.get(t, 1.0) for t in tokens)

    shared_mass = mass(shared)
    left_mass, right_mass = mass(a), mass(b)

    denominator = math.sqrt(left_mass * right_mass)
    cosine = shared_mass / denominator if denominator else 0.0
    smaller = min(left_mass, right_mass)
    overlap = shared_mass / smaller if smaller else 0.0

    blend = max(0.0, min(1.0, containment))
    return (1.0 - blend) * cosine + blend * min(overlap, 1.0)


def keyword_overlap(text: str, keywords: Sequence[str]) -> tuple[int, float]:
    """How strongly ``text`` matches a topic's vocabulary.

    Returns the number of distinct keywords hit and a 0-1 strength, saturating
    so that a headline matching five keywords is not scored five times higher
    than one matching two. Multi-word keywords are matched as phrases.
    """
    if not keywords:
        return 0, 0.0

    lowered = f" {' '.join(tokenize(text, keep_stopwords=True, min_length=1))} "
    hits = 0
    for keyword in keywords:
        needle = f" {' '.join(tokenize(keyword, keep_stopwords=True, min_length=1))} "
        if needle.strip() and needle in lowered:
            hits += 1

    # 1 hit -> 0.5, 2 -> 0.71, 3 -> 0.82, 4 -> 0.89 ...
    strength = 1.0 - 0.5**hits if hits else 0.0
    return hits, strength


def capitalized_tokens(text: str) -> set[str]:
    """Tokens written with a capital letter somewhere other than the start.

    The sentence-initial word is skipped because its capital says nothing. The
    result is lowercased so it can be compared against :func:`tokenize` output.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9'’\-]*", text or "")
    found: set[str] = set()
    for position, word in enumerate(words):
        if position == 0 or not word[0].isupper():
            continue
        token = _POSSESSIVE_RE.sub("", word.lower()).strip("-'’")
        if len(token) >= 2 and token not in STOPWORDS:
            found.add(token)
    return found


def entity_vocabulary(texts: Sequence[str], *, min_ratio: float = 0.6) -> set[str]:
    """Tokens that behave like proper nouns across the whole corpus.

    Deciding per-headline does not work. Many outlets set headlines in Title
    Case, where every word is capitalised and nothing stands out; and a token
    that happens to open a headline is capitalised for reasons of grammar, not
    because it names anything.

    Judging across the corpus handles both. A token is an entity when it is
    capitalised in most of the headlines that contain it, where:

    * a headline-initial occurrence **abstains** rather than voting against —
      "Nvidia unveils..." says nothing either way about ``nvidia``, and
      counting it as lowercase evidence is enough on its own to hide the most
      important entity in a story; and
    * a Title Case headline gets a half vote, so those outlets contribute
      evidence without swamping it.
    """
    total: Counter[str] = Counter()
    capitalized: Counter[str] = Counter()

    for text in texts:
        tokens = set(tokenize(text))
        if not tokens:
            continue

        caps = capitalized_tokens(text)
        leading = _leading_token(text)
        title_case = len(caps) >= 0.7 * len(tokens)

        for token in tokens:
            if token == leading:
                continue
            total[token] += 2
            if token in caps:
                capitalized[token] += 1 if title_case else 2

    return {
        token for token, count in total.items() if count and capitalized[token] / count >= min_ratio
    }


def _leading_token(text: str) -> str:
    """The first word of ``text``, normalised — its capital carries no meaning."""
    match = re.search(r"[A-Za-z][A-Za-z0-9'’\-]*", text or "")
    if not match:
        return ""
    return _POSSESSIVE_RE.sub("", match.group(0).lower()).strip("-'’")


def sentences(text: str) -> list[str]:
    """Split a blob into sentences, well enough for extractive summarising."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return []
    return [s.strip() for s in _SENTENCE_RE.split(cleaned) if s.strip()]
