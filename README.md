# MetalRadr

Personal alert system: watches 5 Sydney venues plus a couple of
rock/metal-leaning promoters, matches against your artist list and
genre net, and sends new show announcements your way. Threads API
setup is currently on hold, so alerts default to a summary email; a
dedicated Threads account posting flow is built and ready to switch
back to once that's sorted (see "Alert channels" below).

## How it works

1. `main.py` runs once a day (via GitHub Actions cron), aiming for
   7am Sydney time. The workflow fires twice — 20:00 and 21:00 UTC —
   to cover 7am across both AEST and AEDT without needing manual cron
   edits at DST transitions. GitHub's scheduled firing is best-effort
   and can drift by hours under queue load (observed drifting from
   ~20min late up to ~8h late over a few consecutive days), so rather
   than gating on a fixed hour, `main.py` tracks whether a real check
   has already happened today (`last_real_run_date` in `state.json`,
   compared against the current Sydney date via `zoneinfo`) and
   no-ops any firing after the first one that actually runs that day
   — however late it ends up landing. This check only applies to
   real/seed runs — `--preview` always runs regardless of time of
   day. Pass `--force` to bypass the gate for a manual real run or
   `--seed` on demand (the daily cron never needs this). The GitHub
   Actions "Run workflow" button has a matching `force` checkbox for
   the same purpose when testing from the Actions tab.
2. It scrapes each venue/promoter's public listings page (no API, no
   login — just reading the public page, same as a browser would).
3. Every event is checked against:
   - **Venue match** — anything at your 5 venues counts, no filter
     needed, except venues with `keyword_filter_required: true` set
     (Afterpay Arena and Roundhouse, both of which mix in non-music
     content) — those need an artist or genre match just like
     promoter sources do.
   - **Artist match** — your named "must-see" list (`config.yaml`),
     matched anywhere.
   - **Genre match** — a broader keyword net (`config.yaml`), for
     promoter sources and keyword-filtered venues. Checked first as a
     literal keyword in the title (instant), then — only if that
     misses — via a MusicBrainz artist lookup (see "Genre matching via
     MusicBrainz" below), since most event titles are just an artist's
     name with no genre word in it at all (e.g. "Avenged Sevenfold").
4. Each event that passes the match filter gets one extra request to
   its own event page to pull the show's date (listing pages don't
   reliably show one) — see "Known rough edges" below for where this
   can come up empty.
5. Matches are filtered against `state.json`: only event URLs that
   weren't already in the last saved snapshot count as "new" (see
   "Snapshot diffing" below), and those new matches are further deduped
   so the same artist run (multiple nights) only triggers one alert
   (using the first night's date), then sent via the configured alert
   channel (see "Alert channels").

## Genre matching via MusicBrainz

Title-keyword genre matching only works when a genre word literally
appears in the event title — which almost never happens for listings
that are just an artist's name (e.g. "Evanescence" doesn't contain
"rock"). For any event that still has no match after venue/artist/
title-keyword checks, `matching.matches_genre_via_musicbrainz()`
looks the artist up via MusicBrainz's artist search
(`musicbrainz_client.lookup_artist_tags()`) and checks its tags
against the same `genres:` list in `config.yaml`.

- **No API key needed**, but MusicBrainz requires a descriptive
  User-Agent (set in `musicbrainz_client.py`) and enforces a strict
  **1 request/second** rate limit, both handled client-side.
