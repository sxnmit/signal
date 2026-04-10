"""Deduplication helpers for article normalization and fingerprinting."""

from __future__ import annotations

import hashlib
import re


def normalize_text(value: str) -> str:
    """Lowercase and collapse whitespace for deterministic hashing."""
    lowered = (value or "").strip().lower()
    return re.sub(r"\s+", " ", lowered)


def compute_content_hash(title: str, description: str) -> str:
    """Hash normalized title + description using SHA256."""
    normalized = f"{normalize_text(title)}\n{normalize_text(description)}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()