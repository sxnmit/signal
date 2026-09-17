"""Command line interface.

``signal <command>``. Every command takes ``--config``, ``-v`` and ``-q``;
each one does a single, nameable thing, and the ones that change something
outside the process say so before they do it.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__
from .archive import Archive
from .config import Config, ConfigError
from .env import load_dotenv
from .logs import get_logger, setup_logging
from .models import Digest
from .render import render_email, render_markdown, render_terminal
from .render.site import build_site
from .runner import RunOutcome
from .runner import run as run_pipeline
from .sample_data import sample_articles
from .store import Store

__all__ = ["main"]

log = get_logger(__name__)

_ENV_EXAMPLE = """\
# Signal — secrets. Copy to .env and fill in. Never commit the filled-in copy.

# Summarizer. Without one, Signal uses its offline extractive summarizer.
# Any OpenAI-compatible endpoint works; set base_url in signal.toml to match.
GROQ_API_KEY=

# Optional: adds keyword search on top of your RSS feeds.
NEWS_API_KEY=

# Email delivery. For Gmail this must be an App Password, not your password:
# https://myaccount.google.com/apppasswords
SENDER_EMAIL=
SENDER_PASSWORD=
RECIPIENT_EMAILS=you@example.com

# Optional: post the digest to Slack or Discord as well.
# SIGNAL_WEBHOOK_URL=
"""


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    setup_logging(verbosity=args.verbose, quiet=args.quiet)
    load_dotenv(args.env_file)

    try:
        return int(args.handler(args))
    except ConfigError as exc:
        log.error("Configuration error: %s", exc)
        return 2
    except KeyboardInterrupt:
        print()
        log.warning("Interrupted")
        return 130


# ---------------------------------------------------------------------------
#  commands
# ---------------------------------------------------------------------------


def cmd_run(args: argparse.Namespace) -> int:
    """Assemble and deliver one edition."""
    config = _load_config(args)
    outcome = run_pipeline(config, dry_run=args.dry_run, deliver=not args.no_send)
    digest = outcome.digest

    if args.print or args.dry_run:
        print(render_terminal(digest))

    if digest.is_empty:
        log.info("No new stories cleared the bar this run")
        return 0

    _report(outcome, dry_run=args.dry_run)

    if config.site.enabled and not args.dry_run and args.build_site:
        _build(config)

    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run the whole pipeline on bundled sample articles, touching nothing."""
    config = _load_config(args)
    # An in-memory store and no delivery: demo reads nothing and writes nothing.
    outcome = run_pipeline(
        config,
        dry_run=True,
        deliver=False,
        articles=sample_articles(),
        store=Store(":memory:"),
    )

    if args.format == "html":
        path = Path(args.output or "signal-demo.html")
        path.write_text(render_email(outcome.digest), encoding="utf-8")
        print(f"Wrote {path}")
    elif args.format == "markdown":
        print(render_markdown(outcome.digest))
    else:
        print(render_terminal(outcome.digest))

    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    """Show an archived edition without re-running anything."""
    config = _load_config(args)
    digest = _resolve_edition(config, args.date)
    if digest is None:
        return 1

    if args.format == "markdown":
        print(render_markdown(digest))
    elif args.format == "html":
        path = Path(args.output or f"{digest.date_slug}.html")
        path.write_text(render_email(digest, base_url=config.site.base_url), encoding="utf-8")
        print(f"Wrote {path}")
    else:
        print(render_terminal(digest))

    return 0


def cmd_site(args: argparse.Namespace) -> int:
    """Rebuild the static archive site."""
    config = _load_config(args)
    _build(config, limit=args.limit)
    return 0


