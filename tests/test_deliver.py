"""Delivery channels, with SMTP and HTTP faked out."""

from __future__ import annotations

import smtplib
from datetime import UTC, datetime

import pytest
import requests

from signal_agent.config import EmailConfig, WebhookConfig
from signal_agent.deliver.smtp import build_message, send_digest
from signal_agent.deliver.webhook import build_payload, post_digest
from signal_agent.models import Digest, Section, Story


@pytest.fixture
def digest() -> Digest:
    return Digest(
        generated_at=datetime(2026, 9, 17, 12, tzinfo=UTC),
        sections=[
            Section(
                topic="World",
                slug="world",
                icon="🌍",
                stories=[
                    Story(
                        headline="Talks stall",
                        summary="No agreement was reached.",
                        url="https://bbc.example.com/talks",
                        source="BBC",
                        corroboration=2,
                        also_covered_by=[("CNN", "https://cnn.example.com/talks")],
                    )
                ],
            )
        ],
    )


@pytest.fixture
def email_cfg() -> EmailConfig:
    return EmailConfig(
        sender="me@example.com",
        password="app-password",
        recipients=("a@example.com", "b@example.com"),
    )


class FakeSMTP:
    """Captures what would have been sent."""

    instances: list = []

    def __init__(self, *args, **kwargs):
        self.sent: list[tuple[str, list[str]]] = []
        self.logged_in = False
        self.started_tls = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = True

    def send_message(self, message, from_addr=None, to_addrs=None):
        self.sent.append((message["To"], list(to_addrs or [])))

    def quit(self):
        pass


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


class TestMessage:
    def test_is_multipart_with_both_parts(self, digest, email_cfg):
        message = build_message(digest, email_cfg, "a@example.com")
        types = {part.get_content_type() for part in message.walk()}
        assert "text/plain" in types
        assert "text/html" in types

    def test_subject_uses_the_template(self, digest, email_cfg):
        message = build_message(digest, email_cfg, "a@example.com")
        assert "Signal" in message["Subject"]
        assert "Sep 17" in message["Subject"]

    def test_marks_itself_as_automated(self, digest, email_cfg):
        message = build_message(digest, email_cfg, "a@example.com")
        assert message["Auto-Submitted"] == "auto-generated"


class TestSend:
    def test_one_message_per_recipient_by_default(self, digest, email_cfg, fake_smtp):
        # v1 put every address in one To: header, disclosing the list to everyone.
        result = send_digest(digest, email_cfg)

        assert result.ok
        assert result.sent == 2
        server = fake_smtp.instances[0]
        assert [to for to, _ in server.sent] == ["a@example.com", "b@example.com"]

    def test_shared_recipients_when_asked(self, digest, email_cfg, fake_smtp):
        import dataclasses

        cfg = dataclasses.replace(email_cfg, private_recipients=False)
        send_digest(digest, cfg)
        assert len(fake_smtp.instances[0].sent) == 1

    def test_uses_starttls(self, digest, email_cfg, fake_smtp):
        send_digest(digest, email_cfg)
        assert fake_smtp.instances[0].started_tls

    def test_implicit_tls_on_465(self, digest, email_cfg, fake_smtp):
        import dataclasses

        send_digest(digest, dataclasses.replace(email_cfg, smtp_port=465))
        # SMTP_SSL needs no STARTTLS handshake.
        assert not fake_smtp.instances[0].started_tls

    def test_missing_credentials_is_reported_not_raised(self, digest):
        result = send_digest(digest, EmailConfig())
        assert not result.ok
        assert "SENDER_EMAIL" in result.error

    def test_connection_failure_is_reported(self, digest, email_cfg, monkeypatch):
        def explode(*args, **kwargs):
            raise OSError("no route to host")

        monkeypatch.setattr(smtplib, "SMTP", explode)
        result = send_digest(digest, email_cfg)
        assert not result.ok
        assert "no route" in result.error


class TestWebhook:
    def test_slack_payload_shape(self, digest):
        payload = build_payload(digest, WebhookConfig(format="slack", url="https://x"))
        assert payload["blocks"][0]["type"] == "header"
        assert "Talks stall" in str(payload)

    def test_slack_escapes_markup(self):
        digest = Digest(
            generated_at=datetime(2026, 9, 17, tzinfo=UTC),
            sections=[
                Section(
                    topic="T",
                    slug="t",
                    icon="x",
                    stories=[
                        Story(
                            headline="A <script> & B",
                            summary="s",
                            url="https://e.com/a",
                            source="E",
                        )
                    ],
                )
            ],
        )
        payload = build_payload(digest, WebhookConfig(format="slack"))
        assert "&lt;script&gt;" in str(payload)

    def test_discord_payload(self, digest):
        payload = build_payload(digest, WebhookConfig(format="discord"))
        assert "content" in payload
        assert len(payload["content"]) <= 1900

    def test_json_payload_is_the_digest(self, digest):
        payload = build_payload(digest, WebhookConfig(format="json"))
        assert payload["date"] == "2026-09-17"

    def test_post_success(self, digest, monkeypatch):
        class Response:
            status_code = 200

        session = requests.Session()
        session.post = lambda *a, **k: Response()
        cfg = WebhookConfig(enabled=True, url="https://hooks.example.com/x")
        assert post_digest(digest, cfg, session=session)

    def test_post_failure_is_reported(self, digest):
        class Response:
            status_code = 500

        session = requests.Session()
        session.post = lambda *a, **k: Response()
        cfg = WebhookConfig(enabled=True, url="https://hooks.example.com/x")
        assert not post_digest(digest, cfg, session=session)

    def test_network_error_is_swallowed(self, digest):
        session = requests.Session()

        def explode(*a, **k):
            raise requests.ConnectionError("down")

        session.post = explode
        cfg = WebhookConfig(enabled=True, url="https://hooks.example.com/x")
        assert not post_digest(digest, cfg, session=session)

    def test_unconfigured_is_a_noop(self, digest):
        assert not post_digest(digest, WebhookConfig())
