# Changelog

## 2.0.0

A rewrite. The idea is the same — read the news so you do not have to — but v1 was a handful of
flat scripts that emailed a list of links, and this is a package that groups articles by event,
ranks them, and can deliver the result five different ways.

Your secrets do not change and your database is migrated in place.

### Added

- **Story clustering.** Articles covering the same event are merged into one entry carrying every
  outlet that ran it. Headlines are compared with an IDF-weighted blend of cosine similarity and
  containment, blocked on rare tokens to keep the cost near-linear, and reinforced by a named-entity
  vocabulary derived across the corpus — which is what catches an analysis piece whose headline
  shares no vocabulary with the report it responds to.
- **Ranking before summarising.** Clusters score on topic relevance × recency decay × corroboration
  × source weight, and only what clears the bar reaches the summariser.
- **Works with no API keys at all.** RSS and Hacker News for sources, an extractive summariser for
  the writing. `signal demo` runs the whole pipeline over a bundled corpus with no network.
- **Provider-agnostic summarising.** Any OpenAI-compatible endpoint (Groq, OpenAI, OpenRouter,
  Together, Ollama, vLLM) or Anthropic's native API, selected in config.
- **A static archive site.** `signal site` renders every edition into a searchable website with
  dark mode and per-day permalinks, deployed to GitHub Pages by the bundled workflow.
- **A real CLI**: `run`, `demo`, `preview`, `site`, `sources`, `stats`, `init`, `watch`, with
  `--dry-run` that genuinely writes nothing.
- **More output formats**: HTML email with dark-mode support, plain text, terminal, Markdown, JSON.
- **Webhook delivery** to Slack and Discord.
- **`signal.toml` configuration** with packaged defaults, deep merging, and environment overrides,
  so topics and feeds no longer require editing Python.
- **268 tests**, none of which touch the network, plus lint, format and type checking in CI.

### Fixed

- **Articles were buried before they were ever published.** v1 wrote every fetched article to the
  database immediately, and treated presence in that table as "already sent". Anything the
  summariser did not select was therefore never reconsidered. Sending is now what marks a story as
  spent, so one that misses today's cut stays eligible tomorrow.
- **Every recipient could see every other recipient.** v1 put the whole list in one `To:` header.
  Each address now gets its own message by default.
- **Summarizer output was parsed by hand.** v1 asked for a bespoke `HEADLINE:`/`---` format and
  dropped stories whenever the model reformatted its answer. The model now returns JSON keyed by
  index, is never asked for a URL, and unparseable items fall back per story instead of losing the
  topic.
- **Feeds were fetched once per topic.** 16 topics × 16 feeds meant 256 downloads for 16 feeds'
  worth of news. Feeds are now fetched once per run, in parallel.
- **`scraper.py` shadowed the real pipeline.** It was a stale copy of `main.py` with its own
  `run_digest`, missing deduplication and persistence entirely — and the README told you to run it.
- Deprecated `datetime.utcnow()` replaced with timezone-aware timestamps throughout.
- Tracking parameters (`utm_*`, `fbclid`, …), `www.`, trailing slashes and `http` vs `https` are now
  normalised away before deduplication, so the same article from two feeds is one article.
- Outlet names appended to feed headlines (`" — The Verge"`) are stripped before comparison.
- Possessives are folded when tokenising: `Nvidia's` and `Nvidia` were previously different tokens,
  which hid the most important word in a story.
- A failing feed no longer risks the run; failures are collected and reported.
- Fixed a typo in the shipped topic list (`internaitonal`).

### Changed

- **The database is no longer committed.** v1 pushed a 3 MB SQLite file on every run — this
  repository's history is fifty consecutive `Update news database` commits. The archive
  (`archive/YYYY-MM-DD.json`, a few KB of diffable text) is now the durable record of what has been
  sent, and the database is a rebuildable cache that CI never needs to persist. `already_sent` reads
  from both, so a lost database costs nothing.
- **Schema v2**, migrated automatically from v1 with send history preserved. `sent_articles` is
  folded into an `articles.sent_at` column; a `digests` table records run history for `signal stats`.
- **Old rows are pruned** after `dedup.retention_days` (90 by default) and the file is vacuumed, so
  the database cannot grow without bound.
- **Topics were reorganised** from sixteen prose search strings into thirteen topics with explicit
  keyword vocabularies, which is what makes routing and relevance scoring possible.
- Dependencies dropped from six to two (`feedparser`, `requests`). The `groq` and `anthropic` SDKs
  are gone in favour of plain HTTP; `python-dotenv` and `schedule` are replaced by ~30 lines each.
- Package renamed to `signal_agent` — a top-level `signal` package would shadow the standard
  library module of that name.

### Migrating

| v1 | v2 |
|---|---|
| `python main.py --now` | `signal run` |
| `python scraper.py` | `signal watch` |
| editing `config.py` | `signal init`, then edit `signal.toml` |
| `news_digest.db` in git | `archive/*.json` in git |

Secrets keep their names, so repository secrets and any existing `.env` continue to work unchanged.
The first run after upgrading may repeat a story or two from the previous day, because send history
now lives in the archive and the archive starts empty.

## 1.0.0

Initial version: NewsAPI and RSS fetching, Groq summarisation, HTML email digest, scheduled through
GitHub Actions.
