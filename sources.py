# ============================================================
#  sources.py — Fetches articles from NewsAPI and RSS feeds
# ============================================================

import feedparser
import requests
from datetime import datetime, timedelta
from config import (
    NEWS_API_KEY,
    NEWSAPI_LANGUAGE,
    NEWSAPI_MAX_ARTICLES,
    RSS_FEEDS,
    RSS_MAX_ARTICLES_PER_FEED,
)


def fetch_newsapi(topic: str) -> list[dict]:
    """Pull articles from NewsAPI for a given topic (last 24 hours)."""
    if not NEWS_API_KEY or NEWS_API_KEY == "YOUR_NEWSAPI_KEY":
        return []

    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": topic,
        "from": yesterday,
        "sortBy": "publishedAt",
        "language": NEWSAPI_LANGUAGE,
        "pageSize": min(NEWSAPI_MAX_ARTICLES, 100),
        "apiKey": NEWS_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "title": a.get("title", ""),
                "url": a.get("url", ""),
                "source": a.get("source", {}).get("name", "NewsAPI"),
                "published": a.get("publishedAt", ""),
                "summary": a.get("description", "") or "",
            }
            for a in articles
            if a.get("title") and "[Removed]" not in a.get("title", "")
        ]
    except Exception as e:
        print(f"  [NewsAPI error for '{topic}']: {e}")
        return []


def fetch_rss(topic: str) -> list[dict]:
    """Scan all RSS feeds and return entries whose title/summary mention the topic."""
    keywords = [w.lower() for w in topic.split() if len(w) > 3]
    results = []

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            count = 0
            for entry in feed.entries:
                if count >= RSS_MAX_ARTICLES_PER_FEED:
                    break
                title   = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                text    = (title + " " + summary).lower()

                if any(kw in text for kw in keywords):
                    results.append({
                        "title":     title,
                        "url":       entry.get("link", ""),
                        "source":    feed.feed.get("title", feed_url),
                        "published": entry.get("published", ""),
                        "summary":   summary[:400],
                    })
                    count += 1
        except Exception as e:
            print(f"  [RSS error {feed_url}]: {e}")

    return results


def collect_raw_articles(topic: str) -> list[dict]:
    """Merge NewsAPI + RSS results, deduplicate by URL."""
    articles = fetch_newsapi(topic) + fetch_rss(topic)
    seen, unique = set(), []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique
