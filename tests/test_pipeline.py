"""Tokenising, deduplication, clustering, routing, and ranking."""

from __future__ import annotations

import pytest

from signal_agent.config import RankConfig, Topic
from signal_agent.models import Cluster
from signal_agent.pipeline.cluster import cluster_articles
from signal_agent.pipeline.dedup import drop_duplicates, within_window
from signal_agent.pipeline.rank import assign_topics, relevance, score_cluster, select
from signal_agent.pipeline.text import (
    capitalized_tokens,
    entity_vocabulary,
    idf_weights,
    keyword_overlap,
    sentences,
    similarity,
    tokenize,
)


class TestTokenize:
    def test_drops_stopwords_and_punctuation(self):
        assert tokenize("The cat, and the DOG!") == ["cat", "dog"]

    def test_folds_possessives(self):
        # Without this, "Nvidia's" and "Nvidia" never match, which hides the
        # single most important token in a story.
        assert tokenize("Nvidia's chip") == tokenize("Nvidia chip")

    def test_keeps_two_letter_news_tokens(self):
        tokens = tokenize("AI and the EU and the UN")
        assert {"ai", "eu", "un"} <= set(tokens)

    def test_keeps_digits(self):
        assert "2026" in tokenize("Outlook for 2026")

    def test_empty(self):
        assert tokenize("") == []


class TestSimilarity:
    def test_identical_sets_score_one(self):
        tokens = tokenize("Nvidia announces new chip")
        assert similarity(tokens, tokens) == pytest.approx(1.0)

    def test_disjoint_sets_score_zero(self):
        assert similarity(tokenize("cats sleep"), tokenize("markets rally")) == 0.0

    def test_empty_is_zero(self):
        assert similarity([], tokenize("anything")) == 0.0

    def test_related_beats_unrelated(self):
        a = tokenize("Nvidia unveils Rubin data center GPU")
        b = tokenize("Nvidia announces Rubin GPU for inference")
        c = tokenize("Canada unveils immigration targets")
        assert similarity(a, b) > similarity(a, c)

    def test_containment_helps_uneven_lengths(self):
        short = tokenize("Nvidia announces Rubin")
        long = tokenize("Nvidia announces Rubin at its annual developer conference in California")
        assert similarity(short, long, containment=1.0) > similarity(short, long, containment=0.0)


class TestEntities:
    def test_capitalized_tokens_skips_first_word(self):
        # The opening capital is grammar, not evidence of a name.
        assert capitalized_tokens("Nvidia ships Rubin") == {"rubin"}

    def test_entity_vocabulary_finds_names(self):
        titles = [
            "Nvidia ships Rubin",
            "Analysts weigh Nvidia's Rubin launch",
            "What Rubin means for inference",
        ]
        assert {"nvidia", "rubin"} <= entity_vocabulary(titles)

    def test_common_words_are_not_entities(self):
        titles = ["Company reports earnings", "Another company reports earnings"]
        assert "company" not in entity_vocabulary(titles)


class TestKeywordOverlap:
    def test_counts_distinct_hits(self):
        hits, strength = keyword_overlap("Nvidia GPU launch", ["nvidia", "gpu", "biology"])
        assert hits == 2
        assert 0 < strength < 1

    def test_matches_multi_word_keywords(self):
        hits, _ = keyword_overlap("A major data breach today", ["data breach"])
        assert hits == 1

    def test_no_keywords(self):
        assert keyword_overlap("anything", []) == (0, 0.0)

    def test_strength_saturates(self):
        _, one = keyword_overlap("nvidia", ["nvidia"])
        _, many = keyword_overlap("nvidia gpu chip silicon", ["nvidia", "gpu", "chip", "silicon"])
        assert many > one
        assert many < 1.0


def test_sentences_splits_on_terminators():
    assert sentences("One thing happened. Then another! Why? Yes.") == [
        "One thing happened.",
        "Then another!",
        "Why?",
        "Yes.",
    ]


