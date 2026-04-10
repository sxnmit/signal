# ============================================================
#  analyzer.py — Uses Groq (free) to filter and summarize news
# ============================================================

from groq import Groq
from config import GROQ_API_KEY

MAX_ARTICLES_PER_TOPIC = 5


def build_article_context(articles: list[dict]) -> str:
    if not articles:
        return "(No articles found from NewsAPI/RSS for this topic.)"
    lines = []
    for i, a in enumerate(articles[:20], 1):
        lines.append(
            f"{i}. [{a['source']}] {a['title']}\n"
            f"   URL: {a['url']}\n"
            f"   {a['summary'][:200]}"
        )
    return "\n\n".join(lines)


def analyze_topic(topic: str, articles: list[dict]) -> dict:
    """
    Ask Groq (Llama 3.3 70B) to filter and summarize
    the pre-fetched articles for a given topic.
    """
    if not GROQ_API_KEY or GROQ_API_KEY.strip() == "":
        print(f"  [Groq] No API key set; skipping summarization for '{topic[:50]}...'")
        return {"topic": topic, "stories": [], "raw": "No API key"}
    client = Groq(api_key=GROQ_API_KEY)
    article_context = build_article_context(articles)

    prompt = f"""You are a research assistant preparing a daily news digest section.

TOPIC: {topic}

PRE-FETCHED ARTICLES (from NewsAPI & RSS, last 24h):
{article_context}

INSTRUCTIONS:
1. Review the articles above and select the {MAX_ARTICLES_PER_TOPIC} most important, distinct stories related to the topic.
2. Return your response in this EXACT format (use --- as separators):

HEADLINE: <concise headline>
SOURCE: <publication name>
URL: <article url>
SUMMARY: <2-3 sentence summary of what happened and why it matters>
---
HEADLINE: ...
(repeat for each story)

Focus on factual reporting. Avoid duplicates. Prioritize recency and significance.
Do not include any text outside of this format."""

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        full_text = response.choices[0].message.content
        stories = parse_stories(full_text)
        return {"topic": topic, "stories": stories, "raw": full_text}

    except Exception as e:
        print(f"  [Groq error for '{topic}']: {e}")
        return {"topic": topic, "stories": [], "raw": str(e)}


def parse_stories(text: str) -> list[dict]:
    """Parse Groq's formatted output into structured story dicts."""
    stories = []
    blocks = [b.strip() for b in text.split("---") if b.strip()]

    for block in blocks:
        story = {"headline": "", "source": "", "url": "", "summary": ""}
        for line in block.splitlines():
            line = line.strip()
            if line.startswith("HEADLINE:"):
                story["headline"] = line[len("HEADLINE:") :].strip()
            elif line.startswith("SOURCE:"):
                story["source"] = line[len("SOURCE:") :].strip()
            elif line.startswith("URL:"):
                story["url"] = line[len("URL:") :].strip()
            elif line.startswith("SUMMARY:"):
                story["summary"] = line[len("SUMMARY:") :].strip()
        if story["headline"]:
            stories.append(story)

    return stories
