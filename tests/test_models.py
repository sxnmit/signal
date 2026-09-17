"""Normalisation, fingerprinting, and the digest data model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from signal_agent.models import (
    Article,
    Cluster,
    Digest,
    RunStats,
    Section,
    Story,
    canonical_url,
    clean_title,
    normalize_text,
    utcnow,
)


class TestCanonicalUrl:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("https://example.com/a", "https://example.com/a"),
            ("http://example.com/a", "https://example.com/a"),
            ("https://WWW.Example.COM/a", "https://example.com/a"),
            ("https://example.com/a/", "https://example.com/a"),
            ("https://example.com/a#section", "https://example.com/a"),
            ("https://example.com/a?utm_source=rss&id=7", "https://example.com/a?id=7"),
            ("https://example.com/a?fbclid=xyz", "https://example.com/a"),
            ("", ""),
        ],
    )
    def test_normalises(self, raw, expected):
        assert canonical_url(raw) == expected

    def test_http_and_https_collapse(self):
        assert canonical_url("http://example.com/x") == canonical_url("https://example.com/x")

    def test_keeps_meaningful_query(self):
        assert canonical_url("https://n.com/p?story=42") == "https://n.com/p?story=42"

    def test_leaves_relative_input_alone(self):
        assert canonical_url("not a url") == "not a url"


class TestCleanTitle:
    def test_strips_outlet_suffix(self):
        assert clean_title("Something important happened today - The Verge") == (
            "Something important happened today"
        )

    def test_keeps_short_titles_intact(self):
        # Trimming would leave too little to be a headline, so it is refused.
        assert clean_title("Nvidia up - Reuters") == "Nvidia up - Reuters"

    def test_collapses_whitespace(self):
        assert clean_title("  a   b\nc  ") == "a b c"


def test_normalize_text():
    assert normalize_text("  Hello   WORLD \n") == "hello world"


class TestArticle:
    def test_create_normalises(self):
        article = Article.create(
            title="A perfectly ordinary headline about things - Ars Technica",
            url="http://WWW.Example.com/story/?utm_source=x",
            source="  Ars  ",
        )
        assert article.url == "https://example.com/story"
        assert article.source == "Ars"
        assert "Ars Technica" not in article.title

    def test_fingerprint_ignores_case_and_spacing(self, article_factory):
        a = article_factory("Rates hold steady", summary="The bank  held.")
        b = article_factory("RATES   HOLD steady", summary="the Bank held.")
        assert a.fingerprint == b.fingerprint

    def test_fingerprint_differs_for_different_stories(self, article_factory):
        assert article_factory("One thing").fingerprint != article_factory("Other").fingerprint

    def test_domain(self, article_factory):
        assert article_factory("x", url="https://news.bbc.co.uk/a").domain == "news.bbc.co.uk"

    def test_age_hours(self, article_factory):
        assert 4.9 < article_factory("x", hours_ago=5).age_hours < 5.1

    def test_age_is_zero_without_timestamp(self):
        assert Article.create(title="x", url="https://a.com/x", source="a").age_hours == 0.0

    def test_articles_are_hashable(self, article_factory):
        assert len({article_factory("x"), article_factory("x")}) == 1


class TestCluster:
    def test_corroboration_counts_distinct_domains(self, article_factory):
        cluster = Cluster(
            members=[
                article_factory("A story", source="BBC"),
                article_factory("A story", source="CNN"),
                article_factory("A story again", source="CNN"),
            ]
        )
        assert cluster.corroboration == 2

    def test_others_excludes_lead_and_deduplicates_outlets(self, article_factory):
        cluster = Cluster(
            members=[
                article_factory("Lead", source="BBC"),
                article_factory("Second", source="CNN"),
                article_factory("Third", source="CNN"),
            ]
        )
        assert [a.source for a in cluster.others] == ["CNN"]

    def test_lead_is_first_member(self, article_factory):
        first = article_factory("First")
        cluster = Cluster(members=[first, article_factory("Second")])
        assert cluster.lead is first


class TestSerialisation:
    def _digest(self) -> Digest:
        story = Story(
            headline="Headline",
            summary="Summary.",
            url="https://example.com/a",
            source="BBC",
            score=1.25,
            published=datetime(2026, 5, 1, 12, tzinfo=UTC),
            corroboration=3,
            also_covered_by=[("CNN", "https://cnn.example.com/a")],
        )
        return Digest(
            generated_at=datetime(2026, 5, 1, 13, tzinfo=UTC),
            sections=[Section(topic="World", slug="world", icon="🌍", stories=[story])],
            stats=RunStats(fetched=100, published=1, summarizer="extractive"),
        )

    def test_round_trip(self):
        original = self._digest()
        restored = Digest.from_dict(original.to_dict())

        assert restored.generated_at == original.generated_at
        assert restored.story_count == 1
        assert restored.sections[0].stories[0].also_covered_by == [
            ("CNN", "https://cnn.example.com/a")
        ]
        assert restored.stats.fetched == 100

    def test_date_slug(self):
        assert self._digest().date_slug == "2026-05-01"

    def test_empty_digest(self):
        digest = Digest(generated_at=utcnow(), sections=[])
        assert digest.is_empty
        assert digest.story_count == 0

    def test_stats_from_dict_ignores_unknown_keys(self):
        stats = RunStats.from_dict({"fetched": 5, "invented_field": 1})
        assert stats.fetched == 5


def test_utcnow_is_aware():
    assert utcnow().tzinfo is not None


def test_age_never_negative(article_factory):
    future = Article.create(
        title="Tomorrow", url="https://a.com/t", source="a", published=utcnow() + timedelta(hours=2)
    )
    assert future.age_hours == 0.0
