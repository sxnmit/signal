"""Summarising with a language model.

Two deliberate differences from how v1 did this:

* **The model returns JSON, keyed by index.** v1 asked for a bespoke
  ``HEADLINE:``/``---`` text format and parsed it by hand, which quietly
  dropped stories whenever the model reformatted its answer.
* **The model never supplies a URL.** It is given indices and returns indices;
  links are copied from the fetched articles. A model cannot send a reader to
  a page that does not exist if it is never asked for a link.

Any OpenAI-compatible endpoint works — Groq, OpenAI, Together, OpenRouter, a
local Ollama or vLLM — as does Anthropic's native API.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from ..config import SummarizeConfig, Topic
from ..logs import get_logger
from ..models import Cluster, Story
from .base import story_from_cluster
from .extractive import ExtractiveSummarizer

__all__ = ["LLMSummarizer", "build_prompt", "parse_response"]

log = get_logger(__name__)

_SYSTEM = (
    "You are a news editor writing a daily digest. You are precise, neutral, and "
    "allergic to hype. You never speculate beyond the material you are given."
)

_INSTRUCTIONS = """\
Rewrite each numbered item below as a digest entry.

For every item return:
  "index"    the item's number, unchanged
  "headline" a clear, specific headline, under 95 characters, no outlet name,
             no clickbait, sentence case
  "summary"  two sentences: what happened, then why it matters. Use only facts
             present in the item. If several outlets are listed, write the
             story once, not once per outlet.

Respond with JSON only, in exactly this shape:
{"stories": [{"index": 0, "headline": "...", "summary": "..."}]}

Do not add items, drop items, reorder them, or include any URL."""

_JSON_BLOCK = re.compile(r"\{.*\}", re.S)


def build_prompt(topic: Topic, clusters: list[Cluster]) -> str:
    """Render one topic's clusters into the user message."""
    lines = [f"TOPIC: {topic.name}", ""]

    for index, cluster in enumerate(clusters):
        lead = cluster.lead
        lines.append(f"[{index}] {lead.title}")
        lines.append(f"    Outlet: {lead.source}")
        if cluster.corroboration > 1:
            others = ", ".join(a.source for a in cluster.others)
            lines.append(f"    Also covered by: {others}")
        for article in cluster.members[:3]:
            if article.summary:
                lines.append(f"    - {article.summary[:400]}")
        lines.append("")

    lines.append(_INSTRUCTIONS)
    return "\n".join(lines)


def parse_response(text: str, expected: int) -> dict[int, tuple[str, str]]:
    """Pull ``index -> (headline, summary)`` out of a model response.

    Tolerant on purpose: models wrap JSON in prose or code fences often enough
    that strict parsing would throw away usable answers. Anything unparseable
    or out of range is dropped, and the caller falls back for those indices.
    """
    if not text:
        return {}

    payload: Any = None
    for candidate in (text, _extract_json(text)):
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue

    if payload is None:
        return {}

    items = payload.get("stories") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return {}

    parsed: dict[int, tuple[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= index < expected:
            continue

        headline = str(item.get("headline", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if headline or summary:
            parsed[index] = (headline, summary)

    return parsed


def _extract_json(text: str) -> str:
    """Find the JSON object inside a response that also contains prose."""
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        return fenced.group(1).strip()
    match = _JSON_BLOCK.search(text)
    return match.group(0) if match else ""


class LLMSummarizer:
    """Calls a chat-completions endpoint, falling back cleanly when it cannot."""

    def __init__(self, cfg: SummarizeConfig, session: requests.Session | None = None) -> None:
        self.cfg = cfg
        self.name = f"llm:{cfg.model}"
        self._session = session or requests.Session()
        self._fallback = ExtractiveSummarizer()
        self._degraded = False
        """Set once the endpoint has failed, so one outage does not cost N retries."""

    def write(self, topic: Topic, clusters: list[Cluster]) -> list[Story]:
        """Summarise a topic, falling back per-story on anything the model missed."""
        if not clusters:
            return []

        baseline = self._fallback.write(topic, clusters)
        if self._degraded:
            return baseline

        try:
            response = self._complete(build_prompt(topic, clusters))
        except Exception as exc:  # noqa: BLE001 - a bad endpoint must not end the run
            log.warning("Summarizer failed for '%s' (%s); using extractive text", topic.name, exc)
            self._degraded = True
            return baseline

        written = parse_response(response, len(clusters))
        if not written:
            log.warning("Summarizer returned nothing usable for '%s'", topic.name)
            return baseline

        if len(written) < len(clusters):
            log.debug(
                "Summarizer covered %d/%d stories for '%s'", len(written), len(clusters), topic.name
            )

        stories: list[Story] = []
        for index, cluster in enumerate(clusters):
            headline, summary = written.get(index, ("", ""))
            stories.append(
                story_from_cluster(
                    cluster,
                    headline=headline or baseline[index].headline,
                    summary=summary or baseline[index].summary,
                )
            )
        return stories

    # -- transport -------------------------------------------------------

    def _complete(self, prompt: str) -> str:
        """POST the prompt and return the assistant's text. Retries on 429/5xx."""
        url, headers, payload = (
            self._anthropic_request(prompt)
            if self.cfg.api == "anthropic"
            else self._openai_request(prompt)
        )

        last_error = ""
        for attempt in range(self.cfg.retries + 1):
            response = self._session.post(
                url, headers=headers, json=payload, timeout=self.cfg.timeout_seconds
            )

            if response.status_code == 200:
                return self._extract_text(response.json())

            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code not in (408, 429, 500, 502, 503, 504):
                break

            if attempt < self.cfg.retries:
                # Respect Retry-After when the provider sends one.
                delay = _retry_after(response) or 2.0 * (attempt + 1)
                log.debug("Summarizer retry in %.1fs (%s)", delay, last_error)
                time.sleep(delay)

        raise RuntimeError(last_error or "no response")

    def _openai_request(self, prompt: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        return (
            f"{self.cfg.base_url.rstrip('/')}/chat/completions",
            {
                "Authorization": f"Bearer {self.cfg.api_key}",
                "Content-Type": "application/json",
            },
            {
                "model": self.cfg.model,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
            },
        )

    def _anthropic_request(self, prompt: str) -> tuple[str, dict[str, str], dict[str, Any]]:
        return (
            f"{self.cfg.base_url.rstrip('/')}/messages",
            {
                "x-api-key": self.cfg.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            {
                "model": self.cfg.model,
                "max_tokens": self.cfg.max_tokens,
                "temperature": self.cfg.temperature,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            },
        )

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        """Read the assistant text out of either API's response shape."""
        if "choices" in payload:
            return str(payload["choices"][0]["message"]["content"] or "")

        blocks = payload.get("content", [])
        return "".join(
            str(block.get("text", "")) for block in blocks if block.get("type") == "text"
        )


def _retry_after(response: requests.Response) -> float | None:
    """Seconds to wait, per the ``Retry-After`` header, when present and sane."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), 30.0))
    except ValueError:
        return None
