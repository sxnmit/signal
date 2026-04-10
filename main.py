"""Main orchestration for fetch -> deduplicate -> summarize -> email pipeline."""

from __future__ import annotations

import sys
import time
from datetime import datetime

import schedule

from analyzer import analyze_topic
from config import CLAUDE_SEARCH_TOPICS, DIGEST_INTERVAL_HOURS, REGION_TOPICS
from db import article_exists, init_db, insert_article, mark_as_sent
from dedup import compute_content_hash
from emailer import send_digest
from sources import collect_raw_articles

GROQ_DELAY_SECONDS = 1.5


def prepare_new_articles(raw_articles: list[dict]) -> tuple[list[dict], dict[str, int]]:
    """Filter duplicate items and persist only unseen articles.

    Returns articles safe to summarize and a URL -> article_id map.
    """
    new_articles: list[dict] = []
    article_ids_by_url: dict[str, int] = {}

    for article in raw_articles:
        url = (article.get("url") or "").strip()
        if not url:
            continue

        content_hash = compute_content_hash(article.get("title", ""), article.get("summary", ""))
        if article_exists(url=url, content_hash=content_hash):
            continue

        candidate = {**article, "content_hash": content_hash}
        article_id = insert_article(candidate)
        if article_id is None:
            continue

        new_articles.append(article)
        article_ids_by_url[url] = article_id

    return new_articles, article_ids_by_url


def run_digest() -> None:
    """Execute one digest cycle."""
    init_db()

    print(f"\n{'='*55}")
    print(f"  News Digest Agent starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    digest_sections: list[dict] = []
    sent_article_ids: set[int] = set()

    for topic in CLAUDE_SEARCH_TOPICS + REGION_TOPICS:
        print(f"🔍 Processing: {topic}")

        try:
            print("   Fetching from NewsAPI & RSS...")
            raw_articles = collect_raw_articles(topic)
            print(f"   Found {len(raw_articles)} raw articles")

            fresh_articles, article_ids_by_url = prepare_new_articles(raw_articles)
            print(f"   {len(fresh_articles)} new article(s) after dedup")

            if not fresh_articles:
                print("   Skipping topic (all duplicates)")
                continue

            print("   Asking Groq to filter & summarize...")
            section = analyze_topic(topic, fresh_articles)
            print(f"   Got {len(section['stories'])} stories")

            if section.get("stories"):
                digest_sections.append(section)
                for story in section["stories"]:
                    story_url = (story.get("url") or "").strip()
                    article_id = article_ids_by_url.get(story_url)
                    if article_id is not None:
                        sent_article_ids.add(article_id)
            else:
                print("   Skipping topic (no stories)")
        except Exception as exc:
            print(f"   ❌ Topic failed: {exc}")

        time.sleep(GROQ_DELAY_SECONDS)

    print("\n📧 Sending email digest...")
    if not digest_sections:
        print("  No topics had new stories this run — skipping email.")
        return

    if send_digest(digest_sections):
        for article_id in sent_article_ids:
            mark_as_sent(article_id)
        print(f"  Marked {len(sent_article_ids)} article(s) as sent.")

    print(f"\nDone. Next digest in {DIGEST_INTERVAL_HOURS} hour(s).\n")


def main() -> None:
    """Run once with --now or continuously on a schedule."""
    if "--now" in sys.argv:
        run_digest()
        return

    print(f"📡 News Digest Agent running. Digest sent every {DIGEST_INTERVAL_HOURS} hour(s).")
    print("   Press Ctrl+C to stop.\n")

    schedule.every(DIGEST_INTERVAL_HOURS).hours.do(run_digest)
    run_digest()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()