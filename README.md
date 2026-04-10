# 📡 Daily News Digest Agent

A background agent that scrapes tech & world news from NewsAPI and RSS feeds, summarizes with Groq (Llama), and emails you an HTML digest on a schedule.

---

## Setup (5 minutes)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get your API keys

| Key | Where to get it | Free tier? |
|-----|----------------|------------|
| `GROQ_API_KEY` | https://console.groq.com | ✅ Yes |
| `NEWS_API_KEY` | https://newsapi.org/register | ✅ Yes (100 req/day) |

### 3. Set up Gmail App Password
1. Enable 2-Factor Authentication on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Create a new App Password (select "Mail" + "Mac/Windows Computer")
4. Copy the 16-character password

### 4. Put your secrets in a `.env` file (never committed)

Keys stay out of the code. Create `.env` from the example and fill in your values:

```bash
cp .env.example .env
```

Edit `.env` and set:

- `GROQ_API_KEY` — from https://console.groq.com
- `NEWS_API_KEY` — from https://newsapi.org/register
- `SENDER_EMAIL` — your Gmail address
- `SENDER_PASSWORD` — Gmail App Password (16 chars from apppasswords)
- `RECIPIENT_EMAILS` — one or more addresses, comma-separated

The app loads `.env` automatically. `.env` is in `.gitignore` so it won’t be committed.

---

## Running

**Test immediately (runs once and exits):**
```bash
python scraper.py --now
```

**Run continuously (sends digest every N hours, see `DIGEST_INTERVAL_HOURS` in config):**
```bash
python scraper.py
```

**Keep it running in the background (Mac/Linux):**
```bash
# Option A: nohup (simple)
nohup python scraper.py &

# Option B: screen (recommended — lets you reattach)
screen -S digest
python scraper.py
# Detach: Ctrl+A then D
# Reattach: screen -r digest
```

**Auto-start on login (Mac — launchd):**

Create `~/Library/LaunchAgents/com.newsdigest.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.newsdigest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/news-digest/scraper.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>/tmp/newsdigest.log</string>
  <key>StandardErrorPath</key><string>/tmp/newsdigest.err</string>
</dict>
</plist>
```
Then: `launchctl load ~/Library/LaunchAgents/com.newsdigest.plist`

---

## Customization

### Add topics (`config.py`)
Edit `CLAUDE_SEARCH_TOPICS` (tech/CS) and `REGION_TOPICS` (world & geopolitics):
```python
CLAUDE_SEARCH_TOPICS = [
    "your tech topic here",
    ...
]
REGION_TOPICS = [
    "your world-news topic here",
    ...
]
```

### Add RSS feeds (`config.py`)
```python
RSS_FEEDS = [
    "https://your-favorite-site.com/rss",
    ...
]
```

### Change digest interval (`config.py`)
```python
DIGEST_INTERVAL_HOURS = 24  # digest once a day
```

---

## Files

| File | Purpose |
|------|---------|
| `config.py` | All settings — edit this |
| `scraper.py` | Main runner & scheduler |
| `sources.py` | NewsAPI + RSS fetching |
| `analyzer.py` | Groq (Llama) summarization & filtering |
| `emailer.py` | HTML email builder & sender |