def test_idf_weights_favour_rare_tokens():
    docs = [tokenize("common word rare"), tokenize("common word"), tokenize("common word")]
    weights = idf_weights(docs)
    assert weights["rare"] > weights["common"]


class TestDedup:
    def test_collapses_same_url(self, article_factory):
        a = article_factory("One", url="https://x.com/a?utm_source=rss")
        b = article_factory("One", url="https://x.com/a")
        assert len(drop_duplicates([a, b])) == 1

    def test_collapses_identical_text_at_different_urls(self, article_factory):
        # Wire copy: same words, different link.
        a = article_factory("Wire story", url="https://a.com/1", summary="Identical body.")
        b = article_factory("Wire story", url="https://b.com/2", summary="Identical body.")
        assert len(drop_duplicates([a, b])) == 1

    def test_keeps_higher_weighted_copy(self, article_factory):
        weak = article_factory("Wire", url="https://a.com/1", summary="Same.", weight=0.8)
        strong = article_factory("Wire", url="https://b.com/2", summary="Same.", weight=1.4)
        assert drop_duplicates([weak, strong])[0].source_weight == 1.4

    def test_keeps_distinct_articles(self, article_factory):
        assert len(drop_duplicates([article_factory("One"), article_factory("Two")])) == 2

    def test_drops_items_without_url_or_title(self, article_factory):
        assert drop_duplicates([article_factory("Fine"), article_factory("x", url="")]) != []

    def test_empty(self):
        assert drop_duplicates([]) == []


class TestWindow:
    def test_filters_old_articles(self, article_factory):
        kept = within_window(
            [article_factory("New", hours_ago=2), article_factory("Old", hours_ago=100)], 36
        )
        assert [a.title for a in kept] == ["New"]

    def test_keeps_undated_articles(self):
        from signal_agent.models import Article

        undated = Article.create(title="No date", url="https://a.com/x", source="a")
        assert within_window([undated], 36) == [undated]

    def test_zero_disables_filtering(self, article_factory):
        old = article_factory("Old", hours_ago=999)
        assert within_window([old], 0) == [old]


class TestClustering:
    def test_merges_the_same_story_across_outlets(self, article_factory):
        articles = [
            article_factory("Nvidia unveils Rubin data center GPU", source="Ars"),
            article_factory("Nvidia announces Rubin GPU for inference", source="Verge"),
            article_factory("Canada unveils new immigration targets", source="CBC"),
        ]
        clusters = cluster_articles(articles, 0.35)
        sizes = sorted(len(c.members) for c in clusters)
        assert sizes == [1, 2]

    def test_shared_rare_entities_merge_divergent_headlines(self, article_factory):
        # Neither headline shares much vocabulary, but both name Nvidia and Rubin.
        articles = [
            article_factory("Nvidia unveils Rubin data center GPU", source="Ars"),
            article_factory("Rubin: Nvidia bets on serving, not training", source="Stratechery"),
        ]
        assert len(cluster_articles(articles, 0.35)) == 1

    def test_unrelated_stories_stay_apart(self, article_factory):
        articles = [
            article_factory("Central bank holds interest rates steady", source="WSJ"),
            article_factory("Rust stabilises async traits in new release", source="Ars"),
            article_factory("Ransomware group breaches hospital network", source="WIRED"),
        ]
        assert len(cluster_articles(articles, 0.35)) == 3

    def test_lead_is_the_most_representative_headline(self, article_factory):
        articles = [
            article_factory("Nvidia unveils Rubin GPU", source="Ars", weight=1.2),
            article_factory("Nvidia announces Rubin GPU today", source="Verge", weight=1.0),
            article_factory("Rubin: what Nvidia is really betting on", source="Blog", weight=1.4),
        ]
        cluster = cluster_articles(articles, 0.35)[0]
        # The highest-weighted source is the commentary; it must not lead.
        assert cluster.lead.source != "Blog"

    def test_empty_and_single(self, article_factory):
        assert cluster_articles([], 0.35) == []
        assert len(cluster_articles([article_factory("One")], 0.35)) == 1

    def test_clustering_is_transitive(self, article_factory):
        articles = [
            article_factory("Nvidia unveils Rubin data center GPU", source="A"),
            article_factory("Nvidia announces Rubin GPU for inference", source="B"),
            article_factory("Nvidia's Rubin GPU targets inference market", source="C"),
        ]
        assert len(cluster_articles(articles, 0.35)) == 1


