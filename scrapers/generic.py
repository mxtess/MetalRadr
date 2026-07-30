"""
Generic scraper for venue / promoter "what's on" listing pages.

Design note: these sites are built on a handful of different platforms
(WordPress event plugins for the Century Venues / Playbill venues,
Webflow for Destroy All Lines, a WordPress theme with a custom event
template for Afterpay Arena). Rather than hand-write a brittle CSS
selector per site, this scraper looks for the one thing they all
reliably have in common: a link whose href matches the source's
event_link_pattern (e.g. "/event/" or "/tours/"). It then walks
up/backwards through the DOM to find the nearest heading-like text to
use as the event title.

This is deliberately resilient-but-approximate. The first time you run
this against a real source, sanity-check a few titles against the live
page — if a site's markup doesn't put a heading near the event link,
or its event_link_pattern turns out to also match a nav/listing page
(see GENERIC_SLUGS below), you'll need to adjust that source's config
or, if the site is structured too differently, write a small
source-specific parser instead of forcing it through this one.
"""

import json
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MetalRadr/1.0; personal use, +https://github.com/)"
}

# Pagination links (e.g. /event/page/2/, /tours/page/) aren't events.
PAGINATION_RE = re.compile(r"/page(/\d+)?/?(?:$|\?)", re.IGNORECASE)

# Nav/widget link text that sometimes ends up nearest an event link but
# doesn't name a specific event.
GENERIC_TITLES = {
    "more info", "info", "view all events", "events",
    "what's on", "whats on", "you may also be interested in",
}

# URL slugs that are nav/listing pages rather than a specific event, even
# when they happen to satisfy a source's event_link_pattern — e.g. Qudos's
# event_link_pattern "/event" also matches "/event-calendar", which is the
# calendar landing page, not a show.
GENERIC_SLUGS = {"event", "events", "event-calendar", "calendar", "upcoming-events"}


def is_pagination_link(href: str) -> bool:
    """True if href looks like a paginator link rather than a real event."""
    return bool(PAGINATION_RE.search(href))


def is_generic_nav_link(href: str) -> bool:
    """True if href's last path segment is a generic nav/listing slug, not a specific event."""
    path = href.split("?")[0].split("#")[0]
    slug = path.rstrip("/").split("/")[-1]
    return slug.lower() in GENERIC_SLUGS


def slug_to_title(href: str) -> str:
    """Fallback title derived from the URL slug, e.g. /event/lorna-shore/ -> 'Lorna Shore'."""
    slug = href.strip("/").split("/")[-1]
    slug = re.sub(r"[-_]+", " ", slug)
    return slug.title()


def nearest_heading_text(link_tag, event_link_pattern: str) -> str | None:
    """Look for a heading (h1-h4) inside the link's own event-card container.

    Walks up from the link only while the ancestor still represents a single
    event, i.e. contains just this one event link. Once an ancestor contains
    more than one link matching event_link_pattern, we've escaped into the
    shared listing wrapper — any heading found there could belong to a
    different card, so stop before that point instead of returning it.
    """
    parent = link_tag.parent
    depth = 0
    while parent is not None and depth < 4:
        matching_links = [
            a for a in parent.find_all("a", href=True)
            if event_link_pattern in a["href"]
        ]
        if len(matching_links) > 1:
            break
        heading = parent.find(["h1", "h2", "h3", "h4"])
        if heading:
            text = heading.get_text(strip=True)
            if text:
                return text
        parent = parent.parent
        depth += 1
    return None


