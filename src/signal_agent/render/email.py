"""The HTML email.

Email rendering is its own discipline: no external CSS, no flexbox or grid in
Outlook, and a dark mode that has to be expressed twice — once as a media query
for clients that honour it, and once as a baseline of inline styles for the
many that do not. Everything here is a table for that reason.
"""

from __future__ import annotations

import html
from datetime import datetime

from ..models import Digest, Section, Story
from .util import headline_stat, time_ago

__all__ = ["render_email", "render_plaintext"]

# Light palette. Dark equivalents live in the <style> block below.
_INK = "#0f172a"
_MUTED = "#64748b"
_FAINT = "#94a3b8"
_RULE = "#e2e8f0"
_CARD = "#ffffff"
_PAGE = "#f1f5f9"
_ACCENT = "#2563eb"

# One hue per topic, cycled. Chosen to stay legible on both light and dark cards.
_TOPIC_COLORS = [
    "#2563eb",
    "#0891b2",
    "#059669",
    "#7c3aed",
    "#db2777",
    "#ea580c",
    "#0284c7",
    "#65a30d",
]


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def _color_for(index: int) -> str:
    return _TOPIC_COLORS[index % len(_TOPIC_COLORS)]


def render_email(digest: Digest, *, base_url: str = "") -> str:
    """Render a complete digest as an HTML email document."""
    date_label = (
        digest.generated_at.strftime("%A, %B %-d, %Y")
        if _supports_dash()
        else (digest.generated_at.strftime("%A, %B %d, %Y"))
    )

    sections = "".join(
        _render_section(section, index, digest.generated_at)
        for index, section in enumerate(digest.sections)
        if section.stories
    )

    permalink = ""
    if base_url:
        link = f"{base_url.rstrip('/')}/{digest.date_slug}.html"
        permalink = (
            f'<a href="{_esc(link)}" style="color:{_FAINT};text-decoration:underline;">'
            "Read this edition on the web</a> · "
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{_esc(digest.title)} — {_esc(date_label)}</title>
<style>
  /* Clients that honour prefers-color-scheme get a proper dark theme; the rest
     keep the inline light styles, which are readable on their own. */
  @media (prefers-color-scheme: dark) {{
    .sg-page   {{ background:#0b1120 !important; }}
    .sg-card   {{ background:#111827 !important; border-color:#1f2937 !important; }}
    .sg-ink    {{ color:#e5e7eb !important; }}
    .sg-muted  {{ color:#9ca3af !important; }}
    .sg-faint  {{ color:#6b7280 !important; }}
    .sg-rule   {{ border-color:#1f2937 !important; }}
    .sg-chip   {{ background:#1f2937 !important; color:#cbd5f5 !important; }}
    .sg-foot   {{ background:#0b1120 !important; }}
  }}
  @media only screen and (max-width:620px) {{
    .sg-pad {{ padding-left:20px !important; padding-right:20px !important; }}
    .sg-title {{ font-size:17px !important; }}
  }}
  a {{ text-decoration:none; }}
</style>
</head>
<body class="sg-page" style="margin:0;padding:0;background:{_PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">
  {_esc(headline_stat(digest))}
</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       class="sg-page" style="background:{_PAGE};">
  <tr><td align="center" style="padding:32px 12px;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
           style="max-width:640px;width:100%;">

      <!-- masthead -->
      <tr><td class="sg-pad" style="padding:0 8px 22px 8px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr>
            <td style="font:700 26px/1.1 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                       letter-spacing:-0.6px;color:{_INK};" class="sg-ink">
              {_esc(digest.title)}<span style="color:{_ACCENT};">.</span>
            </td>
            <td align="right"
                style="font:500 13px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                       color:{_MUTED};" class="sg-muted">{_esc(date_label)}</td>
          </tr>
          <tr><td colspan="2"
                  style="padding-top:6px;font:400 13px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                         color:{_FAINT};" class="sg-faint">{_esc(headline_stat(digest))}</td></tr>
        </table>
      </td></tr>

      {sections or _empty_state()}

      <!-- footer -->
      <tr><td class="sg-pad sg-foot" align="center"
              style="padding:28px 8px 8px 8px;
                     font:400 12px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                     color:{_FAINT};" class="sg-faint">
        {permalink}Assembled by
        <a href="https://github.com/sxnmit/signal" style="color:{_FAINT};text-decoration:underline;">Signal</a>
        from {_esc(str(digest.stats.fetched))} articles across your sources.
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""


def _empty_state() -> str:
    return f"""
      <tr><td class="sg-card sg-pad" style="background:{_CARD};border:1px solid {_RULE};
              border-radius:14px;padding:28px;text-align:center;
              font:400 15px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
              color:{_MUTED};">
        Nothing new cleared the bar today.
      </td></tr>"""


def _render_section(section: Section, index: int, now: datetime) -> str:
    color = _color_for(index)
    stories = "".join(_render_story(s, color, now) for s in section.stories)

    return f"""
      <tr><td class="sg-pad" style="padding:14px 8px 10px 8px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
          <td style="font:700 12px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                     letter-spacing:1.1px;text-transform:uppercase;color:{color};
                     border-left:3px solid {color};padding-left:10px;">
            {_esc(section.icon)} {_esc(section.topic)}
          </td>
        </tr></table>
      </td></tr>
      {stories}"""


def _render_story(story: Story, color: str, now: datetime) -> str:
    meta_parts = [_esc(story.source)]
    if stamp := time_ago(story.published, now=now):
        meta_parts.append(_esc(stamp))
    meta = " · ".join(meta_parts)

    badge = ""
    if story.corroboration > 1:
        badge = (
            f'<span class="sg-chip" style="display:inline-block;background:{color}14;'
            f"color:{color};border-radius:999px;padding:2px 8px;margin-left:8px;"
            "font:600 11px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;"
            f'">{story.corroboration} outlets</span>'
        )

    corroboration = ""
    if story.also_covered_by:
        links = " · ".join(
            f'<a href="{_esc(url)}" style="color:{_FAINT};text-decoration:underline;">{_esc(source)}</a>'
            for source, url in story.also_covered_by[:5]
        )
        corroboration = f"""
          <tr><td style="padding-top:10px;
                     font:400 12px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                     color:{_FAINT};" class="sg-faint">Also covered by {links}</td></tr>"""

    return f"""
      <tr><td class="sg-pad" style="padding:0 8px 10px 8px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
               class="sg-card" style="background:{_CARD};border:1px solid {_RULE};border-radius:14px;">
          <tr><td style="padding:18px 20px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr><td class="sg-title sg-ink"
                      style="font:600 18px/1.35 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                             color:{_INK};letter-spacing:-0.2px;">
                <a href="{_esc(story.url)}" style="color:{_INK};" class="sg-ink">{_esc(story.headline)}</a>
              </td></tr>
              <tr><td style="padding-top:6px;
                         font:500 12px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                         color:{_MUTED};" class="sg-muted">{meta}{badge}</td></tr>
              <tr><td style="padding-top:10px;
                         font:400 15px/1.65 -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
                         color:{_INK};" class="sg-ink">{_esc(story.summary)}</td></tr>
              {corroboration}
            </table>
          </td></tr>
        </table>
      </td></tr>"""


def render_plaintext(digest: Digest) -> str:
    """The text/plain alternative.

    Always sent alongside the HTML: it is what screen readers, terminal mail
    clients and spam filters actually read.
    """
    lines = [
        digest.title.upper(),
        digest.generated_at.strftime("%A, %B %d, %Y"),
        headline_stat(digest),
        "",
    ]

    for section in digest.sections:
        if not section.stories:
            continue
        lines.append(f"{section.icon} {section.topic.upper()}")
        lines.append("-" * min(len(section.topic) + 4, 60))

        for story in section.stories:
            lines.append(f"* {story.headline}")
            meta = story.source
            if stamp := time_ago(story.published, now=digest.generated_at):
                meta += f", {stamp}"
            if story.corroboration > 1:
                meta += f" — {story.corroboration} outlets"
            lines.append(f"  {meta}")
            lines.append(f"  {story.summary}")
            lines.append(f"  {story.url}")
            lines.append("")
        lines.append("")

    lines.append("Assembled by Signal — https://github.com/sxnmit/signal")
    return "\n".join(lines)


def _supports_dash() -> bool:
    """Whether ``%-d`` (no zero padding) works on this platform."""
    try:
        datetime(2024, 1, 5).strftime("%-d")
    except ValueError:  # pragma: no cover - Windows
        return False
    return True
