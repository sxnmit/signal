"""Signal — a news agent that finds the story, not just the articles.

The package is organised as a pipeline:

    sources  ->  pipeline  ->  summarize  ->  render  ->  deliver
    (fetch)      (dedupe,      (write the    (email,     (smtp,
                  cluster,      digest)       markdown,   webhook,
                  rank)                       terminal,   console)
                                              site)

Every stage is swappable and every stage is pure enough to test without a
network connection.
"""

from __future__ import annotations

__version__ = "2.0.0"

__all__ = ["__version__"]