def _parse_iso_date(value: str) -> str | None:
    """Parse an ISO 8601 datetime string into a short display date, e.g. 'Feb 14, 2027'."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return f"{dt:%b} {dt.day}, {dt.year}"


_MONTH_NAMES = (
    "January|February|March|April|May|June|"
    "July|August|September|October|November|December"
)
_TRAILING_MONTH_YEAR_RE = re.compile(rf"({_MONTH_NAMES})\s+(\d{{4}})\s*$")
_DAY_NUMBER_RE = re.compile(r"\b(\d{1,2})\b")


def _parse_display_date(text: str) -> str | None:
    """
    Parse "Weekday D Month YYYY" style display dates, e.g. Afterpay Arena's
    "Thursday 10 September 2026". Multi-night runs are compressed into one
    string there, e.g. "Monday 19, Tuesday 20 & Wednesday 21 October 2026"
    — only the first day is kept, matching the "one alert per run" rule
    applied to multi-listing runs elsewhere.
    """
    month_year_match = _TRAILING_MONTH_YEAR_RE.search(text)
    if not month_year_match:
        return None
    day_match = _DAY_NUMBER_RE.search(text)
    if not day_match:
        return None
    month_name, year = month_year_match.groups()
    try:
        dt = datetime.strptime(f"{day_match.group(1)} {month_name} {year}", "%d %B %Y")
    except ValueError:
        return None
    return f"{dt:%b} {dt.day}, {dt.year}"


_WEEKDAY_DAY_MONTH_RE = re.compile(
    r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(\d{1,2})\s+([A-Za-z]+)$"
)


def _parse_display_date_no_year(text: str) -> str | None:
    """
    Parse "Weekday DD Mon" style dates with no year at all, e.g.
    Roundhouse's "Sat 03 Oct". Infers the year as the nearest future
    occurrence of that month/day relative to today — these are always
    upcoming event listings, never past ones — so "05 Feb" seen in July
    resolves to next February, not the one that already passed.
    """
    match = _WEEKDAY_DAY_MONTH_RE.match(text.strip())
    if not match:
        return None
    day, month_abbr = match.groups()
    today = datetime.utcnow().date()
    for year_guess in (today.year, today.year + 1):
        try:
            candidate = datetime.strptime(f"{day} {month_abbr} {year_guess}", "%d %b %Y")
        except ValueError:
            continue
        if candidate.date() >= today:
            return f"{candidate:%b} {candidate.day}, {candidate.year}"
    return None


def extract_event_date(url: str) -> str | None:
    """
    Fetch a single event's own page and pull its date. Listing pages don't
    reliably show a date next to each event card, but individual event
    pages usually do, via one of (checked in order):
      1. A schema.org Event JSON-LD block with startDate (Century Venues'
         WordPress sites — Metro/Enmore Theatre).
      2. A <time datetime> tag.
      3. A "DATE" label (any heading tag) followed by a sibling holding a
         "Weekday D Month YYYY" string (Afterpay Arena).
      4. A <p class="event-subtitle"> holding a "Weekday DD Mon" string
         with no year at all (Roundhouse) — the year is inferred as the
         nearest future occurrence of that month/day.
    Returns None if none of these are found (e.g. Destroy All Lines' tour
    pages are free-text prose with no structured date), so callers should
    treat a missing date as expected, not an error.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if isinstance(entry, dict) and entry.get("@type") == "Event" and entry.get("startDate"):
                parsed = _parse_iso_date(entry["startDate"])
                if parsed:
                    return parsed

    time_tag = soup.find("time", datetime=True)
    if time_tag:
        parsed = _parse_iso_date(time_tag["datetime"])
        if parsed:
            return parsed

    date_label = soup.find(
        ["h1", "h2", "h3", "h4", "h5", "h6", "strong", "span", "dt"],
        string=lambda s: s and s.strip().upper() == "DATE",
    )
    if date_label:
        # The label itself may be wrapped in an inline tag (e.g. <h4><strong>
        # DATE</strong></h4>) — find_next_sibling on the label's own tag
        # would look inside <h4>, not after it, so walk up to the block-level
        # container the label's text actually belongs to first.
        container = date_label
        while container.parent is not None and container.name not in (
            "h1", "h2", "h3", "h4", "h5", "h6", "dt", "li", "div",
        ):
            container = container.parent
        value_tag = container.find_next_sibling()
        if value_tag:
            parsed = _parse_display_date(value_tag.get_text(" ", strip=True))
            if parsed:
                return parsed

    subtitle = soup.find(class_="event-subtitle")
    if subtitle:
        parsed = _parse_display_date_no_year(subtitle.get_text(" ", strip=True))
        if parsed:
            return parsed

    return None


def scrape_listing_page(url: str, event_link_pattern: str, source_name: str) -> list[dict]:
    """
    Fetch a listing page and return a list of {title, url, source} dicts,
    one per distinct event link found.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Group all matching <a> tags by href (in document order) rather than
    # just keeping the first one seen — some sites wrap the same event in
    # multiple links (e.g. an image-only link before the text link), and
    # picking only the first would lose a perfectly good title/heading
    # available on a later occurrence of the same href.
    tags_by_href: dict[str, list] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if event_link_pattern not in href:
            continue
        if is_pagination_link(href):
            continue
        if is_generic_nav_link(href):
            continue
        tags_by_href.setdefault(href, []).append(a)

    events = []
    for href, tags in tags_by_href.items():
        title = None
        for a in tags:
            title = nearest_heading_text(a, event_link_pattern)
            if title:
                break
        if not title:
            for a in tags:
                text = a.get_text(strip=True)
                if text:
                    title = text
                    break
        title = title or slug_to_title(href)

        # Skip obvious non-event nav/widget links (nav items, "view all", etc.)
        if title.strip().lower() in GENERIC_TITLES:
            continue

        events.append({
            "title": title,
            "url": href if href.startswith("http") else requests.compat.urljoin(url, href),
            "source": source_name,
        })

    return events


def scrape_venue(venue_config: dict) -> list[dict]:
    return scrape_listing_page(
        url=venue_config["url"],
        event_link_pattern=venue_config["event_link_pattern"],
        source_name=venue_config["name"],
    )


def scrape_promoter(promoter_config: dict) -> list[dict]:
    return scrape_listing_page(
        url=promoter_config["url"],
        event_link_pattern=promoter_config["event_link_pattern"],
        source_name=promoter_config["name"],
    )
