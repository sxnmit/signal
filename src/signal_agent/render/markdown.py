"""Markdown rendering, for pasting into notes, wikis, or a pull request."""

from __future__ import annotations

from ..models import Digest
from .util import headline_stat, time_ago

__all__ = ["render_markdown"]


def render_markdown(digest: Digest, *, heading_level: int = 1) -> str:
    """Render a digest as Markdown."""
    top = "#" * max(1, heading_level)
    sub = "#" * max(2, heading_level + 1)

    lines = [
        f"{top} {digest.title} — {digest.generated_at.strftime('%B %d, %Y')}",
        "",
        f"*{headline_stat(digest)}*",
        "",
    ]

    if digest.is_empty:
        lines += ["Nothing new cleared the bar today.", ""]
        return "\n".join(lines)

    for section in digest.sections:
        if not section.stories:
            continue

        lines += [f"{sub} {section.icon} {section.topic}", ""]

        for story in section.stories:
            lines.append(f"**[{_escape(story.headline)}]({story.url})**")

            meta = [story.source]
            if stamp := time_ago(story.published, now=digest.generated_at):
                meta.append(stamp)
            if story.corroboration > 1:
                meta.append(f"**{story.corroboration} outlets**")
            lines += [f"<sub>{' · '.join(meta)}</sub>", "", story.summary]

            if story.also_covered_by:
                also = ", ".join(
                    f"[{_escape(source)}]({url})" for source, url in story.also_covered_by[:5]
                )
                lines += ["", f"<sub>Also covered by {also}</sub>"]

            lines.append("")

    lines += ["---", "", "Assembled by [Signal](https://github.com/sxnmit/signal)."]
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape the characters that would break a Markdown link label."""
    return (text or "").replace("[", "\\[").replace("]", "\\]")