- **Cached in `state.json`** under `artist_genre_cache` (lowercase
  artist name → its tag list, including an empty list for "no tags
  found" so that's cached too), so the same artist is only ever
  queried once, not re-queried every day. This cache is only persisted
  by real runs and `--seed` — `--preview` never touches `state.json`,
  so repeatedly previewing re-queries MusicBrainz for the same batch
  each time (this can take a couple of minutes, since a full scrape
  can have 100+ artists needing a lookup on a cold cache).
- The search endpoint's `inc=genres` param doesn't actually return a
  curated `genres` field (only a direct MBID lookup does) — it always
  returns `tags` instead, a broader community-tagged set that
  includes non-genre noise (e.g. "usa", "anthemic"). That's fine here:
  we only check membership against our own curated `genres:` list, so
  noise tags simply never match anything.
- Some real artists come back with no tags at all (MusicBrainz's tag
  data is crowdsourced and incomplete) — that's a genuine data gap,
  not a bug, and the event correctly falls back to no match rather
  than guessing.

## Alert channels

`main.py` supports two ways to deliver new-show alerts, chosen with
`--channel`:

- `email` (default) — sends **one digest email per run** listing every
  new match (title, date, venue/source, link) via Gmail SMTP. This is
  the active default while Threads API setup is on hold.
- `threads` — posts **one Threads post per new match** via the Threads
  API. Fully implemented, just needs the Meta app setup below before
  it'll work — pass `--channel threads` (or update `daily.yml`) once
  that's done.

Both channels read their credentials from environment variables, so
switching is just a flag change — nothing needs to be ripped out.

## Snapshot diffing

`state.json` tracks every event URL MetalRadr has ever seen
(`known_urls`), not just the ones it alerted on. A run only alerts on
URLs that are genuinely new since the last saved snapshot — currently
on-sale shows that were already listed yesterday don't get re-alerted
just because state.json didn't exist yet or got reset.

Before your first real daily run, seed the state so today's
already-on-sale shows aren't all treated as new announcements:
```bash
python main.py --seed
```
This scrapes everything currently listed and records it as
already-known, without posting or alerting on anything. From then on,
the daily run (and `--preview`) only surface event URLs that weren't
part of the last snapshot.

## One-time setup

### 1. Set up the Gmail sender
This is the active default (`--channel email`) while Threads is on hold.

- Turn on **2-Step Verification** on the Gmail account you want alerts
  to send *from* (a dedicated account works well, so you're not using
  your main account's app password) — Google Account → Security →
  2-Step Verification.
- Once 2-Step Verification is on, go to Google Account → Security →
  **App passwords**, create one for "Mail", and copy the 16-character
  password it gives you (spaces don't matter). This is
  `GMAIL_APP_PASSWORD` — it's not your normal Gmail password and
  can't be used to log in anywhere else.
- Decide where alerts should land (`ALERT_EMAIL`) — one address, or
  several comma-separated (e.g. `you@example.com, someone-else@example.com`)
  if more than one person wants alerts. Can be the same Gmail address
  you're sending from, or any other inbox(es) you actually check.

### 2. Add GitHub repo secrets
In your repo: Settings → Secrets and variables → Actions, add:
- `GMAIL_ADDRESS` — the Gmail address you're sending from
- `GMAIL_APP_PASSWORD` — the app password from step 1
- `ALERT_EMAIL` — where alerts should be sent; comma-separate multiple
  addresses in the same secret to add more recipients later (no code
  changes needed, just edit the secret)

### 3. Edit `config.yaml`
- Add your must-see artists under `artists:`
- Adjust `genres:` if you want to broaden/narrow the net
- The 5 venues and Destroy All Lines are pre-filled; Handsome Tours is
  present but disabled (`enabled: false`) until its URL/structure is
  verified — flip it on once checked.

### 4. Test locally before relying on the daily cron
```bash
pip install -r requirements.txt
export GMAIL_ADDRESS=...
export GMAIL_APP_PASSWORD=...
export ALERT_EMAIL="you@example.com, someone-else@example.com"  # comma-separate for multiple recipients
python main.py --seed   # snapshot everything on sale today, don't alert
python main.py --preview  # sanity-check what a real run would alert on
python main.py
```
Check the printed output for scrape warnings — if a site's markup has
changed or a selector doesn't pick up titles cleanly, you'll see it
here before it ever reaches your inbox.

### 5. Turn on the schedule
Push to GitHub. The workflow runs daily automatically; you can also
trigger it manually from the Actions tab ("Run workflow") to test.

## Switching to Threads later

The Threads posting path (`--channel threads`) is fully implemented in
`threads_client.py`, just waiting on Meta app setup:

1. Sign up for a new Threads account (e.g. `@metalradr`), then follow
   it from your personal account so its posts show up in your feed.
2. Register a Meta developer app at
   https://developers.facebook.com/apps and add the **Threads Use
   Case** to it.
3. Follow Meta's Threads API getting-started flow to authorize the app
   against the MetalRadr Threads account. This gives you a short-lived
   user access token.
4. Exchange it for a **long-lived token** (valid ~60 days) using the
   token exchange endpoint documented at
   https://developers.facebook.com/docs/threads — you'll need to
   refresh this periodically (see "Token refresh" below).
5. Note down your **Threads user ID** (also returned during
   authorization), and add `THREADS_ACCESS_TOKEN` and `THREADS_USER_ID`
   as GitHub repo secrets.
6. Pass `--channel threads` locally to test, then update the `run:`
   line in `.github/workflows/daily.yml` to do the same for the daily
   cron.

### Token refresh
Threads long-lived tokens last ~60 days and can be refreshed via the
API before they expire (they cannot be refreshed after expiry — you'd
need to re-authorize). Consider adding a second scheduled job that
refreshes the token monthly and updates the GitHub secret via the
GitHub API, or just calendar-remind yourself every ~45 days.

## Known rough edges (check these on first real run)

- **Selector resilience**: `scrapers/generic.py` finds event links by
  URL pattern and grabs the nearest heading as the title. This is
  robust to most WordPress/Webflow event listing layouts but hasn't
  been tested against live HTML — sanity-check the first day's output.
  When a site wraps the same event in more than one link (e.g. an
  image-only link before the text link — Roundhouse does this),
  `scrape_listing_page()` checks every occurrence of that href for a
  heading or non-empty link text before falling back to a slug-derived
  title, rather than giving up after the first (often empty) match.
- **Destroy All Lines title extraction**: currently pulls junk text
  (something like "touring nowpresale on nowsold out") instead of the
  actual artist name for every event on this source — a pre-existing
  bug, not something introduced by genre matching. Since the
  MusicBrainz lookup (and the title-keyword check before it) both key
  off `event["title"]`, neither can work correctly for this source
  until that extraction is fixed separately. In practice this means
  one wasted MusicBrainz query for that junk string (cached after the
  first, since it's identical across all Destroy All Lines events),
  and zero real genre matches from this source until it's fixed.
- **Afterpay Arena** (rebranded from Qudos Bank Arena —
  `qudosbankarena.com.au` now 301-redirects to `afterpayarena.com.au`):
  this page mixes concerts with sports and family shows, so
  `keyword_filter_required: true` makes `matching.classify()` require
  an artist or genre match for this venue specifically, same as
  promoter sources — a "venue match" alone isn't enough here like it
  is for the music-only venues.
- **Roundhouse** (UNSW/Arc's student union venue, not a Century Venues
  site — real event links are `/roundhouse/events/<slug>`, not
  `/event/`): a multi-purpose venue whose listing mixes gigs and DJ
  nights with non-music events like "Bingo Loco" (a party bingo game
  night), so `keyword_filter_required: true` is set here too, same as
  Afterpay Arena. Titles come through with age-restriction suffixes
  intact (e.g. "ODD MOB | 18+") since that's the site's actual link
  text — this occasionally affects MusicBrainz lookup accuracy (a
  fuzzy search can return a different "top result" for slightly
  different query strings), but stripping the suffix didn't reliably
  improve matches in testing, so it's left as-is rather than adding
  brittle title-cleanup heuristics.
- **Handsome Tours**: disabled by default until you confirm its actual
  tours page URL and that the generic scraper picks up titles cleanly.
- **Date extraction**: `extract_event_date()` tries, in order: (1) the
  schema.org Event JSON-LD `startDate` that the Century Venues
  WordPress sites (Metro/Enmore Theatre) embed on each event's own
  page, (2) a `<time datetime>` tag, (3) a "DATE" label followed by a
  "Weekday D Month YYYY" string (Afterpay Arena's event pages — a
  multi-night run compresses into one string there too, e.g. "Monday
  19, Tuesday 20 & Wednesday 21 October 2026", and only the first day
  is kept), (4) a `<p class="event-subtitle">` holding a "Weekday DD
  Mon" string with no year at all (Roundhouse) — the year is inferred
  as the nearest future occurrence of that month/day relative to
  today. A handful of Afterpay events don't fit even that — a
  relocated show with "Relocated" instead of a date, one missing its
  year, a season pass listing "2026/2027 Season" — these fall back to
  no date rather than guessing wrong. Destroy All Lines' free-text
  tour pages have no structured date at all. Either way the alert
  still goes out, just without a date — check `--preview` output
  ("date not found" in the meta line) if a source you expect to have
  dates doesn't.
