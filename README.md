# MetalRadr

Personal alert system: watches 4 Sydney venues plus a couple of
rock/metal-leaning promoters, matches against your artist list and
genre net, and sends new show announcements your way. Threads API
setup is currently on hold, so alerts default to a summary email; a
dedicated Threads account posting flow is built and ready to switch
back to once that's sorted (see "Alert channels" below).

## How it works

1. `main.py` runs once a day (via GitHub Actions cron).
2. It scrapes each venue/promoter's public listings page (no API, no
   login — just reading the public page, same as a browser would).
3. Every event is checked against:
   - **Venue match** — anything at your 4 venues counts, no filter needed.
   - **Artist match** — your named "must-see" list (`config.yaml`),
     matched anywhere.
   - **Genre match** — a broader keyword net (`config.yaml`), for
     promoter sources that aren't tied to your 4 venues.
4. Matches are filtered against `state.json`: only event URLs that
   weren't already in the last saved snapshot count as "new" (see
   "Snapshot diffing" below), and those new matches are further deduped
   so the same artist run (multiple nights) only triggers one alert,
   then sent via the configured alert channel (see "Alert channels").

## Alert channels

`main.py` supports two ways to deliver new-show alerts, chosen with
`--channel`:

- `email` (default) — sends **one digest email per run** listing every
  new match (title, venue/source, link) via Gmail SMTP. This is the
  active default while Threads API setup is on hold.
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
- Decide where alerts should land (`ALERT_EMAIL`) — can be the same
  Gmail address, or any other inbox you actually check.

### 2. Add GitHub repo secrets
In your repo: Settings → Secrets and variables → Actions, add:
- `GMAIL_ADDRESS` — the Gmail address you're sending from
- `GMAIL_APP_PASSWORD` — the app password from step 1
- `ALERT_EMAIL` — the address alerts should be sent to

### 3. Edit `config.yaml`
- Add your must-see artists under `artists:`
- Adjust `genres:` if you want to broaden/narrow the net
- The 4 venues and Destroy All Lines are pre-filled; Handsome Tours is
  present but disabled (`enabled: false`) until its URL/structure is
  verified — flip it on once checked.

### 4. Test locally before relying on the daily cron
```bash
pip install -r requirements.txt
export GMAIL_ADDRESS=...
export GMAIL_APP_PASSWORD=...
export ALERT_EMAIL=...
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
- **Qudos/Afterpay Arena**: this page mixes concerts with sports and
  family shows, so `keyword_filter_required` is set for it — you may
  want stricter matching here than for the music-dedicated venues.
- **Handsome Tours**: disabled by default until you confirm its actual
  tours page URL and that the generic scraper picks up titles cleanly.
