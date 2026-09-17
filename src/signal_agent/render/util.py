"""Small helpers shared by the renderers."""

from __future__ import annotations

from datetime import datetime

from ..models import Digest, utcnow

__all__ = ["headline_stat", "plural", "time_ago"]


def time_ago(moment: datetime | None, *, now: datetime | None = None) -> str:
    """A compact relative time, e.g. ``"3h ago"``. Empty when unknown."""
    if moment is None:
        return ""

    reference = now or utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=reference.tzinfo)

    seconds = (reference - moment).total_seconds()
    if seconds < 0:
        return "just now"

    minutes = seconds / 60
    if minutes < 60:
        return "just now" if minutes < 2 else f"{int(minutes)}m ago"

    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"

    days = hours / 24
    if days < 7:
        return f"{int(days)}d ago"

    return moment.strftime("%b %d")


def plural(count: int, singular: str, plural_form: str = "") -> str:
    """``3 stories`` / ``1 story``."""
    word = singular if count == 1 else (plural_form or f"{singular}s")
    return f"{count} {word}"


def headline_stat(digest: Digest) -> str:
    """One line describing the edition, used under the masthead.

    Leads with corroboration when there is any, because "four outlets agreed"
    is the most interesting thing Signal can tell you about a day's news.
    """
    stories = [s for section in digest.sections for s in section.stories]
    if not stories:
        return "No new stories today."

    parts = [plural(len(stories), "story", "stories"), plural(len(digest.sections), "topic")]

    best = max((s.corroboration for s in stories), default=1)
    if best > 1:
        parts.append(f"top story confirmed by {best} outlets")

    return " · ".join(parts)
