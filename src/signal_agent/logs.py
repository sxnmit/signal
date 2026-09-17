"""Console logging with just enough colour to scan a run at a glance."""

from __future__ import annotations

import logging
import os
import sys

__all__ = ["get_logger", "setup_logging"]

_RESET = "\033[0m"
_LEVEL_COLORS = {
    logging.DEBUG: "\033[38;5;245m",
    logging.INFO: "\033[38;5;39m",
    logging.WARNING: "\033[38;5;214m",
    logging.ERROR: "\033[38;5;203m",
    logging.CRITICAL: "\033[1;38;5;203m",
}
_LEVEL_GLYPHS = {
    logging.DEBUG: "·",
    logging.INFO: "›",
    logging.WARNING: "!",
    logging.ERROR: "✗",
    logging.CRITICAL: "✗",
}


def supports_color(stream: object = None) -> bool:
    """Whether ANSI colour is safe to emit on ``stream``.

    Honours ``NO_COLOR`` and ``FORCE_COLOR``; otherwise requires a TTY.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    stream = stream or sys.stderr
    return bool(getattr(stream, "isatty", lambda: False)())


class ConsoleFormatter(logging.Formatter):
    """One-line records: a coloured glyph, then the message."""

    def __init__(self, *, color: bool) -> None:
        super().__init__()
        self.color = color

    def format(self, record: logging.LogRecord) -> str:
        glyph = _LEVEL_GLYPHS.get(record.levelno, "›")
        message = record.getMessage()

        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        if not self.color:
            return f"{glyph} {message}"

        tint = _LEVEL_COLORS.get(record.levelno, "")
        return f"{tint}{glyph}{_RESET} {message}"


def setup_logging(verbosity: int = 0, *, quiet: bool = False) -> None:
    """Configure the ``signal_agent`` logger tree.

    ``verbosity`` counts ``-v`` flags: 0 is INFO, 1 or more is DEBUG. ``quiet``
    drops everything below WARNING.
    """
    if quiet:
        level = logging.WARNING
    elif verbosity >= 1:
        level = logging.DEBUG
    else:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ConsoleFormatter(color=supports_color(sys.stderr)))

    root = logging.getLogger("signal_agent")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False

    # Third-party chatter is never useful at our INFO level.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Logger for a module inside the package."""
    suffix = name.removeprefix("signal_agent.")
    return logging.getLogger(f"signal_agent.{suffix}" if suffix != name else name)
