"""Tiny SMTP mailer for verification / notification emails.

Configured entirely via environment variables (put them in .env):

    SMTP_HOST      e.g. smtp.office365.com
    SMTP_PORT      e.g. 587   (STARTTLS)
    SMTP_USER      the login / mailbox, e.g. ruimin@jilai.ai
    SMTP_PASSWORD  the mailbox password — for Office 365 with MFA, use an
                   "App Password" (basic SMTP AUTH must be allowed on the tenant)
    SMTP_FROM      optional From address (defaults to SMTP_USER)

Self-test (sends a message to yourself):
    python -m product_researcher.mailer you@example.com
"""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER") and os.getenv("SMTP_PASSWORD"))


def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    """Send one email via STARTTLS. Raises on failure."""
    host = os.getenv("SMTP_HOST", "smtp.office365.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("SMTP_FROM") or user

    if not (host and user and password):
        raise RuntimeError(
            "SMTP is not configured. Set SMTP_HOST, SMTP_USER and SMTP_PASSWORD "
            "in your .env (for Office 365 with MFA, use an App Password)."
        )

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(user, password)
        server.send_message(msg)


def send_verification_email(to: str, link: str) -> None:
    subject = "Verify your email — Marketing Agent Team"
    text = (
        "Welcome to Marketing Agent Team!\n\n"
        f"Please confirm your email address by opening this link:\n{link}\n\n"
        "If you didn't create an account, you can ignore this message."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a">'
        "<h2 style='margin:0 0 12px'>Welcome to Marketing Agent Team</h2>"
        "<p>Please confirm your email address to finish setting up your account.</p>"
        f'<p><a href="{link}" style="display:inline-block;background:#1f6feb;color:#fff;'
        'text-decoration:none;padding:11px 20px;border-radius:8px;font-weight:600">'
        "Verify my email</a></p>"
        f'<p style="color:#666;font-size:13px">Or paste this link into your browser:<br>{link}</p>'
        "<p style='color:#666;font-size:13px'>If you didn't create an account, you can ignore this email.</p>"
        "</div>"
    )
    send_email(to, subject, text, html)


def send_reset_email(to: str, link: str) -> None:
    subject = "Reset your password — Marketing Agent Team"
    text = (
        "We received a request to reset your Marketing Agent Team password.\n\n"
        f"Open this link to choose a new password (valid for 1 hour):\n{link}\n\n"
        "If you didn't request this, you can safely ignore this email."
    )
    html = (
        '<div style="font-family:Arial,sans-serif;font-size:15px;color:#1a1a1a">'
        "<h2 style='margin:0 0 12px'>Reset your password</h2>"
        "<p>Click below to choose a new password. This link is valid for 1 hour.</p>"
        f'<p><a href="{link}" style="display:inline-block;background:#1f6feb;color:#fff;'
        'text-decoration:none;padding:11px 20px;border-radius:8px;font-weight:600">'
        "Reset password</a></p>"
        f'<p style="color:#666;font-size:13px">Or paste this link into your browser:<br>{link}</p>'
        "<p style='color:#666;font-size:13px'>If you didn't request this, you can ignore this email.</p>"
        "</div>"
    )
    send_email(to, subject, text, html)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except Exception:
        pass
    recipient = sys.argv[1] if len(sys.argv) > 1 else os.getenv("SMTP_USER")
    if not recipient:
        print("Usage: python -m product_researcher.mailer <recipient_email>")
        raise SystemExit(2)
    print(f"Sending a test email to {recipient} via {os.getenv('SMTP_HOST')}:{os.getenv('SMTP_PORT')} ...")
    try:
        send_email(recipient, "Marketing Agent Team — SMTP test",
                   "This is a test email. If you received it, SMTP works. ✅")
        print("✅ Sent. Check the inbox (and spam folder).")
    except Exception as exc:
        print(f"❌ Failed: {type(exc).__name__}: {exc}")
        raise SystemExit(1)
