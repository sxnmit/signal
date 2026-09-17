"""Core data types shared by every pipeline stage.

The pipeline moves through three shapes:

    Article   a single item as published by one outlet
    Cluster   the same underlying event as covered by 1..n outlets
    Story     a cluster after it has been written up for the digest

Keeping these immutable (or near enough) means each stage is a pure function
of its input, which is what makes the whole pipeline testable offline.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters that change per-visit and would otherwise defeat
# URL-based deduplication.
_TRACKING_PARAMS = frozenset(
    {
        "cmpid",
        "ei",
        "fbclid",
        "gclid",
        "ICID",
        "igshid",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "msclkid",
        "ncid",
        "ref",
        "referrer",
        "s_cid",
        "smid",
        "src",
        "twclid",
        "utm_brand",
        "utm_campaign",
        "utm_content",
        "utm_medium",
        "utm_name",
        "utm_source",
        "utm_term",
        "yclid",
    }
)

_WHITESPACE = re.compile(r"\s+")
# Trailing " - The Verge" / " | Reuters" that most feeds staple onto titles.
_TITLE_SUFFIX = re.compile(r"\s+[-–—|]\s+[^-–—|]{2,40}$")


def utcnow() -> datetime:
    """Timezone-aware current time.

    Used instead of :func:`datetime.utcnow`, which is deprecated and returns a
    naive value that compares badly against feed timestamps.
    """
    return datetime.now(UTC)


def normalize_text(value: str) -> str:
    """Lowercase and collapse whitespace so hashing is deterministic."""
    return _WHITESPACE.sub(" ", (value or "").strip().lower())


def canonical_url(url: str) -> str:
    """Strip tracking noise so the same article from two feeds hashes alike.

    Drops the fragment, removes known tracking query parameters, lowercases the
    host, and trims a trailing slash. The scheme is normalised to ``https`` so
    that ``http://`` and ``https://`` copies of one article collapse together.
    """
    url = (url or "").strip()
    if not url:
        return ""

    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    if not parts.netloc:
        return url

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAMS
    ]
    scheme = "https" if parts.scheme in ("", "http", "https") else parts.scheme
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"

    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def clean_title(title: str) -> str:
    """Remove the outlet name most feeds append to every headline."""
    title = _WHITESPACE.sub(" ", (title or "").strip())
    stripped = _TITLE_SUFFIX.sub("", title)
    # Only accept the trim if a real headline survives it.
    return stripped if len(stripped) >= 25 else title


@dataclass(frozen=True, slots=True)
class Article:
    """One item as published by a single outlet."""

    title: str
    url: str
    source: str
    summary: str = ""
    published: datetime | None = None
    origin: str = "rss"
    """Which provider produced this article (``rss``, ``newsapi``, ``hackernews``)."""
    source_weight: float = 1.0
    """Editorial trust for the outlet, from config. Feeds into ranking."""

    @classmethod
    def create(
        cls,
        *,
        title: str,
        url: str,
        source: str,
        summary: str = "",
        published: datetime | None = None,
        origin: str = "rss",
        source_weight: float = 1.0,
    ) -> Self:
        """Build an article with its title and URL already normalised."""
        return cls(
            title=clean_title(title),
            url=canonical_url(url),
            source=(source or "").strip() or "Unknown",
            summary=_WHITESPACE.sub(" ", (summary or "").strip()),
            published=published,
            origin=origin,
            source_weight=source_weight,
        )

    @property
    def domain(self) -> str:
        """Host of the article URL, used to tell outlets apart when clustering."""
        try:
            return urlsplit(self.url).netloc.lower()
        except ValueError:
            return ""

    @property
    def fingerprint(self) -> str:
        """Stable hash of the normalised title and summary.

        Two feeds carrying identical text produce the same fingerprint even when
        their URLs differ, which catches syndicated wire copy.
        """
        payload = f"{normalize_text(self.title)}\n{normalize_text(self.summary)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def age_hours(self) -> float:
        """Hours since publication; ``0`` when the feed gave no timestamp."""
        if self.published is None:
            return 0.0
        delta = utcnow() - self.published
        return max(delta.total_seconds() / 3600.0, 0.0)

    def with_weight(self, weight: float) -> Article:
        """Return a copy carrying a different source weight."""
        return replace(self, source_weight=weight)


@dataclass(slots=True)
class Cluster:
    """One event, as covered by one or more outlets.

    ``members`` is kept sorted with the strongest article first, so
    :attr:`lead` is the copy the digest should link to and the rest become the
    "also covered by" line.
    """

    members: list[Article]
    score: float = 0.0
    topic: str = ""

    @property
    def lead(self) -> Article:
        """The best article in the cluster — the one the digest links to."""
        return self.members[0]

    @property
    def corroboration(self) -> int:
        """How many distinct outlets ran this story."""
        return len({a.domain or a.source for a in self.members})

    @property
    def others(self) -> list[Article]:
        """Everything except the lead, one per outlet, in rank order."""
        seen = {self.lead.domain or self.lead.source}
        extra: list[Article] = []
        for article in self.members[1:]:
            key = article.domain or article.source
            if key not in seen:
                seen.add(key)
                extra.append(article)
        return extra


@dataclass(slots=True)
class Story:
    """A cluster written up for publication."""

    headline: str
    summary: str
    url: str
    source: str
    score: float = 0.0
    published: datetime | None = None
    corroboration: int = 1
    also_covered_by: list[tuple[str, str]] = field(default_factory=list)
    """``(outlet, url)`` pairs for the other outlets that ran the same story."""

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe form, used by the archive and the static site."""
        return {
            "headline": self.headline,
            "summary": self.summary,
            "url": self.url,
            "source": self.source,
            "score": round(self.score, 4),
            "published": self.published.isoformat() if self.published else None,
            "corroboration": self.corroboration,
            "also_covered_by": [{"source": s, "url": u} for s, u in self.also_covered_by],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Story:
        """Rebuild a story from its archived JSON form."""
        published = data.get("published")
        return cls(
            headline=data.get("headline", ""),
            summary=data.get("summary", ""),
            url=data.get("url", ""),
            source=data.get("source", ""),
            score=float(data.get("score", 0.0)),
            published=datetime.fromisoformat(published) if published else None,
            corroboration=int(data.get("corroboration", 1)),
            also_covered_by=[
                (item["source"], item["url"]) for item in data.get("also_covered_by", [])
            ],
        )


@dataclass(slots=True)
class Section:
    """All the stories selected for one topic."""

    topic: str
    slug: str
    icon: str
    stories: list[Story]

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "slug": self.slug,
            "icon": self.icon,
            "stories": [s.to_dict() for s in self.stories],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Section:
        return cls(
            topic=data.get("topic", ""),
            slug=data.get("slug", ""),
            icon=data.get("icon", ""),
            stories=[Story.from_dict(s) for s in data.get("stories", [])],
        )


@dataclass(slots=True)
class RunStats:
    """What one pipeline run actually did. Printed, archived, and shown in the email."""

    fetched: int = 0
    after_dedup: int = 0
    clusters: int = 0
    published: int = 0
    sources_ok: int = 0
    sources_failed: int = 0
    duration_seconds: float = 0.0
    summarizer: str = "extractive"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "after_dedup": self.after_dedup,
            "clusters": self.clusters,
            "published": self.published,
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "duration_seconds": round(self.duration_seconds, 2),
            "summarizer": self.summarizer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunStats:
        return cls(**{k: v for k, v in data.items() if k in cls.__slots__})


@dataclass(slots=True)
class Digest:
    """One complete edition: everything needed to render or re-render it."""

    generated_at: datetime
    sections: list[Section]
    stats: RunStats = field(default_factory=RunStats)
    title: str = "Signal"

    @property
    def date_slug(self) -> str:
        """``YYYY-MM-DD``, used as the archive filename and permalink."""
        return self.generated_at.strftime("%Y-%m-%d")

    @property
    def story_count(self) -> int:
        return sum(len(s.stories) for s in self.sections)

    @property
    def is_empty(self) -> bool:
        return self.story_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "date": self.date_slug,
            "stats": self.stats.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Digest:
        return cls(
            generated_at=datetime.fromisoformat(data["generated_at"]),
            sections=[Section.from_dict(s) for s in data.get("sections", [])],
            stats=RunStats.from_dict(data.get("stats", {})),
            title=data.get("title", "Signal"),
        )
