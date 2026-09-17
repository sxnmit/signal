"""Summariser selection."""

from __future__ import annotations

from ..config import SummarizeConfig
from ..logs import get_logger
from .base import Summarizer, story_from_cluster
from .extractive import ExtractiveSummarizer
from .llm import LLMSummarizer

__all__ = [
    "ExtractiveSummarizer",
    "LLMSummarizer",
    "Summarizer",
    "get_summarizer",
    "story_from_cluster",
]

log = get_logger(__name__)


def get_summarizer(cfg: SummarizeConfig) -> Summarizer:
    """Build the configured summariser.

    ``provider = "auto"`` picks the language model when an API key is present
    and the extractive summariser when it is not, so a fresh clone produces a
    real digest without anyone signing up for anything.
    """
    provider = cfg.resolved_provider()

    if provider == "llm":
        if not cfg.api_key:
            log.warning(
                "Summarizer 'llm' requested but %s is not set; using extractive",
                cfg.api_key_env,
            )
            return ExtractiveSummarizer()
        return LLMSummarizer(cfg)

    if provider != "extractive":
        log.warning("Unknown summarizer '%s'; using extractive", provider)

    return ExtractiveSummarizer()
