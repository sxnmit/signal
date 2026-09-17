"""Shared plumbing for every provider: HTTP sessions, date parsing, reporting."""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import Article

__all__ = ["FetchReport", "SourceResult", "build_session", "parse_timestamp"]


def build_session(user_agent: str, *, retries: int = 2) -> requests.Session:
    """An HTTP session with a real user agent and bounded retries.

    Feeds and news APIs fail transiently often enough that a bare
    ``requests.get`` produces noisy, unreproducible runs. Retries cover
    connection errors and 5xx responses only — a 404 is answered immediately.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})

    retry = Retry(
        total=retries,
        connect=retries,
        read=retries,
        status=retries,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def parse_timestamp(value: object) -> datetime | None:
    """Best-effort parse of the many date shapes feeds emit.

    Handles ISO 8601 (with a trailing ``Z``), RFC 2822, and the 9-tuple
    ``feedparser`` produces. Always returns a timezone-aware value in UTC, or
    ``None`` when nothing usable is there.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    if isinstance(value, time.struct_time):
        return datetime(*value[:6], tzinfo=UTC)

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


@dataclass(slots=True)
class SourceResult:
    """What one provider returned, and whether it worked."""

    name: str
    articles: list[Article] = field(default_factory=list)
    error: str | None = None
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(slots=True)
class FetchReport:
    """Every provider's outcome for a single run."""

    results: list[SourceResult] = field(default_factory=list)

    def add(self, result: SourceResult) -> None:
        self.results.append(result)

    def extend(self, results: Iterable[SourceResult]) -> None:
        self.results.extend(results)

    @property
    def articles(self) -> list[Article]:
        """Everything fetched, in provider order."""
        return [article for result in self.results for article in result.articles]

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.ok)

    @property
    def failures(self) -> list[SourceResult]:
        return [r for r in self.results if not r.ok]
