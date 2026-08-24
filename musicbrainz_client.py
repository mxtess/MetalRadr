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
MAX_CANDIDATES = 5  # how many top-scoring search results to pool tags from
MAX_ATTEMPTS = 3  # retries for transient network errors, not for genuine empty results

# MusicBrainz's canonical special-purpose artist entries — administrative
# placeholders, not real artists, used for unattributed/compilation
# releases (https://musicbrainz.org/doc/Style/Unknown_and_untitled).
# These IDs are fixed and identical across every MusicBrainz install.
# Their "tags" are a chaotic community dumping ground that happens to
# include real genre words (e.g. "rock", "metal", "electronic"), so a
# garbage query (an artist name that doesn't really exist, or that a
# broken scraper mangled) can score these highly and spuriously produce
# a "genre match" that means nothing. Must always be excluded.
_SPECIAL_PURPOSE_ARTIST_IDS = {
    "125ec42a-7229-4250-afc5-e057484327fe",  # [unknown]
    "89ad4ac3-39f7-470e-963a-56509c546377",  # Various Artists
}

_last_request_at = 0.0


def _throttle() -> None:
    """Block just long enough to keep requests at least 1s apart."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def lookup_artist_tags(artist_name: str) -> list[str] | None:
    """
    Search MusicBrainz for artist_name and return the combined, deduped
    tags (lowercase) pooled from up to the top MAX_CANDIDATES scoring
    results, in score order.

    A single top result isn't always trustworthy for common/generic
    artist names: MusicBrainz's fuzzy search can rank an unrelated
    same-word entity above the intended artist. For example searching
    "President" top-scores a German Euro-Dance trio called "Mr.
    President" over the real "PRESIDENT" (UK metal band), which only
    shows up a few places down — and the real band is the one with
    tags that actually mean something (thrash metal, metalcore, etc).
    The single best-scored result is always trusted; beyond that, a
    candidate is only pooled in if its name is an EXACT (case-
    insensitive) match to the query — not just a fuzzy/partial
    similarity — so this only ever picks up a different real entity
    that happens to share the exact same name, not any coincidentally
    similar but unrelated act. Candidates matching MusicBrainz's own
    special-purpose placeholder artists (see _SPECIAL_PURPOSE_ARTIST_IDS)
    are skipped entirely and don't count towards MAX_CANDIDATES — their
    tags are junk that happens to include real genre words, which would
    otherwise turn any garbage/unrecognized artist name into a false
    "genre match".

    Note: the search endpoint's inc=genres doesn't actually populate a
    curated "genres" field (only the direct entity-lookup endpoint by
    MBID does that) — it does always return "tags" though, a broader
    community-tagged set that includes genre-like tags alongside noise
    (e.g. "usa", "anthemic"). That's fine here for the same reason.

    Returns None if the request itself failed after retries (network
    error, bad response) — distinct from a genuine empty result. This
    matters because MusicBrainz connections do intermittently drop, and
    a transient failure must NOT be cached as "this artist has no
    tags": callers should skip caching a None and just retry the lookup
    fresh next run. Returns [] (an empty list) when the request
    succeeded but there's truly no result or no tags at all — that IS a
    stable, cacheable outcome.
    """
    data = None
    for attempt in range(MAX_ATTEMPTS):
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
            break
        except (requests.RequestException, ValueError):
            continue
    if data is None:
        return None

    artists = data.get("artists") or []
    query_normalized = artist_name.strip().lower()

    tags = []
    seen = set()
    candidates_used = 0
    for artist in artists:
        if candidates_used >= MAX_CANDIDATES:
            break
        if artist.get("id") in _SPECIAL_PURPOSE_ARTIST_IDS:
            continue
        disambiguation = (artist.get("disambiguation") or "").lower()
        if "special purpose" in disambiguation:
            continue
        # The single best-scored (non-junk) result is trusted
        # unconditionally — the common case where an act's own name is
        # the clear top match. Anything beyond that is only pooled in if
        # its name is an EXACT (case-insensitive) match to the query, not
        # merely a fuzzy/partial similarity — otherwise pooling would
        # start pulling in tags from coincidentally similar but unrelated
        # acts (e.g. a query for "Bingo Loco" — a non-music party-bingo
        # night, not a band — fuzzy-matches "Bingo Players", an
        # unrelated real DJ duo, several ranks down).
        if candidates_used > 0 and (artist.get("name") or "").strip().lower() != query_normalized:
            continue
        candidates_used += 1
        for t in artist.get("genres") or artist.get("tags") or []:
            name = t.get("name")
            if name and name.lower() not in seen:
                seen.add(name.lower())
                tags.append(name.lower())
    return tags
