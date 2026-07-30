"""
Minimal client for posting text to a Threads account via Meta's Threads API.

Setup required before this works (one-time, see README.md):
  1. Create a Meta developer app with the Threads Use Case enabled.
  2. Authorize it against the MetalRadr Threads account to get a
     short-lived user access token, then exchange it for a long-lived
     token (~60 days) and set up a refresh before it expires.
  3. Store that token as the THREADS_ACCESS_TOKEN secret (GitHub Actions
     secret, or local env var).
  4. Store the Threads user ID as THREADS_USER_ID.

API docs: https://developers.facebook.com/docs/threads
"""

import os
import time
import requests

GRAPH_BASE = "https://graph.threads.net/v1.0"


class ThreadsClient:
    def __init__(self, access_token: str | None = None, user_id: str | None = None):
        self.access_token = access_token or os.environ["THREADS_ACCESS_TOKEN"]
        self.user_id = user_id or os.environ["THREADS_USER_ID"]

    def post_text(self, text: str) -> str:
        """
        Publishing to Threads is two calls: create a media container,
        then publish it. Returns the published post's ID.
        """
        container_id = self._create_container(text)
        # Threads recommends a short pause between container creation and
        # publish to let it finish processing server-side.
        time.sleep(2)
        return self._publish_container(container_id)

    def _create_container(self, text: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads",
            data={
                "media_type": "TEXT",
                "text": text,
                "access_token": self.access_token,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def _publish_container(self, container_id: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.user_id}/threads_publish",
            data={
                "creation_id": container_id,
                "access_token": self.access_token,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["id"]


def format_post(event: dict) -> str:
    """Build the Threads post body for a matched event."""
    reason_labels = {
        "venue": None,  # venue is implicit — no need to label
        "artist": "on your watch list",
        "genre": f"matched genre: {event.get('matched_genre')}",
    }
    label = reason_labels.get(event["match_reason"])

    headline = event["title"].strip()
    if event.get("date"):
        headline += f" — {event['date']}"
    headline += f" — via {event['source']}"

    lines = [headline]
    if label:
        lines.append(label)
    lines.append(event["url"])

    return "\n".join(lines)
