"""Webhook delivery, for Slack, Discord, or anything that takes JSON."""

from __future__ import annotations

from typing import Any

import requests

from ..config import WebhookConfig
from ..logs import get_logger
from ..models import Digest
from ..render.markdown import render_markdown
from ..render.util import headline_stat

__all__ = ["post_digest"]

log = get_logger(__name__)

# Slack rejects blocks over 3000 characters and messages over 50 blocks.
_SLACK_TEXT_LIMIT = 2900
_SLACK_BLOCK_LIMIT = 45
_DISCORD_LIMIT = 1900


def build_payload(digest: Digest, cfg: WebhookConfig) -> dict[str, Any]:
    """Shape the digest for the configured webhook flavour."""
    if cfg.format == "slack":
        return _slack_payload(digest)
    if cfg.format == "discord":
        return {"content": _truncate(render_markdown(digest, heading_level=2), _DISCORD_LIMIT)}
    return digest.to_dict()


def _slack_payload(digest: Digest) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📡 {digest.title} — {digest.generated_at.strftime('%b %d')}",
            },
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": headline_stat(digest)}],
        },
    ]

    for section in digest.sections:
        if not section.stories or len(blocks) >= _SLACK_BLOCK_LIMIT:
            break

        lines = [f"*{section.icon} {section.topic}*"]
        for story in section.stories:
            badge = f"  `{story.corroboration} outlets`" if story.corroboration > 1 else ""
            lines.append(f"• <{story.url}|{_escape_slack(story.headline)}>{badge}")
            lines.append(f"  _{_escape_slack(story.summary)}_")

        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": _truncate("\n".join(lines), _SLACK_TEXT_LIMIT)},
            }
        )

    return {"text": f"{digest.title} — {headline_stat(digest)}", "blocks": blocks}


def _escape_slack(text: str) -> str:
    """Escape the three characters Slack treats as markup."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def post_digest(
    digest: Digest, cfg: WebhookConfig, *, session: requests.Session | None = None
) -> bool:
    """POST the digest to the configured webhook. Returns success."""
    if not cfg.configured:
        return False

    http = session or requests.Session()
    try:
        response = http.post(cfg.url, json=build_payload(digest, cfg), timeout=20)
        if response.status_code >= 400:
            log.warning("Webhook rejected the digest: HTTP %s", response.status_code)
            return False
    except requests.RequestException as exc:
        log.warning("Webhook delivery failed: %s", exc)
        return False
    finally:
        if session is None:
            http.close()

    log.info("Digest posted to webhook")
    return True
