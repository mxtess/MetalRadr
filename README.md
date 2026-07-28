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
4. New matches are deduped against `state.json` so the same artist run
   (multiple nights) only triggers one post, then posted to Threads.

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
