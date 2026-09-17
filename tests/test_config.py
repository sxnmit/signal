"""Config loading, merging, and environment overrides."""

from __future__ import annotations

import pytest

from signal_agent.config import Config, ConfigError, Topic
from signal_agent.env import parse_dotenv


class TestDefaults:
    def test_packaged_defaults_load(self):
        config = Config.load()
        assert config.title == "Signal"
        assert config.topics
        assert config.feeds
        assert config.source_path is None

    def test_every_topic_has_keywords(self):
        for topic in Config.load().topics:
            assert topic.keywords, f"{topic.name} has no keywords"

    def test_topic_slugs_are_unique(self):
        slugs = [t.slug for t in Config.load().topics]
        assert len(slugs) == len(set(slugs))

    def test_feed_urls_are_unique(self):
        urls = [f.url for f in Config.load().feeds]
        assert len(urls) == len(set(urls))


class TestUserConfig:
    def test_partial_config_merges_over_defaults(self, tmp_path):
        path = tmp_path / "signal.toml"
        path.write_text('title = "My Feed"\n[fetch]\nwindow_hours = 12\n')

        config = Config.load(path)
        assert config.title == "My Feed"
        assert config.fetch.window_hours == 12
        # Untouched sections still come from the defaults.
        assert config.topics
        assert config.fetch.timeout_seconds == 12

    def test_topics_replace_rather_than_append(self, tmp_path):
        path = tmp_path / "signal.toml"
        path.write_text('[[topics]]\nname = "Only This"\nkeywords = ["x"]\n')
        assert len(Config.load(path).topics) == 1

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            Config.load(tmp_path / "absent.toml")

    def test_broken_toml_raises(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("this is not = = toml")
        with pytest.raises(ConfigError):
            Config.load(path)

    def test_unknown_keys_are_ignored(self, tmp_path):
        # A config written for a newer Signal must not break an older one.
        path = tmp_path / "signal.toml"
        path.write_text("[fetch]\nwindow_hours = 8\nfuture_option = true\n")
        assert Config.load(path).fetch.window_hours == 8

    def test_topic_without_a_name_raises(self, tmp_path):
        path = tmp_path / "signal.toml"
        path.write_text('[[topics]]\nkeywords = ["x"]\n')
        with pytest.raises(ConfigError):
            Config.load(path)

    def test_slug_is_derived_from_name(self):
        assert Topic.from_dict({"name": "Chips & Hardware"}).slug == "chips-hardware"


class TestEnvironment:
    def test_v1_secret_names_still_work(self, monkeypatch):
        # The old workflow exported these; they must keep working untouched.
        monkeypatch.setenv("SENDER_EMAIL", "me@example.com")
        monkeypatch.setenv("SENDER_PASSWORD", "app-password")
        monkeypatch.setenv("RECIPIENT_EMAILS", "a@example.com, b@example.com")

        email = Config.load().email
        assert email.sender == "me@example.com"
        assert email.recipients == ("a@example.com", "b@example.com")
        assert email.configured

    def test_signal_prefixed_names_win(self, monkeypatch):
        monkeypatch.setenv("SENDER_EMAIL", "old@example.com")
        monkeypatch.setenv("SIGNAL_SENDER", "new@example.com")
        assert Config.load().email.sender == "new@example.com"

    def test_smtp_port_override(self, monkeypatch):
        monkeypatch.setenv("SMTP_PORT", "465")
        assert Config.load().email.smtp_port == 465

    def test_invalid_port_falls_back(self, monkeypatch):
        monkeypatch.setenv("SMTP_PORT", "not-a-number")
        assert Config.load().email.smtp_port == 587

    def test_webhook_url_enables_the_channel(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_WEBHOOK_URL", "https://hooks.example.com/x")
        assert Config.load().webhook.configured

    def test_legacy_db_path(self, monkeypatch):
        monkeypatch.setenv("NEWS_DIGEST_DB_PATH", "/tmp/legacy.db")
        assert Config.load().store.path == "/tmp/legacy.db"


class TestSummarizerSelection:
    def test_auto_without_a_key_is_extractive(self):
        assert Config.load().summarize.resolved_provider() == "extractive"

    def test_auto_with_a_key_is_llm(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "sk-test")
        assert Config.load().summarize.resolved_provider() == "llm"

    def test_explicit_choice_is_respected(self, monkeypatch):
        monkeypatch.setenv("SIGNAL_SUMMARIZER", "extractive")
        monkeypatch.setenv("GROQ_API_KEY", "sk-test")
        assert Config.load().summarize.resolved_provider() == "extractive"


class TestEmailReadiness:
    def test_reports_what_is_missing(self):
        assert set(Config.load().email.missing()) == {
            "SENDER_EMAIL",
            "SENDER_PASSWORD",
            "RECIPIENT_EMAILS",
        }


class TestDotenv:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("A=1", {"A": "1"}),
            ("export A=1", {"A": "1"}),
            ('A="hello world"', {"A": "hello world"}),
            ("A='raw $value'", {"A": "raw $value"}),
            ("A=plain # trailing", {"A": "plain"}),
            ("# just a comment", {}),
            ("", {}),
            ("no_equals_sign", {}),
        ],
    )
    def test_parsing(self, text, expected):
        assert parse_dotenv(text) == expected

    def test_real_environment_wins(self, tmp_path, monkeypatch):
        from signal_agent.env import load_dotenv

        monkeypatch.setenv("SHARED", "from-environment")
        path = tmp_path / ".env"
        path.write_text("SHARED=from-file\nONLY_IN_FILE=yes\n")

        load_dotenv(path)
        import os

        assert os.environ["SHARED"] == "from-environment"
        assert os.environ["ONLY_IN_FILE"] == "yes"

    def test_missing_file_is_fine(self, tmp_path):
        from signal_agent.env import load_dotenv

        assert load_dotenv(tmp_path / "nope.env") == {}
