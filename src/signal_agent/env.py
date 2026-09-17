"""Minimal ``.env`` loader.

A dependency-free stand-in for ``python-dotenv``: Signal needs to read a handful
of ``KEY=value`` lines, not the full spec, and dropping the package keeps the
runtime dependencies down to ``feedparser`` and ``requests``.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["load_dotenv", "parse_dotenv"]


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse ``.env`` text into a mapping.

    Understands comments, blank lines, ``export`` prefixes, and single- or
    double-quoted values. Escape sequences inside double quotes are honoured;
    single-quoted values are taken literally, as in POSIX shells.
    """
    values: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = value.encode("utf-8").decode("unicode_escape")
        else:
            # An unquoted value ends at the first inline comment.
            value = value.split(" #", 1)[0].strip()

        values[key] = value

    return values


def load_dotenv(path: str | Path = ".env", *, override: bool = False) -> dict[str, str]:
    """Load ``path`` into :data:`os.environ` and return what it contained.

    Real environment variables win by default, so a value exported by CI (or by
    GitHub Actions secrets) is never clobbered by a stale local file.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return {}

    values = parse_dotenv(env_path.read_text(encoding="utf-8"))
    for key, value in values.items():
        if override or key not in os.environ:
            os.environ[key] = value

    return values