@pytest.fixture
def topics() -> list[Topic]:
    return [
        Topic(name="AI", slug="ai", keywords=("ai", "model", "openai"), max_stories=3),
        Topic(name="Markets", slug="markets", keywords=("inflation", "rates"), max_stories=3),
    ]


class TestRouting:
    def test_routes_to_best_topic(self, article_factory, topics):
        cluster = Cluster(members=[article_factory("OpenAI releases a new model")])
        buckets = assign_topics([cluster], topics)
        assert len(buckets["ai"]) == 1
        assert buckets["markets"] == []

    def test_drops_unmatched_clusters(self, article_factory, topics):
        cluster = Cluster(members=[article_factory("Local bakery wins award")])
        buckets = assign_topics([cluster], topics)
        assert all(not v for v in buckets.values())

    def test_each_cluster_lands_in_one_topic_only(self, article_factory, topics):
        cluster = Cluster(members=[article_factory("AI model drives inflation of rates")])
        buckets = assign_topics([cluster], topics)
        assert sum(len(v) for v in buckets.values()) == 1

    def test_relevance_rises_with_corroboration(self, article_factory, topics):
        alone = Cluster(members=[article_factory("OpenAI ships a model", source="A")])
        together = Cluster(
            members=[
                article_factory("OpenAI ships a model", source="A"),
                article_factory("OpenAI model released", source="B"),
            ]
        )
        assert relevance(together, topics[0]) > relevance(alone, topics[0])


class TestRanking:
    def test_corroborated_story_outranks_a_lone_one(self, article_factory):
        cfg = RankConfig()
        lone = Cluster(members=[article_factory("A", hours_ago=1)], score=0.5)
        many = Cluster(
            members=[
                article_factory("A", source="X", hours_ago=1),
                article_factory("A", source="Y", hours_ago=1),
                article_factory("A", source="Z", hours_ago=1),
            ],
            score=0.5,
        )
        assert score_cluster(many, cfg) > score_cluster(lone, cfg)

    def test_recent_beats_stale(self, article_factory):
        cfg = RankConfig()
        fresh = Cluster(members=[article_factory("A", hours_ago=1)], score=0.5)
        stale = Cluster(members=[article_factory("A", hours_ago=48)], score=0.5)
        assert score_cluster(fresh, cfg) > score_cluster(stale, cfg)

    def test_select_respects_per_topic_cap(self, article_factory, topics):
        clusters = [
            Cluster(members=[article_factory(f"OpenAI model number {n}")], score=0.9)
            for n in range(10)
        ]
        selected = select(assign_topics(clusters, topics), topics, RankConfig(min_score=0.0))
        assert len(selected["ai"]) <= 3

    def test_select_drops_low_scores(self, article_factory, topics):
        clusters = [Cluster(members=[article_factory("OpenAI model")], score=0.9)]
        buckets = assign_topics(clusters, topics)
        assert select(buckets, topics, RankConfig(min_score=99.0)) == {}

    def test_global_cap_keeps_the_strongest(self, article_factory, topics):
        clusters = [
            Cluster(members=[article_factory(f"OpenAI model {n}")], score=0.9) for n in range(4)
        ] + [
            Cluster(members=[article_factory(f"inflation and rates {n}")], score=0.9)
            for n in range(4)
        ]
        cfg = RankConfig(min_score=0.0, max_clusters_per_run=2)
        selected = select(assign_topics(clusters, topics), topics, cfg)
        assert sum(len(v) for v in selected.values()) == 2

    def test_empty_selection(self, topics):
        assert select({}, topics, RankConfig()) == {}
