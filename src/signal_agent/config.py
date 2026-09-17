"""Configuration: packaged defaults, an optional TOML file, then the environment.

Precedence, lowest to highest:

1. ``default_config.toml`` shipped inside the package
2. a user ``signal.toml`` (deep-merged, so it only needs the keys it changes)
3. environment variables, including the ones the v1 GitHub Actions workflow set

Secrets are never read from the TOML file. They are looked up by name at the
point of use, so a config file is always safe to commit.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

__all__ = [
    "ArchiveConfig",
    "Config",
    "DedupConfig",
    "EmailConfig",
    "Feed",
    "FetchConfig",
    "HackerNewsConfig",
    "NewsAPIConfig",
    "RankConfig",
    "SiteConfig",
    "StoreConfig",
    "SummarizeConfig",
    "Topic",
    "WebhookConfig",
    "config_search_paths",
]

_PACKAGE_DEFAULT = "default_config.toml"


class ConfigError(ValueError):
    """Raised when a config file is present but unusable."""


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge ``overlay`` onto ``base``.

    Tables merge key by key; every other value (including lists) replaces
    wholesale, so redefining ``[[topics]]`` means "these are my topics" rather
    than "add these to the defaults".
    """
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _env_str(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else None


def _env_int(name: str) -> int | None:
    raw = _env_str(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _slugify(value: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in value.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "topic"


@dataclass(frozen=True, slots=True)
class Feed:
    """One RSS or Atom feed."""

    url: str
    name: str = ""
    weight: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Feed:
        return cls(
            url=str(data["url"]).strip(),
            name=str(data.get("name", "")).strip(),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class Topic:
    """A digest section, plus the vocabulary used to route articles into it."""

    name: str
    slug: str
    icon: str = "•"
    query: str = ""
    max_stories: int = 4
    keywords: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Topic:
        name = str(data.get("name", "")).strip()
        if not name:
            raise ConfigError("every [[topics]] entry needs a name")
        keywords = tuple(str(k).strip().lower() for k in data.get("keywords", []) if str(k).strip())
        return cls(
            name=name,
            slug=str(data.get("slug") or _slugify(name)),
            icon=str(data.get("icon", "•")),
            query=str(data.get("query", "")).strip(),
            max_stories=int(data.get("max_stories", 4)),
            keywords=keywords,
        )


@dataclass(frozen=True, slots=True)
class FetchConfig:
    window_hours: int = 36
    timeout_seconds: int = 12
    max_workers: int = 12
    user_agent: str = "signal/2.0"


@dataclass(frozen=True, slots=True)
class DedupConfig:
    similarity_threshold: float = 0.35
    retention_days: int = 90


@dataclass(frozen=True, slots=True)
class RankConfig:
    recency_half_life_hours: float = 18.0
    corroboration_weight: float = 0.55
    min_score: float = 0.15
    max_stories_per_topic: int = 5
    max_clusters_per_run: int = 60


@dataclass(frozen=True, slots=True)
class SummarizeConfig:
    provider: str = "auto"
    api: str = "openai"
    base_url: str = "https://api.groq.com/openai/v1"
    model: str = "llama-3.3-70b-versatile"
    api_key_env: str = "GROQ_API_KEY"
    max_tokens: int = 2000
    temperature: float = 0.2
    timeout_seconds: int = 60
    retries: int = 2

    @property
    def api_key(self) -> str:
        """The key named by :attr:`api_key_env`, or an empty string."""
        return os.environ.get(self.api_key_env, "").strip()

    def resolved_provider(self) -> str:
        """Turn ``auto`` into a concrete choice based on whether a key exists."""
        if self.provider == "auto":
            return "llm" if self.api_key else "extractive"
        return self.provider


@dataclass(frozen=True, slots=True)
class StoreConfig:
    path: str = "news_digest.db"


@dataclass(frozen=True, slots=True)
class ArchiveConfig:
    enabled: bool = True
    directory: str = "archive"


@dataclass(frozen=True, slots=True)
class SiteConfig:
    enabled: bool = True
    directory: str = "site"
    base_url: str = ""


@dataclass(frozen=True, slots=True)
class EmailConfig:
    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    sender: str = ""
    password: str = ""
    recipients: tuple[str, ...] = ()
    private_recipients: bool = True
    subject_template: str = "{icon} {title} — {date}"

    @property
    def configured(self) -> bool:
        """True when there is enough here to actually send a message."""
        return bool(self.enabled and self.sender and self.password and self.recipients)

    def missing(self) -> list[str]:
        """Human-readable list of what still needs to be set."""
        gaps = []
        if not self.sender:
            gaps.append("SENDER_EMAIL")
        if not self.password:
            gaps.append("SENDER_PASSWORD")
        if not self.recipients:
            gaps.append("RECIPIENT_EMAILS")
        return gaps


@dataclass(frozen=True, slots=True)
class WebhookConfig:
    enabled: bool = False
    url: str = ""
    format: str = "slack"

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.url)


@dataclass(frozen=True, slots=True)
class NewsAPIConfig:
    enabled: bool = True
    api_key_env: str = "NEWS_API_KEY"
    language: str = "en"
    max_articles: int = 5
    page_size: int = 20

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.api_key)


@dataclass(frozen=True, slots=True)
class HackerNewsConfig:
    enabled: bool = True
    min_points: int = 120
    max_articles: int = 25


@dataclass(frozen=True, slots=True)
class Config:
    """The whole configuration, already merged and environment-resolved."""

    title: str = "Signal"
    tagline: str = ""
    fetch: FetchConfig = field(default_factory=FetchConfig)
    dedup: DedupConfig = field(default_factory=DedupConfig)
    rank: RankConfig = field(default_factory=RankConfig)
    summarize: SummarizeConfig = field(default_factory=SummarizeConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)
    site: SiteConfig = field(default_factory=SiteConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    newsapi: NewsAPIConfig = field(default_factory=NewsAPIConfig)
    hackernews: HackerNewsConfig = field(default_factory=HackerNewsConfig)
    feeds: tuple[Feed, ...] = ()
    topics: tuple[Topic, ...] = ()
    source_path: Path | None = None
    """Where the user config came from, or ``None`` when defaults were used."""

    def feed_weights(self) -> dict[str, float]:
        """``feed url -> weight`` lookup, used when building articles."""
        return {f.url: f.weight for f in self.feeds}

    def topic(self, slug: str) -> Topic | None:
        return next((t for t in self.topics if t.slug == slug), None)

    # -- loading ---------------------------------------------------------

    @staticmethod
    def packaged_defaults() -> str:
        """The bundled ``signal.toml``, as text. Also what ``signal init`` writes."""
        resource = resources.files("signal_agent").joinpath(_PACKAGE_DEFAULT)
        return resource.read_text(encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path | None = None) -> Config:
        """Build a config from defaults, an optional file, and the environment.

        ``path`` wins when given. Otherwise the first file found in
        :func:`config_search_paths` is used, and if there is none the packaged
        defaults are used on their own.
        """
        data = tomllib.loads(cls.packaged_defaults())

        chosen: Path | None = None
        candidates = [Path(path)] if path is not None else config_search_paths()
        for candidate in candidates:
            if candidate.is_file():
                chosen = candidate
                break

        if chosen is None and path is not None:
            raise ConfigError(f"config file not found: {path}")

        if chosen is not None:
            try:
                overlay = tomllib.loads(chosen.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{chosen}: {exc}") from exc
            data = _deep_merge(data, overlay)

        return cls.from_dict(data, source_path=chosen)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, source_path: Path | None = None) -> Config:
        """Build a config from an already-merged mapping, then apply the environment."""

        def table(name: str) -> dict[str, Any]:
            value = data.get(name, {})
            return dict(value) if isinstance(value, dict) else {}

        def build(kind: type[Any], name: str) -> Any:
            # Ignore unknown keys rather than exploding: a config written for a
            # newer Signal should still start on an older one.
            fields = set(kind.__dataclass_fields__)
            return kind(**{k: v for k, v in table(name).items() if k in fields})

        email_data = table("email")
        recipients = tuple(
            str(r).strip() for r in email_data.pop("recipients", []) if str(r).strip()
        )
        email_fields = set(EmailConfig.__dataclass_fields__)
        email = EmailConfig(
            recipients=recipients,
            **{k: v for k, v in email_data.items() if k in email_fields and k != "recipients"},
        )

        config = cls(
            title=str(data.get("title", "Signal")),
            tagline=str(data.get("tagline", "")),
            fetch=build(FetchConfig, "fetch"),
            dedup=build(DedupConfig, "dedup"),
            rank=build(RankConfig, "rank"),
            summarize=build(SummarizeConfig, "summarize"),
            store=build(StoreConfig, "store"),
            archive=build(ArchiveConfig, "archive"),
            site=build(SiteConfig, "site"),
            email=email,
            webhook=build(WebhookConfig, "webhook"),
            newsapi=build(NewsAPIConfig, "newsapi"),
            hackernews=build(HackerNewsConfig, "hackernews"),
            feeds=tuple(Feed.from_dict(f) for f in data.get("feeds", []) if f.get("url")),
            topics=tuple(Topic.from_dict(t) for t in data.get("topics", [])),
            source_path=source_path,
        )
        return config.with_environment()

    def with_environment(self) -> Config:
        """Apply environment overrides, including the v1 secret names.

        The old workflow exported ``SENDER_EMAIL``/``RECIPIENT_EMAILS``/etc., so
        those keep working unchanged; ``SIGNAL_*`` names are the documented ones
        going forward and win when both are set.
        """
        import dataclasses

        recipients_raw = _env_str("SIGNAL_RECIPIENTS") or _env_str("RECIPIENT_EMAILS")
        recipients = (
            tuple(r.strip() for r in recipients_raw.split(",") if r.strip())
            if recipients_raw
            else self.email.recipients
        )

        email = dataclasses.replace(
            self.email,
            smtp_host=_env_str("SIGNAL_SMTP_HOST") or _env_str("SMTP_HOST") or self.email.smtp_host,
            smtp_port=_env_int("SIGNAL_SMTP_PORT") or _env_int("SMTP_PORT") or self.email.smtp_port,
            sender=_env_str("SIGNAL_SENDER") or _env_str("SENDER_EMAIL") or self.email.sender,
            password=(
                _env_str("SIGNAL_SENDER_PASSWORD")
                or _env_str("SENDER_PASSWORD")
                or self.email.password
            ),
            recipients=recipients,
        )

        summarize = dataclasses.replace(
            self.summarize,
            provider=_env_str("SIGNAL_SUMMARIZER") or self.summarize.provider,
            api=_env_str("SIGNAL_LLM_API") or self.summarize.api,
            base_url=_env_str("SIGNAL_LLM_BASE_URL") or self.summarize.base_url,
            model=_env_str("SIGNAL_LLM_MODEL") or self.summarize.model,
            api_key_env=_env_str("SIGNAL_LLM_API_KEY_ENV") or self.summarize.api_key_env,
        )

        webhook_url = _env_str("SIGNAL_WEBHOOK_URL")
        webhook = dataclasses.replace(
            self.webhook,
            url=webhook_url or self.webhook.url,
            enabled=self.webhook.enabled or bool(webhook_url),
        )

        store = dataclasses.replace(
            self.store,
            path=(_env_str("SIGNAL_DB_PATH") or _env_str("NEWS_DIGEST_DB_PATH") or self.store.path),
        )

        site = dataclasses.replace(
            self.site, base_url=_env_str("SIGNAL_SITE_BASE_URL") or self.site.base_url
        )

        return dataclasses.replace(
            self, email=email, summarize=summarize, webhook=webhook, store=store, site=site
        )


def config_search_paths() -> list[Path]:
    """Where :meth:`Config.load` looks for a user config, in order."""
    paths: list[Path] = []
    if explicit := _env_str("SIGNAL_CONFIG"):
        paths.append(Path(explicit))
    paths.append(Path("signal.toml"))
    paths.append(Path.home() / ".config" / "signal" / "signal.toml")
    return paths