def cmd_sources(args: argparse.Namespace) -> int:
    """Check every configured source and report what is reachable."""
    from .sources.registry import probe

    config = _load_config(args)
    print(f"Checking {len(config.feeds)} feed(s)…\n")

    results = probe(config)
    width = max((len(r.name) for r in results), default=10)
    healthy = 0

    for result in sorted(results, key=lambda r: (r.ok, -len(r.articles))):
        if result.ok:
            healthy += 1
            print(
                f"  ok    {result.name:<{width}}  "
                f"{len(result.articles):>3} items  {result.elapsed:.1f}s"
            )
        else:
            print(f"  FAIL  {result.name:<{width}}  {result.error}")

    print(f"\n{healthy}/{len(results)} source(s) healthy.")

    if not config.newsapi.configured and config.newsapi.enabled:
        print(f"  note  NewsAPI disabled — {config.newsapi.api_key_env} is not set.")
    print(f"  note  Summarizer: {config.summarize.resolved_provider()}")

    return 0 if healthy else 1


def cmd_stats(args: argparse.Namespace) -> int:
    """Show what the database and archive contain."""
    config = _load_config(args)
    store = Store(config.store.path)
    archive = Archive(config.archive.directory)

    stats = store.stats()
    dates = archive.dates()

    print(f"\n  Database   {config.store.path}")
    print(f"  Size       {stats.size_bytes / 1_048_576:.2f} MB")
    print(f"  Articles   {stats.articles:,} seen, {stats.sent:,} delivered")
    if stats.first_seen:
        print(f"  Range      {stats.first_seen[:10]} → {(stats.last_seen or '')[:10]}")
    print(f"  Editions   {stats.digests:,} recorded, {stats.stories_published:,} stories")
    print(f"  Archive    {len(dates)} file(s) in {config.archive.directory}")

    if stats.top_sources:
        print("\n  Most frequent sources")
        width = max(len(name) for name, _ in stats.top_sources)
        for name, count in stats.top_sources:
            print(f"    {name:<{width}}  {count:>5,}")

    recent = store.recent_digests(limit=args.limit)
    if recent:
        print("\n  Recent editions")
        for row in recent:
            print(
                f"    {row['date']}  {row['story_count']:>3} stories  "
                f"{row['section_count']:>2} topics  {row['duration_seconds']:>5.1f}s  "
                f"{row['summarizer']}"
            )

    print()
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Write a starter signal.toml and .env.example."""
    config_path = Path(args.path or "signal.toml")
    env_path = Path(".env.example")

    if config_path.exists() and not args.force:
        log.error("%s already exists — pass --force to overwrite", config_path)
        return 1

    config_path.write_text(Config.packaged_defaults(), encoding="utf-8")
    print(f"Wrote {config_path}")

    if not env_path.exists() or args.force:
        env_path.write_text(_ENV_EXAMPLE, encoding="utf-8")
        print(f"Wrote {env_path}")

    print("\nNext:")
    print("  1. signal demo            # see the output, no keys needed")
    print("  2. cp .env.example .env   # add keys when you want email or an LLM")
    print("  3. signal run --dry-run   # a real fetch, delivering nothing")
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Run on an interval, in the foreground.

    Deliberately minimal: cron and GitHub Actions are better schedulers than
    anything a long-lived Python process can offer. This exists for a laptop.
    """
    config = _load_config(args)
    interval = max(args.hours, 0.1) * 3600

    log.info("Watching. Next edition every %.1f hour(s). Ctrl-C to stop.", args.hours)
    while True:
        try:
            outcome = run_pipeline(config, deliver=not args.no_send)
            _report(outcome, dry_run=False)
            if config.site.enabled and args.build_site:
                _build(config)
        except Exception:
            # A single bad run must not end the watch loop.
            log.exception("Run failed; continuing")

        time.sleep(interval)


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------


def _load_config(args: argparse.Namespace) -> Config:
    config = Config.load(args.config)
    if config.source_path:
        log.debug("Config: %s", config.source_path)
    else:
        log.debug("Config: built-in defaults (no signal.toml found)")
    return config


def _resolve_edition(config: Config, date: str | None) -> Digest | None:
    archive = Archive(config.archive.directory)
    digest = archive.read(date) if date else archive.latest()

    if digest is None:
        if date:
            log.error("No archived edition for %s", date)
        else:
            log.error("No archived editions in %s — run `signal run` first", archive.directory)
    return digest


def _build(config: Config, limit: int | None = None) -> None:
    archive = Archive(config.archive.directory)
    digests = archive.load_all(limit=limit)
    path = build_site(
        digests,
        config.site.directory,
        title=config.title,
        tagline=config.tagline,
        base_url=config.site.base_url,
    )
    print(f"Site written to {path}/")


