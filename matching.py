"""
Matching (which scraped events count as a hit) and dedup (collapse
back-to-back dates for the same artist into one alert) logic.
"""

import re
from datetime import datetime, timedelta

import musicbrainz_client

NOISE_WORDS = {
    "tickets", "ticket", "sold out", "soldout", "on sale", "onsale",
    "presale", "cancelled", "postponed", "rescheduled", "new date",
    "just announced", "announced",
}


def normalize_title(title: str) -> str:
    """Lowercase, strip common noise words/punctuation, collapse whitespace."""
    t = title.lower()
    for phrase in NOISE_WORDS:
        t = t.replace(phrase, "")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def matches_artist_list(event: dict, artists: list[str]) -> str | None:
    norm_title = normalize_title(event["title"])
    for artist in artists:
        if normalize_title(artist) in norm_title:
            return artist
    return None


def matches_genre(event: dict, genres: list[str]) -> str | None:
    """
    Checks the event title for genre keywords. If your scraper is later
    extended to also capture a source's own genre tags (Metro Theatre and
    Enmore Theatre both expose these), pass those in as extra text here too.
    """
    norm_title = normalize_title(event["title"])
    for genre in genres:
        if genre.lower() in norm_title:
            return genre
    return None


_AGE_RESTRICTION_SUFFIX_RE = re.compile(r"\s*\|\s*(18\+|all ages)\s*$", re.IGNORECASE)


def _artist_name_for_lookup(title: str) -> str:
    """
    Strip a trailing age-restriction suffix some venues append to the
    title (e.g. "PRESIDENT | ALL AGES", "ODD MOB | 18+") before using it
    as a MusicBrainz search query. This is venue metadata, not part of
    the artist's name, and leaving it in can throw off the search badly:
    "PRESIDENT | ALL AGES" top-matches a literal artist named "All Ages"
    and doesn't even return the real "PRESIDENT" band anywhere in the
    results, whereas the clean "PRESIDENT" query does.
    """
    return _AGE_RESTRICTION_SUFFIX_RE.sub("", title).strip()


def matches_genre_via_musicbrainz(event: dict, genres: list[str], genre_cache: dict) -> str | None:
    """
    Fallback for events matches_genre() (title-keyword matching) couldn't
    classify: look up the event's artist via MusicBrainz and check its
    tags against the configured genre net. This catches acts whose title
    is just their name with no genre word in it at all (e.g. "Avenged
    Sevenfold" doesn't contain "metal"), which title-keyword matching can
    never catch no matter how the genre list is tuned.

    genre_cache maps a lowercase artist name to its previously-fetched
    tag list and is mutated in place, so the same artist is only queried
    once across runs rather than every day — callers are responsible for
    persisting genre_cache back to state.json.
    """
    artist_name = _artist_name_for_lookup(event["title"].strip())
    cache_key = artist_name.lower()

    if cache_key in genre_cache:
        tags = genre_cache[cache_key]
    else:
        tags = musicbrainz_client.lookup_artist_tags(artist_name)
        if tags is None:
            # The request itself failed (network error) after retries —
            # don't cache that as "no genre info", or a transient blip
            # would permanently blacklist a real artist from ever
            # matching. Just skip a match this run; the next run will
            # retry the lookup fresh since nothing was cached.
            return None
        genre_cache[cache_key] = tags

    normalized_genres = {g.strip().lower() for g in genres}
    for tag in tags:
        if tag in normalized_genres:
            return tag
    return None


def classify(
    event: dict,
    artists: list[str],
    genres: list[str],
    venue_names: set[str],
    keyword_filter_venues: set[str] = frozenset(),
) -> dict:
    """
    Decide why (if at all) this event is worth alerting on.
    Venue-sourced events always count (any event at one of your 4 venues),
    except venues in keyword_filter_venues (config's keyword_filter_required)
    which mix in sports/family shows alongside gigs — those need an artist
    or genre match just like promoter sources do.
    """
    reason = None
    if event["source"] in venue_names and event["source"] not in keyword_filter_venues:
        reason = "venue"
    artist_hit = matches_artist_list(event, artists)
    if artist_hit:
        reason = "artist"
    genre_hit = None
    if reason is None:
        genre_hit = matches_genre(event, genres)
        if genre_hit:
            reason = "genre"

    event = dict(event)
    event["match_reason"] = reason
    event["matched_artist"] = artist_hit
    event["matched_genre"] = genre_hit
    return event


def dedup_key(event: dict) -> str:
    """
    Key used to group "the same artist run" together. Strips venue/date
    noise so 'Tame Impala - Night 1' and 'Tame Impala - Night 2' collapse.
    """
    norm = normalize_title(event["title"])
    # Drop trailing night/date-ish tokens like "night 1", "night 2", "day 2"
    norm = re.sub(r"\bnight \d+\b", "", norm)
    norm = re.sub(r"\bday \d+\b", "", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def seed_state(events: list[dict], state: dict) -> dict:
    """
    Mark every currently-scraped event URL as already-known, without
    recording any alerts. Used by `--seed` to snapshot "everything on sale
    today" so that a later run only flags genuinely new announcements
    (URLs that weren't part of this snapshot).
    """
    known_urls = set(state.get("known_urls", []))
    known_urls.update(e["url"] for e in events)
    return {
        "known_urls": sorted(known_urls),
        "alerts": dict(state.get("alerts", {})),
    }


def filter_new_events(events: list[dict], state: dict, dedup_window_days: int) -> tuple[list[dict], dict]:
    """
    Given today's scraped+classified events (matched and unmatched) and the
    persisted state dict, return (events_to_alert, updated_state).

    Two layers decide what actually gets alerted:
      1. Snapshot diff — an event URL already present in
         state["known_urls"] was already listed as of the last scrape/seed,
         so it's never "new", regardless of match_reason.
      2. Same-artist-run collapsing — even a genuinely new URL is skipped
         if we already alerted for the same dedup_key within
         dedup_window_days, so a newly announced multi-night run still only
         triggers one alert.

    state shape:
      {
        "known_urls": [...],
        "alerts": { dedup_key: {"last_alerted": "YYYY-MM-DD", "urls": [...]} }
      }
    """
    today = datetime.utcnow().date()
    known_urls = set(state.get("known_urls", []))
    alerts = {k: {**v, "urls": list(v["urls"])} for k, v in state.get("alerts", {}).items()}

    to_alert = []

    for event in events:
        if event["url"] in known_urls:
            continue
        if not event.get("match_reason"):
            continue

        key = dedup_key(event)
        prior = alerts.get(key)

        if prior:
            last_alerted = datetime.strptime(prior["last_alerted"], "%Y-%m-%d").date()
            if (today - last_alerted) <= timedelta(days=dedup_window_days):
                # Already alerted for this artist/run recently — skip,
                # but track the extra date's URL in case it's useful later.
                if event["url"] not in prior["urls"]:
                    prior["urls"].append(event["url"])
                continue

        to_alert.append(event)
        alerts[key] = {
            "last_alerted": today.isoformat(),
            "urls": [event["url"]],
        }

    # Every URL seen today (matched or not) is "known" from here on, so
    # tomorrow's diff only flags what's genuinely new.
    known_urls.update(e["url"] for e in events)

    updated_state = {
        "known_urls": sorted(known_urls),
        "alerts": alerts,
    }
    return to_alert, updated_state
