# ============================================================
# config.py — Edit this file to customize your news agent
# Keys are read from environment variables; use a .env file (see README).
# ============================================================

import os

from dotenv import load_dotenv
load_dotenv()

# --- Groq (summarization; free tier at https://console.groq.com) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

# --- NewsAPI (free tier at https://newsapi.org) ---
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "").strip()

# --- Email Settings (Gmail SMTP by default) ---
EMAIL_CONFIG = {
    "smtp_host": os.environ.get("SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.environ.get("SMTP_PORT", "587")),
    "sender_email": os.environ.get("SENDER_EMAIL", "").strip(),
    "sender_password": os.environ.get(
        "SENDER_PASSWORD", ""
    ).strip(),  # Gmail App Password
    "recipient_emails": [
        e.strip()
        for e in os.environ.get("RECIPIENT_EMAILS", "").split(",")
        if e.strip()
    ],
}

if not EMAIL_CONFIG["recipient_emails"]:
    EMAIL_CONFIG["recipient_emails"] = []  # e.g. ["you@example.com"]

# --- Schedule ---
# How often to run the scraper and send digest (in hours)
DIGEST_INTERVAL_HOURS = 24  # 1x per day

# --- Tech & CS Topics (used for NewsAPI + RSS + Groq summarization) ---
CLAUDE_SEARCH_TOPICS = [
    "OpenAI, Anthropic, Google DeepMind latest AI research and product news",
    "software engineering tools and developer productivity news",
    "big tech layoffs, hiring trends, and software job market",
    "startups and venture capital funding news Silicon Valley",
    "product management trends and frameworks news",
    "open source software major releases and community news",
    "cloud computing AWS Azure Google Cloud latest developments",
    "programming languages trends news",
    "semiconductor and chip industry news NVIDIA AMD Intel",
    "cybersecurity major breaches vulnerabilities news",
    "developer ecosystem news",
]

# --- World & Geopolitics Topics ---
REGION_TOPICS = [
    "Canada political news and government policy today",
    "US relations trade war and tech decoupling news",
    "European Union politics economy and regulation news",
    "India economy technology and geopolitics news",
    "United Nations and global diplomacy major developments",
    "global economy inflation interest rates and markets news",
]

# --- NewsAPI Keyword Searches ---
NEWSAPI_QUERIES = [
    "artificial intelligence",
    "software engineering",
    "tech layoffs hiring",
    "tech startups",
    "venture capital startup funding",
    "Canada's economy and politics",
    "Global politics",
]
NEWSAPI_LANGUAGE = "en"
NEWSAPI_MAX_ARTICLES = 5  # per query

# --- RSS Feeds ---
RSS_FEEDS = [
    # Tech news
    "https://feeds.feedburner.com/TechCrunch",
    "https://www.wired.com/feed/rss",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.theverge.com/rss/index.xml",
    "https://www.technologyreview.com/feed/",
    # Tech strategy & dev culture
    "https://stratechery.com/feed/",
    "https://hnrss.org/frontpage",
    # World news
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    # Politics & geopolitics
    "https://rss.politico.com/politics-news.xml",
    "https://feeds.foreignaffairs.com/rss/rss.xml",
]
RSS_MAX_ARTICLES_PER_FEED = 3
