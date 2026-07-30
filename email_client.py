"""
Minimal client for sending a "new shows" digest email via Gmail's SMTP
relay. Used while Threads API setup (see threads_client.py) is on hold.

Setup required before this works (one-time, see README.md):
  1. Turn on 2-Step Verification on the Gmail account you want to send
     from.
  2. Create an App Password for "Mail" and store it as the
     GMAIL_APP_PASSWORD secret.
  3. Store the sending Gmail address as GMAIL_ADDRESS.
  4. Store the address alerts should land in as ALERT_EMAIL (can be the
     same address, or a different inbox you actually check).
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
        self.to_addr = to_addr or os.environ["ALERT_EMAIL"]

    def send_digest(self, events: list[dict]) -> None:
        """Send a single email listing every newly-matched event."""
        msg = EmailMessage()
        msg["Subject"] = format_subject(events)
        msg["From"] = self.address
        msg["To"] = self.to_addr
        msg.set_content(format_digest(events))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(self.address, self.app_password)
            smtp.send_message(msg)


def format_subject(events: list[dict]) -> str:
    noun = "show" if len(events) == 1 else "shows"
    return f"MetalRadr: {len(events)} new {noun}"


def format_digest(events: list[dict]) -> str:
    """Build the plaintext email body listing each new event."""
    blocks = [
        f"{event['title'].strip()}\n{event['source']}\n{event['url']}"
        for event in events
    ]
    return "\n\n".join(blocks)