def _report(outcome: RunOutcome, *, dry_run: bool) -> None:
    """Print the one-line summary that closes a run."""
    digest = outcome.digest
    stats = digest.stats

    verb = "would publish" if dry_run else "published"
    parts = [
        f"{verb} {stats.published} story group(s) across {len(digest.sections)} topic(s)",
        f"from {stats.fetched} article(s)",
        f"in {stats.duration_seconds:.1f}s",
    ]
    log.info("Done — %s.", ", ".join(parts))

    if not dry_run and outcome.delivered:
        log.info("Delivered to %d destination(s)", outcome.delivered)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="signal",
        description="Signal — one digest a day, with the same story from every outlet merged.",
        epilog="Start with `signal demo` — it needs no API keys and touches nothing.",
    )
    parser.add_argument("--version", action="version", version=f"signal {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-c", "--config", metavar="PATH", help="path to signal.toml (default: search)"
    )
    common.add_argument(
        "--env-file", metavar="PATH", default=".env", help="path to .env (default: .env)"
    )
    common.add_argument("-v", "--verbose", action="count", default=0, help="more logging")
    common.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    run_parser = subparsers.add_parser(
        "run", parents=[common], help="assemble and deliver one edition"
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="fetch and build, but change nothing"
    )
    run_parser.add_argument(
        "--no-send", action="store_true", help="archive the edition but do not deliver it"
    )
    run_parser.add_argument("--print", action="store_true", help="also print the edition")
    run_parser.add_argument(
        "--no-site", dest="build_site", action="store_false", help="skip rebuilding the site"
    )
    run_parser.set_defaults(handler=cmd_run, build_site=True)

    demo_parser = subparsers.add_parser(
        "demo", parents=[common], help="run on bundled sample data — no keys, no network"
    )
    demo_parser.add_argument(
        "-f", "--format", choices=("terminal", "markdown", "html"), default="terminal"
    )
    demo_parser.add_argument("-o", "--output", metavar="PATH", help="output file for --format html")
    demo_parser.set_defaults(handler=cmd_demo)

    preview_parser = subparsers.add_parser(
        "preview", parents=[common], help="show an archived edition"
    )
    preview_parser.add_argument("date", nargs="?", help="YYYY-MM-DD (default: most recent)")
    preview_parser.add_argument(
        "-f", "--format", choices=("terminal", "markdown", "html"), default="terminal"
    )
    preview_parser.add_argument("-o", "--output", metavar="PATH")
    preview_parser.set_defaults(handler=cmd_preview)

    site_parser = subparsers.add_parser(
        "site", parents=[common], help="rebuild the static archive site"
    )
    site_parser.add_argument(
        "--limit", type=int, metavar="N", help="only include the N most recent editions"
    )
    site_parser.set_defaults(handler=cmd_site)

    sources_parser = subparsers.add_parser(
        "sources", parents=[common], help="check that every source is reachable"
    )
    sources_parser.set_defaults(handler=cmd_sources)

    stats_parser = subparsers.add_parser(
        "stats", parents=[common], help="show database and archive statistics"
    )
    stats_parser.add_argument("--limit", type=int, default=7, metavar="N")
    stats_parser.set_defaults(handler=cmd_stats)

    init_parser = subparsers.add_parser(
        "init", parents=[common], help="write a starter signal.toml"
    )
    init_parser.add_argument("path", nargs="?", help="where to write it (default: signal.toml)")
    init_parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    init_parser.set_defaults(handler=cmd_init)

    watch_parser = subparsers.add_parser(
        "watch", parents=[common], help="run on an interval in the foreground"
    )
    watch_parser.add_argument(
        "--hours", type=float, default=24.0, metavar="N", help="interval (default: 24)"
    )
    watch_parser.add_argument("--no-send", action="store_true")
    watch_parser.add_argument("--no-site", dest="build_site", action="store_false")
    watch_parser.set_defaults(handler=cmd_watch, build_site=True)

    return parser


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
