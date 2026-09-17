"""Static site generator for the digest archive.

Turns the JSON archive into a browsable, searchable website with no build step,
no framework and no runtime dependencies — just HTML, one stylesheet and a
small script. It is designed to be served straight from GitHub Pages.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from ..logs import get_logger
from ..models import Digest, Section, Story
from .util import headline_stat, plural, time_ago

__all__ = ["build_site"]

log = get_logger(__name__)

_TOPIC_HUES = [217, 190, 160, 265, 330, 25, 200, 90]


def _esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def build_site(
    digests: list[Digest],
    directory: str | Path,
    *,
    title: str = "Signal",
    tagline: str = "",
    base_url: str = "",
) -> Path:
    """Render every edition into ``directory`` and return the path.

    The newest edition becomes the front page; each edition also gets a
    permalink so a link in an email keeps working.
    """
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)

    ordered = sorted(digests, key=lambda d: d.date_slug, reverse=True)

    (root / "style.css").write_text(_STYLESHEET, encoding="utf-8")
    (root / "app.js").write_text(_SCRIPT, encoding="utf-8")
    (root / "search.json").write_text(
        json.dumps(_search_index(ordered), ensure_ascii=False), encoding="utf-8"
    )
    # Tell GitHub Pages not to run the output through Jekyll.
    (root / ".nojekyll").write_text("", encoding="utf-8")

    for digest in ordered:
        (root / f"{digest.date_slug}.html").write_text(
            _edition_page(digest, ordered, title=title, tagline=tagline, base_url=base_url),
            encoding="utf-8",
        )

    if ordered:
        (root / "index.html").write_text(
            _edition_page(
                ordered[0], ordered, title=title, tagline=tagline, base_url=base_url, is_index=True
            ),
            encoding="utf-8",
        )
    else:
        (root / "index.html").write_text(
            _shell(
                title=title,
                tagline=tagline,
                body='<p class="empty">No editions yet. Run <code>signal run</code>.</p>',
                editions=[],
                current="",
            ),
            encoding="utf-8",
        )

    log.info("Built site with %s at %s", plural(len(ordered), "edition"), root)
    return root


def _search_index(digests: list[Digest]) -> list[dict[str, object]]:
    """Flatten every story in the archive into one searchable list."""
    entries: list[dict[str, object]] = []
    for digest in digests:
        for section in digest.sections:
            for story in section.stories:
                entries.append(
                    {
                        "d": digest.date_slug,
                        "t": section.topic,
                        "i": section.icon,
                        "h": story.headline,
                        "s": story.summary,
                        "o": story.source,
                        "u": story.url,
                        "c": story.corroboration,
                    }
                )
    return entries


def _edition_page(
    digest: Digest,
    all_digests: list[Digest],
    *,
    title: str,
    tagline: str,
    base_url: str,
    is_index: bool = False,
) -> str:
    sections = "".join(
        _section_html(section, index, digest)
        for index, section in enumerate(digest.sections)
        if section.stories
    )

    date_label = digest.generated_at.strftime("%A, %B %d, %Y")
    body = f"""
    <header class="edition">
      <h1>{_esc(date_label)}</h1>
      <p class="stat">{_esc(headline_stat(digest))}</p>
    </header>
    {sections or '<p class="empty">Nothing cleared the bar this day.</p>'}
    """

    return _shell(
        title=title,
        tagline=tagline,
        body=body,
        editions=all_digests,
        current=digest.date_slug,
        canonical=f"{base_url.rstrip('/')}/{digest.date_slug}.html" if base_url else "",
        page_title=f"{title} — {date_label}",
        is_index=is_index,
    )


def _section_html(section: Section, index: int, digest: Digest) -> str:
    hue = _TOPIC_HUES[index % len(_TOPIC_HUES)]
    stories = "".join(_story_html(s, digest) for s in section.stories)
    slug = _esc(section.slug)

    return f"""
    <section class="topic" style="--hue:{hue}" id="{slug}">
      <h2><span class="icon">{_esc(section.icon)}</span>{_esc(section.topic)}</h2>
      <div class="stories">{stories}</div>
    </section>"""


def _story_html(story: Story, digest: Digest) -> str:
    stamp = time_ago(story.published, now=digest.generated_at)
    badge = (
        f'<span class="badge" title="Independently covered by '
        f'{story.corroboration} outlets">{story.corroboration} outlets</span>'
        if story.corroboration > 1
        else ""
    )

    also = ""
    if story.also_covered_by:
        links = " · ".join(
            f'<a href="{_esc(url)}" rel="noopener">{_esc(source)}</a>'
            for source, url in story.also_covered_by[:6]
        )
        also = f'<p class="also"><span>Also covered by</span> {links}</p>'

    meta = " · ".join(part for part in (_esc(story.source), _esc(stamp)) if part)

    return f"""
      <article class="story">
        <h3><a href="{_esc(story.url)}" rel="noopener">{_esc(story.headline)}</a></h3>
        <p class="meta">{meta}{badge}</p>
        <p class="summary">{_esc(story.summary)}</p>
        {also}
      </article>"""


def _shell(
    *,
    title: str,
    tagline: str,
    body: str,
    editions: list[Digest],
    current: str,
    canonical: str = "",
    page_title: str = "",
    is_index: bool = False,
) -> str:
    """Wrap page content in the shared chrome."""
    options = "".join(
        f'<option value="{_esc(d.date_slug)}"{" selected" if d.date_slug == current else ""}>'
        f"{_esc(d.generated_at.strftime('%b %d, %Y'))} · {d.story_count}</option>"
        for d in editions
    )

    picker = (
        f'<select id="edition-picker" aria-label="Choose an edition">{options}</select>'
        if editions
        else ""
    )
    canonical_tag = f'<link rel="canonical" href="{_esc(canonical)}">' if canonical else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{_esc(page_title or title)}</title>
<meta name="description" content="{_esc(tagline)}">
{canonical_tag}
<link rel="stylesheet" href="style.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><text y='26' font-size='26'>📡</text></svg>">
</head>
<body{' class="is-index"' if is_index else ""}>
<a class="skip" href="#main">Skip to content</a>
<nav class="topbar">
  <div class="wrap">
    <a class="brand" href="index.html">{_esc(title)}<span>.</span></a>
    <p class="tagline">{_esc(tagline)}</p>
    <div class="controls">
      <label class="search">
        <input id="search" type="search" placeholder="Search every edition…"
               autocomplete="off" aria-label="Search every edition">
      </label>
      {picker}
      <button id="theme" type="button" aria-label="Toggle dark mode" title="Toggle dark mode">
        <svg viewBox="0 0 20 20" width="15" height="15" aria-hidden="true">
          <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" stroke-width="1.6"/>
          <path d="M10 3a7 7 0 0 0 0 14z" fill="currentColor"/>
        </svg>
      </button>
    </div>
  </div>
</nav>
<main id="main" class="wrap">
  <div id="results" hidden></div>
  <div id="edition">{body}</div>
</main>
<footer class="wrap">
  <p>Assembled by <a href="https://github.com/sxnmit/signal" rel="noopener">Signal</a>.
     Stories are grouped by event, so one entry can carry several outlets.</p>
</footer>
<script src="app.js" defer></script>
</body>
</html>"""


