# MetalRadr

Personal alert system: watches 4 Sydney venues plus a couple of
rock/metal-leaning promoters, matches against your artist list and
genre net, and posts new show announcements to a dedicated Threads
account that you follow — so alerts land in your normal Threads feed
instead of a separate app.

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
   so the same artist run (multiple nights) only triggers one post,
   then posted to Threads.

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

### 1. Create the MetalRadr Threads account
Sign up for a new Threads account (e.g. `@metalradr`), then follow it
from your personal account so its posts show up in your feed.

### 2. Register a Meta developer app
- Go to https://developers.facebook.com/apps and create an app.
- Add the **Threads Use Case** to the app.
- Follow Meta's Threads API getting-started flow to authorize the app
  against the MetalRadr Threads account. This gives you a short-lived
  user access token.
- Exchange it for a **long-lived token** (valid ~60 days) using the
  token exchange endpoint documented at
  https://developers.facebook.com/docs/threads — you'll need to
  refresh this periodically (see "Token refresh" below).
- Note down your **Threads user ID** (also returned during
  authorization).

### 3. Add GitHub repo secrets
In your repo: Settings → Secrets and variables → Actions, add:
- `THREADS_ACCESS_TOKEN`
- `THREADS_USER_ID`

### 4. Edit `config.yaml`
- Add your must-see artists under `artists:`
- Adjust `genres:` if you want to broaden/narrow the net
- The 4 venues and Destroy All Lines are pre-filled; Handsome Tours is
  present but disabled (`enabled: false`) until its URL/structure is
  verified — flip it on once checked.

### 5. Test locally before relying on the daily cron
```bash
pip install -r requirements.txt
export THREADS_ACCESS_TOKEN=...
export THREADS_USER_ID=...
python main.py --seed   # snapshot everything on sale today, don't alert
python main.py --preview  # sanity-check what a real run would alert on
python main.py
```
Check the printed output for scrape warnings — if a site's markup has
changed or a selector doesn't pick up titles cleanly, you'll see it
here before it ever reaches Threads.

### 6. Turn on the schedule
Push to GitHub. The workflow runs daily automatically; you can also
trigger it manually from the Actions tab ("Run workflow") to test.

## Token refresh

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
