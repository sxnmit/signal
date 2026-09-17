"""Renderers: one digest, many surfaces."""

from __future__ import annotations

from .email import render_email, render_plaintext
from .markdown import render_markdown
from .site import build_site
from .terminal import render_terminal
from .util import headline_stat, time_ago

__all__ = [
    "build_site",
    "headline_stat",
    "render_email",
    "render_markdown",
    "render_plaintext",
    "render_terminal",
    "time_ago",
]
