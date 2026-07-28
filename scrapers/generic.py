"""
Generic scraper for venue / promoter "what's on" listing pages.

Design note: these sites are built on a handful of different platforms
(WordPress event plugins for the Century Venues / Playbill venues,
Webflow for Destroy All Lines, something custom for Qudos/Afterpay).
Rather than hand-write a brittle CSS selector per site, this scraper
looks for the one thing they all reliably have in common: a link whose
href matches the source's event_link_pattern (e.g. "/event/" or
"/tours/"). It then walks up/backwards through the DOM to find the
nearest heading-like text to use as the event title.

This is deliberately resilient-but-approximate. The first time you run
this against a real source, sanity-check a few titles against the live
page — if a site's markup doesn't put a heading near the event link,
you'll need to add a small custom parser for that one source (see
qudos_arena() below for an example of a source-specific override).
"""

import re
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


def is_pagination_link(href: str) -> bool:
    """True if href looks like a paginator link rather than a real event."""
    return bool(PAGINATION_RE.search(href))


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


def scrape_listing_page(url: str, event_link_pattern: str, source_name: str) -> list[dict]:
    """
    Fetch a listing page and return a list of {title, url, source} dicts,
    one per distinct event link found.
    """
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    seen_urls = set()
    events = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if event_link_pattern not in href:
            continue
        if is_pagination_link(href):
            continue

        # Normalize to absolute-ish key for dedup within this page
        if href in seen_urls:
            continue
        seen_urls.add(href)

        title = (
            nearest_heading_text(a, event_link_pattern)
            or a.get_text(strip=True)
            or slug_to_title(href)
        )

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
