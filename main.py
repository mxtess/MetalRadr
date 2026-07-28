"""
MetalRadr — daily entry point.

Scrapes the configured venues + promoters, matches against your artist
list / genre net, dedups against state.json, posts new hits to Threads,
and saves updated state.

Run manually with:  python main.py
Runs automatically via .github/workflows/daily.yml
"""

import argparse
import json
import sys
import yaml

from scrapers.generic import scrape_venue, scrape_promoter
from matching import classify, filter_new_events
from threads_client import ThreadsClient, format_post
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
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Generate preview.html instead of posting to Threads. "
             "Does not touch state.json, so it's safe to run repeatedly "
             "while you're checking scrape/match quality.",
    )
    args = parser.parse_args()

    config = load_config()
    state = load_state(config["state_file"])

    venue_names = {v["name"] for v in config["venues"]}
    raw_events = scrape_all(config)

    classified = [
        classify(e, config["artists"], config["genres"], venue_names)
        for e in raw_events
    ]

    if args.preview:
        render_report(classified, path="preview.html")
        matched_count = len([e for e in classified if e.get("match_reason")])
        print(f"Preview written to preview.html — {matched_count} would-be alerts "
              f"out of {len(classified)} scraped events. Nothing was posted, "
              f"nothing was saved to state.json.")
        return

    to_alert, updated_state = filter_new_events(
        classified, state, config["dedup_window_days"]
    )

    if not to_alert:
        print("No new matches today.")
        save_state(config["state_file"], updated_state)
        return

    client = ThreadsClient()
    for event in to_alert:
        post_body = format_post(event)
        try:
            post_id = client.post_text(post_body)
            print(f"Posted ({event['match_reason']}): {event['title']} -> {post_id}")
        except Exception as e:
            print(f"[error] failed to post '{event['title']}': {e}", file=sys.stderr)
            # Don't record it as alerted if the post failed, so it's retried tomorrow.
            key_to_remove = [k for k, v in updated_state.items() if event["url"] in v["urls"]]
            for k in key_to_remove:
                del updated_state[k]

    save_state(config["state_file"], updated_state)


if __name__ == "__main__":
    main()
