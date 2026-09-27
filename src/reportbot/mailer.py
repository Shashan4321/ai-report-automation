"""Send the report by e-mail over SMTP. Dry-run unless SMTP settings are present."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


def build_message(
    html: str, subject: str, sender: str, recipients: list[str], attachment: Path | None = None
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, ", ".join(recipients)
    msg.set_content("Your monthly sales report is attached (HTML).")
    msg.add_alternative(html, subtype="html")
    if attachment:
        msg.add_attachment(
            attachment.read_bytes(), maintype="text", subtype="html", filename=attachment.name
        )
    return msg


def send(html: str, subject: str, attachment: Path | None = None) -> str:
    """Send if SMTP_HOST, SMTP_USER, SMTP_PASSWORD and REPORT_TO are set; else dry-run."""
    host, user, pwd = (os.getenv(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
    to = [a.strip() for a in os.getenv("REPORT_TO", "").split(",") if a.strip()]
    if not (host and user and pwd and to):
        return "dry-run: SMTP settings not configured, e-mail not sent"
    msg = build_message(html, subject, user, to, attachment)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)
    return f"sent to {len(to)} recipient(s)"
