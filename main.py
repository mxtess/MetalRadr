"""
MetalRadr — daily entry point.

Scrapes the configured venues + promoters, matches against your artist
list / genre net, dedups against state.json, sends new hits via the
configured --channel (email by default, threads once that's set up),
and saves updated state.

Run manually with:  python main.py
Runs automatically via .github/workflows/daily.yml
"""

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import yaml

from scrapers.generic import scrape_venue, scrape_promoter, extract_event_date
from matching import classify, filter_new_events, seed_state, matches_genre_via_musicbrainz
from threads_client import ThreadsClient, format_post
from email_client import EmailClient
from report import render_report


def load_config(path="config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(path: str, state: dict) -> None:
    with open(path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def sydney_now() -> datetime:
    return datetime.now(ZoneInfo("Australia/Sydney"))


def forget_event(state: dict, event: dict) -> None:
    """
    Undo bookkeeping for an event whose alert didn't actually go out, so
    it's retried on the next run instead of silently swallowed by the
    snapshot diff or the dedup window.
    """
    state["known_urls"] = [u for u in state["known_urls"] if u != event["url"]]
    key_to_remove = [k for k, v in state["alerts"].items() if event["url"] in v["urls"]]
    for k in key_to_remove:
        del state["alerts"][k]


def attach_genre_matches(classified_events: list[dict], genres: list[str], genre_cache: dict) -> None:
    """
    Fallback for events that still have no match_reason after classify()'s
    venue/artist/title-keyword checks: look up the artist via MusicBrainz
    (rate-limited, cached in genre_cache) and match its tags against the
    genre net. Only called for events that still need it, so this doesn't
    slow down anything that already matched via the cheap checks.
    """
    for event in classified_events:
        if event.get("match_reason"):
            continue
        matched = matches_genre_via_musicbrainz(event, genres, genre_cache)
        if matched:
            event["match_reason"] = "genre"
            event["matched_genre"] = matched


def attach_dates(classified_events: list[dict]) -> None:
    """
    Fetch each matched event's own page for its date (listing pages don't
    show one). Only called for events that passed the venue/artist/genre
    match filter, so this is one extra request per match rather than one
    per scraped event.
    """
    for event in classified_events:
        if event.get("match_reason"):
            event["date"] = extract_event_date(event["url"])


def scrape_all(config: dict) -> list[dict]:
    events = []
    for venue in config["venues"]:
        try:
            events.extend(scrape_venue(venue))
        except Exception as e:
            print(f"[warn] failed to scrape venue {venue['name']}: {e}", file=sys.stderr)

    for promoter in config["promoters"]:
        if promoter.get("enabled") is False:
            continue
        try:
            events.extend(scrape_promoter(promoter))
        except Exception as e:
            print(f"[warn] failed to scrape promoter {promoter['name']}: {e}", file=sys.stderr)

    return events


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--preview",
        action="store_true",
        help="Generate preview.html instead of posting to Threads. "
             "Does not touch state.json, so it's safe to run repeatedly "
             "while you're checking scrape/match quality. Shows only what "
             "would alert given the currently saved state.json snapshot.",
    )
    group.add_argument(
        "--seed",
        action="store_true",
        help="Scrape everything currently listed and record it in "
             "state.json as already-known, without alerting on any of it. "
             "Run this once before your first real daily run so today's "
             "already-on-sale shows aren't all treated as new announcements.",
    )
    parser.add_argument(
        "--channel",
        choices=["threads", "email"],
        default="email",
        help="Where to send new-show alerts. Defaults to email while "
             "Threads API setup is on hold; pass --channel threads to "
             "switch back once that's ready.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the Sydney 7am time gate. Useful for manually running "
             "a real run or --seed on demand without waiting for the "
             "scheduled window; the daily cron never needs this.",
    )
    args = parser.parse_args()

    if not args.preview and not args.force:
        # The workflow fires at both 20:00 and 21:00 UTC to cover 7am Sydney
        # across AEST/AEDT without needing manual cron changes at DST
        # transitions — only the one that actually lands at 7am should do
        # anything.
        now = sydney_now()
        if now.hour != 7:
            print(f"Skipping run — local time in Sydney is {now:%H:%M} "
                  f"({now.tzname()}), not 7am.")
            return

    config = load_config()
    state = load_state(config["state_file"])

    venue_names = {v["name"] for v in config["venues"]}
    keyword_filter_venues = {
        v["name"] for v in config["venues"] if v.get("keyword_filter_required")
    }
    genre_cache = dict(state.get("artist_genre_cache", {}))
    raw_events = scrape_all(config)

    if args.seed:
        updated_state = seed_state(raw_events, state)
        updated_state["artist_genre_cache"] = genre_cache
        save_state(config["state_file"], updated_state)
        print(f"Seeded state.json with {len(raw_events)} currently-listed events. "
              f"Nothing was posted or alerted; future runs will only alert on "
              f"event URLs not in this snapshot.")
        return

    classified = [
        classify(e, config["artists"], config["genres"], venue_names, keyword_filter_venues)
        for e in raw_events
    ]
    attach_genre_matches(classified, config["genres"], genre_cache)
    attach_dates(classified)

    if args.preview:
        to_alert, _ = filter_new_events(classified, state, config["dedup_window_days"])
        render_report(classified, to_alert, path="preview.html")
        print(f"Preview written to preview.html — {len(to_alert)} would-be alerts "
              f"out of {len(classified)} scraped events, compared against the "
              f"last saved state.json. Nothing was posted, nothing was saved "
              f"to state.json.")
        return

    to_alert, updated_state = filter_new_events(
        classified, state, config["dedup_window_days"]
    )
    updated_state["artist_genre_cache"] = genre_cache

    if not to_alert:
        print("No new matches today.")
        save_state(config["state_file"], updated_state)
        return

    if args.channel == "threads":
        client = ThreadsClient()
        for event in to_alert:
            post_body = format_post(event)
            try:
                post_id = client.post_text(post_body)
                print(f"Posted ({event['match_reason']}): {event['title']} -> {post_id}")
            except Exception as e:
                print(f"[error] failed to post '{event['title']}': {e}", file=sys.stderr)
                forget_event(updated_state, event)
    else:
        client = EmailClient()
        try:
            client.send_digest(to_alert)
            print(f"Emailed digest of {len(to_alert)} new show(s) to {client.to_addr}")
        except Exception as e:
            print(f"[error] failed to send alert email: {e}", file=sys.stderr)
            # The digest is a single send, so if it failed nothing in it
            # actually reached anyone — forget all of them so they're
            # retried tomorrow instead of silently dropped.
            for event in to_alert:
                forget_event(updated_state, event)

    save_state(config["state_file"], updated_state)


if __name__ == "__main__":
    main()
