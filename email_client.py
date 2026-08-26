"""
Minimal client for sending a "new shows" digest email via Gmail's SMTP
relay. Used while Threads API setup (see threads_client.py) is on hold.

Setup required before this works (one-time, see README.md):
  1. Turn on 2-Step Verification on the Gmail account you want to send
     from.
  2. Create an App Password for "Mail" and store it as the
     GMAIL_APP_PASSWORD secret.
  3. Store the sending Gmail address as GMAIL_ADDRESS.
  4. Store where alerts should land as ALERT_EMAIL — one address, or
     several comma-separated (e.g. "a@example.com, b@example.com").
     Can be the same address you're sending from, or different inboxes
     you actually check.
"""

import os
import smtplib
from email.message import EmailMessage

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class EmailClient:
    def __init__(
        self,
        address: str | None = None,
        app_password: str | None = None,
        to_addr: str | None = None,
    ):
        self.address = address or os.environ["GMAIL_ADDRESS"]
        self.app_password = app_password or os.environ["GMAIL_APP_PASSWORD"]
        to_addr_raw = to_addr or os.environ["ALERT_EMAIL"]
        self.to_addrs = [a.strip() for a in to_addr_raw.split(",") if a.strip()]

    def send_digest(self, events: list[dict]) -> None:
        """Send a single email listing every newly-matched event to every recipient."""
        msg = EmailMessage()
        msg["Subject"] = format_subject(events)
        msg["From"] = self.address
        msg["To"] = ", ".join(self.to_addrs)
        msg.set_content(format_digest(events))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(self.address, self.app_password)
            smtp.send_message(msg)


def format_subject(events: list[dict]) -> str:
    noun = "show" if len(events) == 1 else "shows"
    return f"MetalRadr: {len(events)} new {noun}"


def format_digest(events: list[dict]) -> str:
    """Build the plaintext email body listing each new event."""
    blocks = []
    for event in events:
        headline = event["title"].strip()
        if event.get("date"):
            headline += f" — {event['date']}"
        headline += f" — via {event['source']}"
        blocks.append(f"{headline}\n{event['url']}")
    return "\n\n".join(blocks)
