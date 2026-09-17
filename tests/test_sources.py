"""Providers. Every HTTP call is faked; nothing here touches the network."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
import requests

from signal_agent.config import Feed, FetchConfig, HackerNewsConfig, NewsAPIConfig, Topic
from signal_agent.sources.base import FetchReport, SourceResult, parse_timestamp
from signal_agent.sources.hackernews import fetch_hackernews
from signal_agent.sources.newsapi import fetch_topic
from signal_agent.sources.rss import _strip_html, fetch_feed

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, *, content=b"", json_data=None, status_code=200, headers=None):
        self.content = content
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}
        self.text = content.decode("utf-8", "replace") if content else ""

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """A requests.Session stand-in that replays a scripted response."""

    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.exc:
            raise self.exc
        return self.response

    def close(self):
        pass


@pytest.fixture
def fetch_cfg() -> FetchConfig:
    return FetchConfig(window_hours=36, timeout_seconds=5, max_workers=2)


class TestParseTimestamp:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-09-16T14:30:00Z",
            "2026-09-16T14:30:00+00:00",
            "Wed, 16 Sep 2026 14:30:00 GMT",
        ],
    )
    def test_parses_common_formats(self, value):
        parsed = parse_timestamp(value)
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_parses_struct_time(self):
        value = time.struct_time((2026, 9, 16, 14, 30, 0, 0, 0, 0))
        assert parse_timestamp(value) == datetime(2026, 9, 16, 14, 30, tzinfo=UTC)

    def test_adds_timezone_to_naive_values(self):
        assert parse_timestamp(datetime(2026, 9, 16)).tzinfo is not None

    @pytest.mark.parametrize("value", [None, "", "not a date", object()])
    def test_returns_none_for_junk(self, value):
        assert parse_timestamp(value) is None


def test_strip_html_flattens_markup():
    assert _strip_html("<p>Hello <b>there</b></p>") == "Hello there"


def test_strip_html_removes_scripts():
    assert "alert" not in _strip_html("<script>alert(1)</script>Body")


def test_strip_html_unescapes_entities():
    assert _strip_html("A &amp; B") == "A & B"


class TestRSS:
    def test_parses_a_real_feed(self, fetch_cfg):
        session = FakeSession(FakeResponse(content=(FIXTURES / "sample_feed.xml").read_bytes()))
        feed = Feed(url="https://example.com/feed", name="Example")
        result = fetch_feed(feed, session, fetch_cfg)

        assert result.ok
        # Entries missing a title or a link are dropped.
        assert len(result.articles) == 2

    def test_normalises_urls_and_strips_html(self, fetch_cfg):
        session = FakeSession(FakeResponse(content=(FIXTURES / "sample_feed.xml").read_bytes()))
        feed = Feed(url="https://e.com/f", name="Example")
        article = fetch_feed(feed, session, fetch_cfg).articles[0]

        assert article.url == "https://example.com/nvidia-rubin"
        assert "<b>" not in article.summary
        assert article.published is not None

    def test_applies_the_configured_weight(self, fetch_cfg):
        session = FakeSession(FakeResponse(content=(FIXTURES / "sample_feed.xml").read_bytes()))
        feed = Feed(url="https://e.com/f", name="Example", weight=1.4)
        assert fetch_feed(feed, session, fetch_cfg).articles[0].source_weight == 1.4

    def test_network_failure_is_reported_not_raised(self, fetch_cfg):
        session = FakeSession(exc=requests.ConnectionError("boom"))
        result = fetch_feed(Feed(url="https://e.com/f"), session, fetch_cfg)

        assert not result.ok
        assert "boom" in result.error

    def test_http_error_is_reported(self, fetch_cfg):
        session = FakeSession(FakeResponse(status_code=404))
        assert not fetch_feed(Feed(url="https://e.com/f"), session, fetch_cfg).ok

    def test_malformed_xml_is_reported(self, fetch_cfg):
        session = FakeSession(FakeResponse(content=b"<<<not xml at all"))
        assert not fetch_feed(Feed(url="https://e.com/f"), session, fetch_cfg).ok


class TestNewsAPI:
    def _payload(self):
        return {
            "status": "ok",
            "articles": [
                {
                    "title": "A real story",
                    "url": "https://news.example.com/a",
                    "source": {"name": "Example Wire"},
                    "description": "What happened.",
                    "publishedAt": "2026-09-16T14:30:00Z",
                },
                {
                    "title": "[Removed]",
                    "url": "https://news.example.com/gone",
                    "source": {"name": "Example Wire"},
                },
            ],
        }

    def test_parses_articles_and_skips_tombstones(self, fetch_cfg):
        session = FakeSession(FakeResponse(json_data=self._payload()))
        api = NewsAPIConfig(max_articles=10)
        result = fetch_topic(Topic(name="Tech", slug="tech"), session, api, fetch_cfg)

        assert result.ok
        assert [a.title for a in result.articles] == ["A real story"]

    def test_reports_api_level_errors(self, fetch_cfg):
        # NewsAPI signals a bad key or exhausted quota in the body, not the status.
        payload = {"status": "error", "message": "apiKeyExhausted"}
        session = FakeSession(FakeResponse(json_data=payload, status_code=200))
        result = fetch_topic(Topic(name="T", slug="t"), session, NewsAPIConfig(), fetch_cfg)

        assert not result.ok
        assert "apiKeyExhausted" in result.error

    def test_respects_max_articles(self, fetch_cfg):
        payload = {
            "status": "ok",
            "articles": [
                {"title": f"Story {n}", "url": f"https://e.com/{n}", "source": {"name": "E"}}
                for n in range(10)
            ],
        }
        session = FakeSession(FakeResponse(json_data=payload))
        api = NewsAPIConfig(max_articles=3)
        assert len(fetch_topic(Topic(name="T", slug="t"), session, api, fetch_cfg).articles) == 3


class TestHackerNews:
    def test_parses_hits(self, fetch_cfg):
        payload = {
            "hits": [
                {
                    "title": "Show HN: a thing",
                    "url": "https://example.com/thing",
                    "points": 340,
                    "num_comments": 120,
                    "created_at": "2026-09-16T10:00:00Z",
                    "objectID": "1",
                }
            ]
        }
        session = FakeSession(FakeResponse(json_data=payload))
        result = fetch_hackernews(session, HackerNewsConfig(), fetch_cfg)

        assert result.ok
        assert result.articles[0].source == "Hacker News"
        assert "340 points" in result.articles[0].summary

    def test_falls_back_to_the_discussion_link(self, fetch_cfg):
        payload = {"hits": [{"title": "Ask HN: anything?", "points": 200, "objectID": "42"}]}
        session = FakeSession(FakeResponse(json_data=payload))
        article = fetch_hackernews(session, HackerNewsConfig(), fetch_cfg).articles[0]
        assert "news.ycombinator.com/item?id=42" in article.url

    def test_disabled_returns_empty(self, fetch_cfg):
        result = fetch_hackernews(FakeSession(), HackerNewsConfig(enabled=False), fetch_cfg)
        assert result.ok
        assert result.articles == []

    def test_points_raise_the_weight(self, fetch_cfg):
        payload = {
            "hits": [
                {"title": "Low", "url": "https://e.com/l", "points": 100, "objectID": "1"},
                {"title": "High", "url": "https://e.com/h", "points": 900, "objectID": "2"},
            ]
        }
        session = FakeSession(FakeResponse(json_data=payload))
        low, high = fetch_hackernews(session, HackerNewsConfig(), fetch_cfg).articles
        assert high.source_weight > low.source_weight


class TestFetchReport:
    def test_aggregates_results(self, article_factory):
        report = FetchReport()
        report.add(SourceResult(name="a", articles=[article_factory("One")]))
        report.add(SourceResult(name="b", error="down"))

        assert len(report.articles) == 1
        assert report.ok_count == 1
        assert [r.name for r in report.failures] == ["b"]
