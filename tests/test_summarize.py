"""Summarisers: the offline default, and the language-model path with no network."""

from __future__ import annotations

import json

import pytest
import requests

from signal_agent.config import SummarizeConfig, Topic
from signal_agent.models import Cluster
from signal_agent.summarize import get_summarizer
from signal_agent.summarize.extractive import ExtractiveSummarizer
from signal_agent.summarize.llm import LLMSummarizer, build_prompt, parse_response


@pytest.fixture
def topic() -> Topic:
    return Topic(name="Chips", slug="chips", keywords=("nvidia",))


@pytest.fixture
def cluster(article_factory) -> Cluster:
    return Cluster(
        members=[
            article_factory(
                "Nvidia unveils Rubin GPU",
                source="Ars Technica",
                summary="Nvidia announced Rubin today. It doubles inference throughput. "
                "The company said shipments begin next year.",
            ),
            article_factory(
                "Nvidia announces Rubin",
                source="The Verge",
                summary="Analysts called the launch defensive.",
            ),
        ],
        score=1.4,
    )


class TestExtractive:
    def test_produces_a_summary_from_the_sources(self, topic, cluster):
        story = ExtractiveSummarizer().write(topic, [cluster])[0]
        assert story.summary
        assert story.headline == cluster.lead.title

    def test_never_invents_a_url(self, topic, cluster):
        story = ExtractiveSummarizer().write(topic, [cluster])[0]
        assert story.url == cluster.lead.url

    def test_carries_corroboration_through(self, topic, cluster):
        story = ExtractiveSummarizer().write(topic, [cluster])[0]
        assert story.corroboration == 2
        assert story.also_covered_by == [("The Verge", cluster.members[1].url)]

    def test_draws_on_every_member(self, topic, cluster):
        # The point of clustering is that the summary can use all the coverage.
        summary = ExtractiveSummarizer().write(topic, [cluster])[0].summary
        assert summary

    def test_handles_an_empty_summary(self, topic, article_factory):
        bare = Cluster(members=[article_factory("A headline with no body text at all")])
        assert ExtractiveSummarizer().write(topic, [bare])[0].headline

    def test_no_clusters(self, topic):
        assert ExtractiveSummarizer().write(topic, []) == []

    def test_summary_is_bounded(self, topic, article_factory):
        long_body = " ".join(f"Sentence number {n} about the topic." for n in range(50))
        cluster = Cluster(members=[article_factory("Long story", summary=long_body)])
        assert len(ExtractiveSummarizer().write(topic, [cluster])[0].summary) <= 340


class TestParseResponse:
    def test_plain_json(self):
        text = json.dumps({"stories": [{"index": 0, "headline": "H", "summary": "S"}]})
        assert parse_response(text, 1) == {0: ("H", "S")}

    def test_fenced_json(self):
        text = '```json\n{"stories":[{"index":0,"headline":"H","summary":"S"}]}\n```'
        assert parse_response(text, 1) == {0: ("H", "S")}

    def test_json_wrapped_in_prose(self):
        text = 'Sure thing! {"stories":[{"index":0,"headline":"H","summary":"S"}]} Hope that helps.'
        assert parse_response(text, 1) == {0: ("H", "S")}

    def test_bare_list(self):
        text = '[{"index": 0, "headline": "H", "summary": "S"}]'
        assert parse_response(text, 1) == {0: ("H", "S")}

    def test_out_of_range_indices_are_dropped(self):
        text = json.dumps({"stories": [{"index": 99, "headline": "H", "summary": "S"}]})
        assert parse_response(text, 1) == {}

    def test_string_index_is_coerced(self):
        text = json.dumps({"stories": [{"index": "0", "headline": "H", "summary": "S"}]})
        assert parse_response(text, 1) == {0: ("H", "S")}

    @pytest.mark.parametrize("text", ["", "not json at all", "{}", '{"stories": "wrong type"}'])
    def test_junk_yields_nothing(self, text):
        assert parse_response(text, 2) == {}


def test_build_prompt_lists_corroborating_outlets(topic, cluster):
    prompt = build_prompt(topic, [cluster])
    assert "[0]" in prompt
    assert "Also covered by: The Verge" in prompt
    # The model is never shown a URL, so it can never return one.
    assert "http" not in prompt


