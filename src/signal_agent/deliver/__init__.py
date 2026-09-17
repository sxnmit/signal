"""Delivery channels."""

from __future__ import annotations

from .smtp import DeliveryResult, send_digest
from .webhook import post_digest

__all__ = ["DeliveryResult", "post_digest", "send_digest"]
