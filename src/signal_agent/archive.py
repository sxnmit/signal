"""The digest archive: one small JSON file per edition.

This is Signal's durable record. It is plain text, so it diffs cleanly and can
live in git without the repository growing a megabyte a week; it is the input
to the static site; and it is enough to rebuild the database's send history if
that database is ever lost, which is what lets CI run without committing a
binary at all.
"""

from __future__ import annotations

import json
from pathlib import Path

from .logs import get_logger
from .models import Digest

__all__ = ["Archive"]

log = get_logger(__name__)


class Archive:
    """A directory of ``YYYY-MM-DD.json`` digests."""

    def __init__(self, directory: str | Path = "archive") -> None:
        self.directory = Path(directory)

    def path_for(self, date_slug: str) -> Path:
        return self.directory / f"{date_slug}.json"

    def write(self, digest: Digest) -> Path:
        """Persist one edition, replacing any earlier run from the same day."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(digest.date_slug)
        path.write_text(
            json.dumps(digest.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        log.debug("Wrote archive %s", path)
        return path

    def read(self, date_slug: str) -> Digest | None:
        """Load one edition, or ``None`` if it is missing or unreadable."""
        path = self.path_for(date_slug)
        if not path.is_file():
            return None
        try:
            return Digest.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError) as exc:
            log.warning("Skipping unreadable archive %s: %s", path, exc)
            return None

    def dates(self) -> list[str]:
        """Every archived date, newest first."""
        if not self.directory.is_dir():
            return []
        return sorted((p.stem for p in self.directory.glob("*.json")), reverse=True)

    def load_all(self, limit: int | None = None) -> list[Digest]:
        """Load archived editions, newest first."""
        dates = self.dates()
        if limit is not None:
            dates = dates[:limit]
        return [digest for date in dates if (digest := self.read(date)) is not None]

    def latest(self) -> Digest | None:
        """The most recent archived edition."""
        for date in self.dates():
            if (digest := self.read(date)) is not None:
                return digest
        return None

    def sent_urls(self, limit: int | None = None) -> set[str]:
        """Every URL the archive shows as already published.

        Used to rebuild deduplication state when the database is absent, which
        is how CI avoids committing one.
        """
        urls: set[str] = set()
        for digest in self.load_all(limit=limit):
            for section in digest.sections:
                for story in section.stories:
                    urls.add(story.url)
                    urls.update(url for _, url in story.also_covered_by)
        return {url for url in urls if url}
