"""Discord scheduled events for player sign-ups found on official event pages.

Webhooks can't create events, so this uses a bot token (DISCORD_BOT_TOKEN) with the
Manage Events permission in the server named by DISCORD_GUILD_ID. Each official page
row in data/watch.json keeps the Discord event it made, so an event is created once
and moved if the sign-up date changes.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from signups import ET

API = "https://discord.com/api/v10"
HEADERS = {"Content-Type": "application/json", "User-Agent": "DiscordBot (https://github.com/reidsord/optcg, 1)"}


def event_body(row):
    """(start, body) of the scheduled event for a page's player sign-up time."""
    opens = datetime.fromisoformat(row["opens"])
    if row.get("hasTime"):
        start, end = opens, opens + timedelta(hours=1)
        note = "Be in the Bandai TCG+ app when sign-ups go live."
    else:  # the page gives a date only: run the event from 8 AM ET (seen drops land mid-morning) to the end of the day
        day = opens.astimezone(ET).date()
        start = datetime(day.year, day.month, day.day, 8, tzinfo=ET)
        end = start + timedelta(hours=15, minutes=59)
        note = "The official page gives a date but no time, so this runs from 8 AM ET through the day. Keep checking the Bandai TCG+ app."
    lines = "\n".join(row.get("lines") or [])
    return start, {
        "name": f"Sign-ups open: {row['name']}"[:100],
        "privacy_level": 2,
        "entity_type": 3,  # external
        "entity_metadata": {"location": row["id"][:100]},
        "scheduled_start_time": start.isoformat(),
        "scheduled_end_time": end.isoformat(),
        "description": f"{lines}\n\n{note}\n{row['id']}"[:1000],
    }


def call(method, path, token, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={**HEADERS, "Authorization": f"Bot {token}"})
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)) + 0.5)
                continue
            raise


def sync(official, token, guild, now, dry_run=False):
    """Create or move a Discord event for each upcoming player sign-up. Updates rows in place."""
    for row in official.values():
        if not row.get("opens"):
            continue
        start, body = event_body(row)
        if start <= now:
            continue  # Discord only takes events that start in the future
        made = row.get("discordEvent") or {}
        if made.get("opens") == row["opens"]:
            continue
        if dry_run or not (token and guild):
            print(f"Discord event {'to move' if made else 'to create'}: {body['name']} at {body['scheduled_start_time']}")
            continue
        try:
            try:
                ev = call("PATCH", f"/guilds/{guild}/scheduled-events/{made['id']}", token, body) if made else None
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
                ev = None  # deleted in Discord; make a new one for the new date
            ev = ev or call("POST", f"/guilds/{guild}/scheduled-events", token, body)
            row["discordEvent"] = {"id": ev["id"], "opens": row["opens"]}
            print(f"Discord event {'moved' if made else 'created'}: {body['name']}")
        except Exception as e:
            detail = e.read().decode("utf-8", "replace")[:300] if isinstance(e, urllib.error.HTTPError) else ""
            print(f"::warning::Couldn't save the Discord event for {row['name']}: {e} {detail}")