_STYLESHEET = """\
/* Signal — archive site. One file, no framework, no build step. */
:root {
  --page: #f6f7f9;
  --card: #ffffff;
  --ink: #0f172a;
  --muted: #5b6577;
  --faint: #8c95a6;
  --rule: #e4e7ec;
  --accent: #2563eb;
  --radius: 14px;
  --shadow: 0 1px 2px rgba(15, 23, 42, .06), 0 8px 24px rgba(15, 23, 42, .04);
}
[data-theme="dark"] {
  --page: #0b1120;
  --card: #111827;
  --ink: #e8ecf4;
  --muted: #9aa5b8;
  --faint: #6b7688;
  --rule: #1e2939;
  --accent: #6ea8fe;
  --shadow: none;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --page: #0b1120; --card: #111827; --ink: #e8ecf4; --muted: #9aa5b8;
    --faint: #6b7688; --rule: #1e2939; --accent: #6ea8fe; --shadow: none;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 400 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Helvetica, Arial, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.wrap { width: 100%; max-width: 760px; margin: 0 auto; padding: 0 16px; }
a { color: inherit; }
.skip {
  position: absolute; left: -9999px; top: 0; background: var(--accent);
  color: #fff; padding: 10px 14px; border-radius: 0 0 8px 0; z-index: 10;
}
.skip:focus { left: 0; }

/* header */
.topbar {
  position: sticky; top: 0; z-index: 5;
  background: color-mix(in srgb, var(--page) 88%, transparent);
  backdrop-filter: saturate(160%) blur(10px);
  border-bottom: 1px solid var(--rule);
  padding: 14px 0;
}
.topbar .wrap { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.brand {
  font-weight: 700; font-size: 20px; letter-spacing: -.5px; text-decoration: none;
}
.brand span { color: var(--accent); }
.tagline { margin: 0; color: var(--faint); font-size: 13px; flex: 1 1 auto; }
.controls { display: flex; align-items: center; gap: 8px; margin-left: auto; }
.search { display: block; }
input[type="search"], select, button#theme {
  font: inherit; font-size: 13px; color: var(--ink);
  background: var(--card); border: 1px solid var(--rule);
  border-radius: 999px; padding: 7px 12px;
}
input[type="search"] { min-width: 190px; }
input[type="search"]:focus-visible, select:focus-visible, button#theme:focus-visible {
  outline: 2px solid var(--accent); outline-offset: 1px;
}
button#theme {
  cursor: pointer; width: 34px; height: 32px; padding: 0;
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--muted);
}
button#theme:hover { color: var(--accent); border-color: var(--accent); }

/* editions */
main { padding: 28px 0 8px; }
.edition h1 { margin: 0; font-size: 28px; letter-spacing: -.7px; line-height: 1.2; }
.edition .stat { margin: 6px 0 0; color: var(--faint); font-size: 14px; }
.topic { margin-top: 34px; }
.topic h2 {
  margin: 0 0 12px; font-size: 12px; font-weight: 700; letter-spacing: 1.1px;
  text-transform: uppercase; color: hsl(var(--hue) 72% 45%);
  border-left: 3px solid hsl(var(--hue) 72% 45%); padding-left: 10px;
  display: flex; align-items: center; gap: 7px;
}
[data-theme="dark"] .topic h2 { color: hsl(var(--hue) 80% 70%); border-color: hsl(var(--hue) 80% 70%); }
.topic h2 .icon { border: 0; }
.stories { display: grid; gap: 10px; }
.story {
  background: var(--card); border: 1px solid var(--rule);
  border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow);
}
.story h3 { margin: 0; font-size: 18px; line-height: 1.35; letter-spacing: -.2px; font-weight: 600; }
.story h3 a { text-decoration: none; }
.story h3 a:hover { color: var(--accent); }
.story .meta {
  margin: 6px 0 0; font-size: 12.5px; color: var(--muted);
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.story .summary { margin: 10px 0 0; }
.badge {
  background: color-mix(in srgb, var(--accent) 14%, transparent);
  color: var(--accent); border-radius: 999px; padding: 2px 9px;
  font-size: 11px; font-weight: 600; letter-spacing: .2px;
}
.also { margin: 10px 0 0; font-size: 12.5px; color: var(--faint); }
.also span { margin-right: 4px; }
.also a { color: var(--faint); text-decoration: underline; text-underline-offset: 2px; }
.also a:hover { color: var(--accent); }
.empty { color: var(--faint); text-align: center; padding: 40px 0; }

/* search */
#results .hit { margin-bottom: 10px; }
#results .hit .date { font-size: 12px; color: var(--faint); }
.results-head { margin: 0 0 14px; font-size: 14px; color: var(--muted); }
mark { background: color-mix(in srgb, var(--accent) 24%, transparent); color: inherit; border-radius: 3px; }

footer { padding: 34px 0 48px; color: var(--faint); font-size: 13px; }
footer a { color: var(--faint); }

@media (max-width: 640px) {
  .topbar .wrap { gap: 8px; }
  .tagline { display: none; }
  .controls { width: 100%; }
  input[type="search"] { flex: 1 1 auto; min-width: 0; }
  .edition h1 { font-size: 23px; }
}
"""

