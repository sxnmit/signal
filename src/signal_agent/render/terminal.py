"""Terminal rendering, so you can read the digest without sending anything."""

from __future__ import annotations

import shutil

from ..logs import supports_color
from ..models import Digest
from .util import headline_stat, time_ago

__all__ = ["render_terminal"]

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_UNDER = "\033[4m"
_TOPIC_COLORS = [
    "\033[38;5;39m",
    "\033[38;5;44m",
    "\033[38;5;42m",
    "\033[38;5;135m",
    "\033[38;5;204m",
    "\033[38;5;208m",
    "\033[38;5;33m",
    "\033[38;5;112m",
]


def render_terminal(digest: Digest, *, color: bool | None = None, width: int | None = None) -> str:
    """Render a digest for a terminal, wrapped to the available width."""
    use_color = supports_color() if color is None else color
    columns = width or min(shutil.get_terminal_size((88, 24)).columns, 96)

    def paint(text: str, *codes: str) -> str:
        return f"{''.join(codes)}{text}{_RESET}" if use_color and codes else text

    out: list[str] = [
        "",
        paint(digest.title.upper(), _BOLD)
        + paint(f"  {digest.generated_at.strftime('%a %d %b %Y')}", _DIM),
        paint(headline_stat(digest), _DIM),
        paint("─" * columns, _DIM),
    ]

    if digest.is_empty:
        out += ["", "  Nothing new cleared the bar today.", ""]
        return "\n".join(out)

    for index, section in enumerate(digest.sections):
        if not section.stories:
            continue

        tint = _TOPIC_COLORS[index % len(_TOPIC_COLORS)]
        out += ["", paint(f"{section.icon} {section.topic.upper()}", _BOLD, tint)]

        for story in section.stories:
            badge = (
                paint(f" [{story.corroboration} outlets]", tint) if story.corroboration > 1 else ""
            )
            out.append("")
            for line_number, line in enumerate(_wrap(story.headline, columns - 4)):
                prefix = paint("  ▍ ", tint) if line_number == 0 else "    "
                out.append(prefix + paint(line, _BOLD))

            meta = story.source
            if stamp := time_ago(story.published, now=digest.generated_at):
                meta += f" · {stamp}"
            out.append("    " + paint(meta, _DIM) + badge)

            for line in _wrap(story.summary, columns - 4):
                out.append("    " + line)

            out.append("    " + paint(story.url, _DIM, _UNDER))

    out += ["", paint("─" * columns, _DIM), ""]
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap; never splits a word, never returns an empty list."""
    import textwrap

    wrapped = textwrap.wrap(text or "", width=max(width, 20))
    return wrapped or [""]