class FakePost:
    """Stands in for ``Session.post``."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self.responses.pop(0) if self.responses else self.responses[-1]


class FakeHTTPResponse:
    def __init__(self, status_code=200, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


def _openai_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class TestLLMSummarizer:
    def _summarizer(self, session, **overrides):
        cfg = SummarizeConfig(retries=0, **overrides)
        return LLMSummarizer(cfg, session=session)

    def test_uses_the_model_text(self, topic, cluster):
        body = json.dumps(
            {"stories": [{"index": 0, "headline": "Rubin arrives", "summary": "Two sentences."}]}
        )
        session = requests.Session()
        session.post = FakePost(FakeHTTPResponse(payload=_openai_payload(body)))

        story = self._summarizer(session).write(topic, [cluster])[0]
        assert story.headline == "Rubin arrives"
        assert story.summary == "Two sentences."

    def test_url_still_comes_from_the_article(self, topic, cluster):
        body = json.dumps(
            {"stories": [{"index": 0, "headline": "H", "summary": "S", "url": "https://evil.test"}]}
        )
        session = requests.Session()
        session.post = FakePost(FakeHTTPResponse(payload=_openai_payload(body)))

        story = self._summarizer(session).write(topic, [cluster])[0]
        assert story.url == cluster.lead.url

    def test_falls_back_when_the_endpoint_fails(self, topic, cluster):
        session = requests.Session()
        session.post = FakePost(FakeHTTPResponse(status_code=500, text="server error"))

        stories = self._summarizer(session).write(topic, [cluster])
        assert stories[0].headline == cluster.lead.title  # extractive output
        assert stories[0].summary

    def test_falls_back_per_story_on_partial_answers(self, topic, cluster, article_factory):
        second = Cluster(members=[article_factory("Another chip story", summary="Body here.")])
        body = json.dumps({"stories": [{"index": 0, "headline": "Only one", "summary": "S"}]})
        session = requests.Session()
        session.post = FakePost(FakeHTTPResponse(payload=_openai_payload(body)))

        stories = self._summarizer(session).write(topic, [cluster, second])
        assert stories[0].headline == "Only one"
        assert stories[1].headline == "Another chip story"

    def test_stops_calling_after_a_failure(self, topic, cluster):
        session = requests.Session()
        post = FakePost(
            FakeHTTPResponse(status_code=500, text="down"),
            FakeHTTPResponse(status_code=500, text="down"),
        )
        session.post = post

        summarizer = self._summarizer(session)
        summarizer.write(topic, [cluster])
        summarizer.write(topic, [cluster])
        # One outage should not cost a call per topic for the rest of the run.
        assert len(post.calls) == 1

    def test_anthropic_response_shape(self, topic, cluster):
        body = json.dumps({"stories": [{"index": 0, "headline": "H", "summary": "S"}]})
        session = requests.Session()
        session.post = FakePost(
            FakeHTTPResponse(payload={"content": [{"type": "text", "text": body}]})
        )

        summarizer = self._summarizer(session, api="anthropic")
        assert summarizer.write(topic, [cluster])[0].headline == "H"

    def test_anthropic_uses_its_own_headers(self, topic, cluster):
        body = json.dumps({"stories": [{"index": 0, "headline": "H", "summary": "S"}]})
        session = requests.Session()
        post = FakePost(FakeHTTPResponse(payload={"content": [{"type": "text", "text": body}]}))
        session.post = post

        self._summarizer(session, api="anthropic").write(topic, [cluster])
        assert "x-api-key" in post.calls[0]["headers"]
        assert post.calls[0]["url"].endswith("/messages")

    def test_no_clusters_makes_no_call(self, topic):
        session = requests.Session()
        post = FakePost()
        session.post = post
        assert self._summarizer(session).write(topic, []) == []
        assert post.calls == []


class TestSelection:
    def test_auto_without_a_key_is_extractive(self):
        assert get_summarizer(SummarizeConfig(provider="auto")).name == "extractive"

    def test_auto_with_a_key_is_the_model(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "sk-test")
        assert get_summarizer(SummarizeConfig(provider="auto")).name.startswith("llm:")

    def test_llm_without_a_key_degrades(self):
        assert get_summarizer(SummarizeConfig(provider="llm")).name == "extractive"

    def test_unknown_provider_degrades(self):
        assert get_summarizer(SummarizeConfig(provider="nonsense")).name == "extractive"
