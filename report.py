"""
Renders scraped + classified events into a single static HTML page so
you can eyeball scrape quality and matching accuracy before anything
posts to Threads.
"""

import html
from datetime import datetime

REASON_LABELS = {
    "venue": "Venue match",
    "artist": "Artist match",
    "genre": "Genre match",
    None: "No match (filtered out)",
}

REASON_COLORS = {
    "venue": "#2f7d4f",
    "artist": "#c0392b",
    "genre": "#2e6da4",
    None: "#999999",
}


def _event_row(event: dict) -> str:
    reason = event.get("match_reason")
    label = REASON_LABELS.get(reason, reason)
    color = REASON_COLORS.get(reason, "#999999")
    extra = ""
    if event.get("matched_artist"):
        extra = f" — matched artist: {html.escape(event['matched_artist'])}"
    elif event.get("matched_genre"):
        extra = f" — matched genre: {html.escape(event['matched_genre'])}"

    return f"""
    <div class="event">
      <span class="tag" style="background:{color}">{html.escape(label)}</span>
      <a href="{html.escape(event['url'])}" target="_blank">{html.escape(event['title'])}</a>
      <div class="meta">{html.escape(event['source'])}{extra}</div>
    </div>
    """


def render_report(classified_events: list[dict], path: str = "preview.html") -> None:
    matched = [e for e in classified_events if e.get("match_reason")]
    unmatched = [e for e in classified_events if not e.get("match_reason")]

    matched_html = "\n".join(_event_row(e) for e in matched) or "<p>No matches found.</p>"
    unmatched_html = "\n".join(_event_row(e) for e in unmatched) or "<p>Nothing filtered out.</p>"

    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MetalRadr preview</title>
<style>
  body {{ font-family: -apple-system, Helvetica, Arial, sans-serif; max-width: 720px;
         margin: 40px auto; padding: 0 16px; color: #1a1a1a; background: #fafafa; }}
  h1 {{ font-size: 1.4rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
  .generated {{ color: #777; font-size: 0.85rem; margin-bottom: 1.5rem; }}
  .event {{ background: white; border: 1px solid #e5e5e5; border-radius: 8px;
            padding: 12px 14px; margin-bottom: 10px; }}
  .event a {{ font-weight: 600; text-decoration: none; color: #111; display: block; margin-top: 4px; }}
  .event a:hover {{ text-decoration: underline; }}
  .tag {{ color: white; font-size: 0.7rem; padding: 2px 8px; border-radius: 999px; }}
  .meta {{ color: #666; font-size: 0.8rem; margin-top: 4px; }}
</style>
</head>
<body>
  <h1>MetalRadr — preview run</h1>
  <div class="generated">Generated {generated_at} · not posted anywhere, this is a dry run</div>

  <h2>Would alert on Threads ({len(matched)})</h2>
  {matched_html}

  <h2>Filtered out ({len(unmatched)})</h2>
  {unmatched_html}
</body>
</html>
"""
    with open(path, "w") as f:
        f.write(page)
