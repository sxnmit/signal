"""Email delivery over SMTP."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from ..config import EmailConfig
from ..logs import get_logger
from ..models import Digest
from ..render.email import render_email, render_plaintext

__all__ = ["DeliveryResult", "send_digest"]

log = get_logger(__name__)


class DeliveryResult:
    """Outcome of one delivery attempt."""

    def __init__(self, sent: int = 0, failed: int = 0, error: str | None = None) -> None:
        self.sent = sent
        self.failed = failed
        self.error = error

    @property
    def ok(self) -> bool:
        return self.sent > 0 and self.failed == 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DeliveryResult(sent={self.sent}, failed={self.failed}, error={self.error!r})"


def build_message(
    digest: Digest, cfg: EmailConfig, recipient: str, *, base_url: str = ""
) -> EmailMessage:
    """Build one multipart/alternative message.

    The plain-text part is generated from the same digest rather than stripped
    from the HTML, so it reads properly rather than as markup debris.
    """
    subject = cfg.subject_template.format(
        icon="📡",
        title=digest.title,
        date=digest.generated_at.strftime("%b %d"),
        count=digest.story_count,
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((digest.title, cfg.sender))
    message["To"] = recipient
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=cfg.sender.split("@")[-1] or "localhost")
    # Tells Gmail and friends this is bulk mail, which keeps it out of Priority
    # Inbox rather than out of the inbox entirely.
    message["Auto-Submitted"] = "auto-generated"
    message["X-Entity-Ref-ID"] = digest.date_slug

    message.set_content(render_plaintext(digest))
    message.add_alternative(render_email(digest, base_url=base_url), subtype="html")
    return message


def send_digest(digest: Digest, cfg: EmailConfig, *, base_url: str = "") -> DeliveryResult:
    """Send the digest to every configured recipient.

    With ``private_recipients`` set (the default), each address gets its own
    message. v1 put every address in a single ``To:`` header, which disclosed
    the whole subscriber list to everyone on it.
    """
    if not cfg.configured:
        missing = ", ".join(cfg.missing())
        log.warning("Email not sent — missing %s", missing)
        return DeliveryResult(error=f"missing {missing}")

    recipients = list(cfg.recipients)
    batches = [[r] for r in recipients] if cfg.private_recipients else [recipients]

    sent = failed = 0
    error: str | None = None

    try:
        with _connect(cfg) as server:
            server.login(cfg.sender, cfg.password)

            for batch in batches:
                message = build_message(
                    digest, cfg, ", ".join(batch) if len(batch) > 1 else batch[0], base_url=base_url
                )
                try:
                    server.send_message(message, from_addr=cfg.sender, to_addrs=batch)
                    sent += len(batch)
                except smtplib.SMTPException as exc:
                    failed += len(batch)
                    error = str(exc)
                    log.warning("Delivery failed for %s: %s", ", ".join(batch), exc)

    except (smtplib.SMTPException, OSError, ssl.SSLError) as exc:
        log.error("SMTP connection failed: %s", exc)
        return DeliveryResult(sent=sent, failed=len(recipients) - sent, error=str(exc))

    if sent:
        log.info("Digest delivered to %d recipient(s)", sent)
    return DeliveryResult(sent=sent, failed=failed, error=error)


def _connect(cfg: EmailConfig) -> smtplib.SMTP:
    """Open an SMTP connection, implicit TLS on 465 and STARTTLS elsewhere."""
    context = ssl.create_default_context()

    if cfg.smtp_port == 465:
        return smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=context)

    server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
    server.ehlo()
    server.starttls(context=context)
    server.ehlo()
    return server