_SCRIPT = """\
// Signal archive: theme toggle, edition picker, and client-side search.
(function () {
  "use strict";

  var root = document.documentElement;
  var STORE = "signal-theme";

  function applyTheme(value) {
    if (value) root.setAttribute("data-theme", value);
    else root.removeAttribute("data-theme");
  }

  try { applyTheme(localStorage.getItem(STORE)); } catch (e) { /* private mode */ }

  var toggle = document.getElementById("theme");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      var current = root.getAttribute("data-theme") || (dark ? "dark" : "light");
      var next = current === "dark" ? "light" : "dark";
      applyTheme(next);
      try { localStorage.setItem(STORE, next); } catch (e) { /* ignore */ }
    });
  }

  var picker = document.getElementById("edition-picker");
  if (picker) {
    picker.addEventListener("change", function () {
      if (picker.value) window.location.href = picker.value + ".html";
    });
  }

  var input = document.getElementById("search");
  var results = document.getElementById("results");
  var edition = document.getElementById("edition");
  if (!input || !results || !edition) return;

  var index = null;
  var pending = null;
  var indexFailed = false;

  function load() {
    if (index) return Promise.resolve(index);
    return fetch("search.json")
      .then(function (r) { return r.json(); })
      .then(function (data) { index = data; return index; })
      .catch(function () {
        // Opening the site straight off disk blocks fetch(), so say that
        // rather than claiming the archive contains nothing.
        indexFailed = true;
        index = [];
        return index;
      });
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function highlight(text, terms) {
    var out = escapeHtml(text);
    terms.forEach(function (term) {
      if (term.length < 2) return;
      var pattern = new RegExp("(" + term.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") + ")", "ig");
      out = out.replace(pattern, "<mark>$1</mark>");
    });
    return out;
  }

  function score(entry, terms) {
    var haystack = (entry.h + " " + entry.s + " " + entry.o + " " + entry.t).toLowerCase();
    var total = 0;
    for (var i = 0; i < terms.length; i++) {
      if (haystack.indexOf(terms[i]) === -1) return 0;       // every term must appear
      total += entry.h.toLowerCase().indexOf(terms[i]) !== -1 ? 3 : 1;
    }
    return total + Math.min(entry.c || 1, 5) * 0.5;          // corroborated stories rank higher
  }

  function render(matches, terms) {
    if (!matches.length) {
      results.innerHTML = indexFailed
        ? '<p class="empty">Search needs the site served over HTTP.<br>' +
          "Try <code>python3 -m http.server</code> in this folder.</p>"
        : '<p class="empty">No stories match that.</p>';
      return;
    }
    var html = '<p class="results-head">' + matches.length +
      (matches.length === 1 ? " story" : " stories") + " found</p>";
    html += '<div class="stories">';
    matches.slice(0, 80).forEach(function (entry) {
      html += '<article class="story hit">' +
        '<h3><a href="' + escapeHtml(entry.u) + '" rel="noopener">' +
          highlight(entry.h, terms) + "</a></h3>" +
        '<p class="meta">' + escapeHtml(entry.o) + " · " +
          '<a class="date" href="' + escapeHtml(entry.d) + '.html">' + escapeHtml(entry.d) + "</a>" +
          (entry.c > 1 ? '<span class="badge">' + entry.c + " outlets</span>" : "") + "</p>" +
        '<p class="summary">' + highlight(entry.s, terms) + "</p></article>";
    });
    results.innerHTML = html + "</div>";
  }

  function run() {
    var query = input.value.trim().toLowerCase();
    if (!query) {
      results.hidden = true;
      results.innerHTML = "";
      edition.hidden = false;
      return;
    }
    var terms = query.split(/\\s+/).filter(Boolean);
    load().then(function (data) {
      var matches = data
        .map(function (entry) { return { entry: entry, score: score(entry, terms) }; })
        .filter(function (row) { return row.score > 0; })
        .sort(function (a, b) { return b.score - a.score || (a.entry.d < b.entry.d ? 1 : -1); })
        .map(function (row) { return row.entry; });
      edition.hidden = true;
      results.hidden = false;
      render(matches, terms);
    });
  }

  input.addEventListener("input", function () {
    window.clearTimeout(pending);
    pending = window.setTimeout(run, 120);
  });
  input.addEventListener("search", run);
  document.addEventListener("keydown", function (event) {
    if (event.key === "/" && document.activeElement !== input) {
      event.preventDefault();
      input.focus();
    } else if (event.key === "Escape" && document.activeElement === input) {
      input.value = "";
      run();
      input.blur();
    }
  });
})();
"""
