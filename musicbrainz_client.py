"""
Minimal client for looking up an artist's genre tags via the MusicBrainz
API — used as a fallback when plain title-keyword genre matching misses
(e.g. "Avenged Sevenfold" doesn't contain the word "metal" anywhere in
its own name).

API docs: https://musicbrainz.org/doc/MusicBrainz_API
No API key needed, but MusicBrainz requires a descriptive User-Agent and
enforces a strict 1 request/second rate limit — both are handled here.
"""

import time

import requests

API_URL = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = "MetalRadr/1.0 ( https://github.com/mxtess/MetalRadr )"
MIN_REQUEST_INTERVAL = 1.0  # seconds — MusicBrainz's documented rate limit

_last_request_at = 0.0


def _throttle() -> None:
    """Block just long enough to keep requests at least 1s apart."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def lookup_artist_tags(artist_name: str) -> list[str]:
    """
    Search MusicBrainz for artist_name and return the top-scoring
    result's tags (lowercase).

    Note: the search endpoint's inc=genres doesn't actually populate a
    curated "genres" field (only the direct entity-lookup endpoint by
    MBID does that) — it does always return "tags" though, a broader
    community-tagged set that includes genre-like tags alongside noise
    (e.g. "usa", "anthemic"). That's fine here since callers only check
    membership against their own curated genre list, so noise tags
    simply never match anything.

    Returns [] if there's no result, no tags, or the request fails for
    any reason — a lookup miss should degrade to "no genre info", not
    break the run.
    """
    _throttle()
    try:
        resp = requests.get(
            API_URL,
            params={"query": artist_name, "fmt": "json", "inc": "genres"},
            headers={"User-Agent": USER_AGENT},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    artists = data.get("artists") or []
    if not artists:
        return []

    top = artists[0]
    tags = top.get("genres") or top.get("tags") or []
    return [t["name"].lower() for t in tags if t.get("name")]
