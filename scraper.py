"""Backward-compatible entrypoint.

Use `python main.py` for the canonical pipeline runner.
"""

import sys
import schedule
import time
from datetime import datetime
from main import main

from config import (
    CLAUDE_SEARCH_TOPICS,
    REGION_TOPICS,
    DIGEST_INTERVAL_HOURS,
)
from sources import collect_raw_articles
from analyzer import analyze_topic
from emailer import send_digest

GROQ_DELAY_SECONDS = 1.5  # between topic calls to reduce rate-limit risk


def run_digest():
    print(f"\n{'='*55}")
    print(f"  News Digest Agent starting — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    digest_sections = []

    for topic in CLAUDE_SEARCH_TOPICS + REGION_TOPICS:
        print(f"🔍 Processing: {topic}")

        try:
            # 1. Collect from NewsAPI + RSS
            print("   Fetching from NewsAPI & RSS...")
            articles = collect_raw_articles(topic)
            print(f"   Found {len(articles)} raw articles")

            # 2. Groq filters & summarizes
            print("   Asking Groq to filter & summarize...")
            section = analyze_topic(topic, articles)
            print(f"   Got {len(section['stories'])} stories")

            if section.get("stories"):
                digest_sections.append(section)
            else:
                print("   Skipping topic (no stories) — won't appear in email")
        except Exception as e:
            print(f"   ❌ Topic failed: {e}")
            # Don't add failed topics — they won't appear in the email

        time.sleep(GROQ_DELAY_SECONDS)

    # 3. Send email (only if we have at least one topic with stories)
    print("\n📧 Sending email digest...")
    if not digest_sections:
        print("  No topics had stories this run — skipping email.")
    else:
        send_digest(digest_sections)

    print(f"\nDone. Next digest in {DIGEST_INTERVAL_HOURS} hour(s).\n")


def main():
    # --now flag: run immediately and exit
    if "--now" in sys.argv:
        run_digest()
        return

    print(f"📡 News Digest Agent running. Digest sent every {DIGEST_INTERVAL_HOURS} hour(s).")
    print("   Press Ctrl+C to stop.\n")

    schedule.every(DIGEST_INTERVAL_HOURS).hours.do(run_digest)

    # Run immediately on startup so you don't wait till tomorrow
    run_digest()

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
