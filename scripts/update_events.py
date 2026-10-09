"""Upcoming One Piece Card Game events near home (Bandai TCG+) and new Premium Bandai drops.

- data/alerts.json is the settings file: home location, search radius, which kinds of
  event are worth a notification, and who to mention.
- data/events.json keeps upcoming events within the radius, one per line.
- data/drops.json keeps One Piece products seen on Premium Bandai USA, one per line.
- Anything seen for the first time, of a kind worth a notification, is written to
  the file named by --notify (Markdown), which the workflow posts as a GitHub issue,
  and to --discord (one webhook message per line) when a Discord webhook is set up.

Usage: python3 scripts/update_events.py [--dry-run] [--notify PATH] [--discord PATH] [--test-home LAT,LNG]
"""
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urljoin

from common import DATA, dump_rows, read_json, write_text
import signups

TCG_API = "https://api.bandai-tcg-plus.com/api/user/event/list"
TCG_EVENT = "https://www.bandai-tcg-plus.com/event/{}"
ONE_PIECE = 4  # Bandai TCG+ game_title_id
PB = "https://p-bandai.com/us"
OFFICIAL = "https://en.onepiece-cardgame.com"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
PAGE = 100
MAX_EVENTS = 3000
REMIND_AHEAD = timedelta(hours=2)  # the job runs hourly, so reminders land 1 to 2 hours ahead

# Event kinds, matched against the event series title in this order.
KINDS = [
    ("Store Championship", re.compile(r"store champ", re.I)),
    ("Treasure Cup", re.compile(r"treasure cup", re.I)),
    ("Prerelease", re.compile(r"pre-?release", re.I)),
    ("Regionals", re.compile(r"regional|national|championship|finals", re.I)),
    ("Release Event", re.compile(r"release event|anniversary|launch", re.I)),
    ("Extra Battle", re.compile(r"extra (?:grand )?battle", re.I)),
    ("Pirates Party", re.compile(r"pirates party", re.I)),
    ("Store Tournament", re.compile(r"store tournament|standard battle", re.I)),
]


def kind_of(title):
    for name, pattern in KINDS:
        if pattern.search(title or ""):
            return name
    return "Other"


def fetch(url, tries=3, timeout=90):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def miles(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return round(7917.6 * math.asin(math.sqrt(a)), 1)


# ---------- Bandai TCG+ ----------

def event_row(e, home):
    geo = e.get("place_geo") or e.get("event_place_geo") or {}
    lat, lng = geo.get("x"), geo.get("y")
    fee = e.get("entryFee")
    try:
        fee = float(fee)
        fee = int(fee) if fee == int(fee) else fee
    except (TypeError, ValueError):
        fee = None
    row = {
        "id": e["id"],
        "kind": kind_of(e.get("event_series_title")),
        "title": (e.get("event_series_title") or "").strip(),
        "store": (e.get("organizer_name") or "").strip(),
        "address": ", ".join(x for x in [(e.get("street_address") or "").strip(), (e.get("city_code") or "").strip().title(),
                                          (e.get("pref_code") or "").replace("US-", "")] if x),
        "start": e.get("start_datetime"),
        "tz": e.get("timezone"),
        "opens": e.get("apply_start_datetime"),
        "fee": fee,
        "cap": e.get("max_join_count"),
        "lat": lat, "lng": lng,
    }
    if home and lat is not None and lng is not None:
        row["miles"] = miles(home["lat"], home["lng"], lat, lng)
    for key, field in (("storeUrl", "organizer_url"), ("storeSns", "organizer_sns_url")):
        if (e.get(field) or "").startswith("http"):
            row[key] = e[field].strip()
    if e.get("is_canceled"):
        row["canceled"] = True
    if e.get("is_over_max_join_count"):
        row["full"] = True
    return row


def fetch_events(cfg, today):
    home = cfg.get("home") or {}
    if home.get("lat") is None or home.get("lng") is None:
        print("No home location in data/alerts.json; skipping Bandai TCG+.")
        return None, home
    params = [("game_title_id", ONE_PIECE), ("limit", PAGE), ("start_date", today),
              ("current_lat", home["lat"]), ("current_lng", home["lng"]), ("distance", cfg.get("radiusMiles", 50)),
              ("favorite", 0), ("application_open_flg", 0), ("order", 1)]
    params += [("country_code[]", c) for c in cfg.get("countries", ["US"])]
    events, offset = [], 0
    while offset < MAX_EVENTS:
        url = TCG_API + "?" + urllib.parse.urlencode(params + [("offset", offset)])
        body = json.loads(fetch(url))["success"]
        page = body.get("event_list") or []
        events += page
        print(f"Bandai TCG+: {len(events)} of {body.get('total')} events")
        if len(page) < PAGE:
            break
        offset += PAGE
    radius = cfg.get("radiusMiles", 50)
    rows = {}
    for e in events:
        r = event_row(e, home)
        if r.get("miles") is not None and r["miles"] > radius * 1.05:
            continue  # the API's distance filter is approximate
        rows[r["id"]] = r
    return rows, home


# ---------- Products and official announcements ----------
# Premium Bandai's item pages and search sit behind a bot check, so card game drops come
# from the official card game site's product list, which tags Premium Bandai exclusives,
# plus the featured items on Premium Bandai's own One Piece page.

def clean(html):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html or ""))).strip()


def fetch_products(pages=2):
    rows = {}
    for page in range(1, pages + 1):
        html = fetch(f"{OFFICIAL}/products/?page={page}")
        for box in re.findall(r'<li class="linkListColBox"[^>]*>(.*?)</li>', html, re.S):
            href = re.search(r'href="([^"]+)"', box)
            title = re.search(r'linkListColTitle">(.*?)</h4>', box, re.S)
            if not href or not title:
                continue
            url = urljoin(OFFICIAL + "/", href.group(1))
            pid = re.sub(r"\.html?$", "", url.rstrip("/").rsplit("/", 1)[-1])
            img = re.search(r'data-src="([^"?]+)', box)
            price = re.search(r'linkListColPrice">.*?class="data">(.*?)</span>', box, re.S)
            tags = [clean(t) for t in re.findall(r'linkListColTag">(.*?)</span>', box, re.S)]
            cat = re.search(r'linkListColCat">(.*?)</span>', box, re.S)
            rows["cg:" + pid] = {
                "id": "cg:" + pid, "name": clean(title.group(1)), "url": url,
                "category": clean(cat.group(1)).title() if cat else None,
                "price": clean(price.group(1)) if price else None,
                "premiumBandai": any("PREMIUM BANDAI" in t.upper() for t in tags),
                "image": urljoin(OFFICIAL + "/", img.group(1)) if img else None,
            }
    return rows


def fetch_pbandai_featured():
    rows = {}
    html = fetch(f"{PB}/series/onepiece-series")
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for item in (data.get("mainEntity") or {}).get("itemListElement") or []:
            m = re.search(r"/item/([A-Z0-9]+)", item.get("url") or "")
            if m:
                rows["pb:" + m.group(1)] = {"id": "pb:" + m.group(1), "name": item.get("name") or m.group(1), "url": item["url"],
                                            "category": "Premium Bandai", "premiumBandai": True}
    return rows


def fetch_drops():
    rows = {}
    for name, fn in [("official product list", fetch_products), ("Premium Bandai One Piece page", fetch_pbandai_featured)]:
        try:
            found = fn()
            print(f"{name}: {len(found)} items")
            rows.update(found)
        except Exception as e:
            print(f"{name} failed: {e}")
            return None  # don't mark items as gone because one source was down
    for r in rows.values():
        for k in [k for k, v in r.items() if v is None]:
            del r[k]
    return rows


def fetch_announcements():
    """Official event pages (Treasure Cup, Store Championship, Regionals, ...) on the card game site."""
    html = fetch(f"{OFFICIAL}/events/")
    rows = {}
    for box in re.findall(r'<li class="eventsColBox"[^>]*>(.*?)</li>', html, re.S):
        href = re.search(r'href="([^"]+)"', box)
        title = re.search(r'linkCardTitle">\s*<h4>(.*?)</h4>', box, re.S)
        if not href or not title:
            continue
        url = urljoin(OFFICIAL + "/", href.group(1))
        when = re.search(r'linkCardDate">(.*?)</p>', box, re.S)
        rows[url] = {"id": url, "name": clean(title.group(1)).replace("\u200b", ""), "url": url,
                     "tags": [clean(t) for t in re.findall(r'class="type">(.*?)</span>', box, re.S)],
                     "when": clean(when.group(1)).replace("Event Period:", "").replace("\u200b", "").strip() if when else ""}
    print(f"Official events page: {len(rows)} announcements")
    return rows


# ---------- Notification ----------

def when(e):
    try:
        return datetime.fromisoformat(e["start"]).strftime("%a %b %-d, %-I:%M %p")
    except (TypeError, ValueError):
        return e.get("start") or "?"


def opens_text(e):
    try:
        opens = datetime.fromisoformat(e["opens"])
    except (TypeError, ValueError, KeyError):
        return ""
    if opens <= datetime.now(timezone.utc):
        return "Open now"
    return opens.strftime("%b %-d, %H:%M UTC")


def discord_opens(e):
    """Registration time as a Discord timestamp, shown in the reader's time zone with a countdown."""
    try:
        opens = datetime.fromisoformat(e["opens"])
    except (TypeError, ValueError, KeyError):
        return ""
    if opens <= datetime.now(timezone.utc):
        return "Open now"
    t = int(opens.timestamp())
    return f"Opens <t:{t}:f> (<t:{t}:R>)"


def due_reminders(events, notify_kinds, now):
    """Events whose registration opens within REMIND_AHEAD and haven't had a reminder yet."""
    due = []
    for e in events.values():
        try:
            opens = datetime.fromisoformat(e["opens"])
        except (TypeError, ValueError, KeyError):
            continue
        if (e["kind"] in notify_kinds and not e.get("canceled") and not e.get("reminded")
                and now < opens <= now + REMIND_AHEAD):
            e["reminded"] = True
            due.append(e)
    return due


def notification(new_events, new_news, new_drops, cfg):
    lines = []
    if new_events:
        lines.append(f"### New tournaments within {cfg.get('radiusMiles', 50)} miles\n")
        lines.append("| When (local) | Event | Store | Miles | Fee | Registration |")
        lines.append("|---|---|---|---|---|---|")
        for e in sorted(new_events, key=lambda e: e.get("start") or ""):
            fee = "Free" if e.get("fee") == 0 else (f"${e['fee']}" if e.get("fee") is not None else "")
            lines.append(f"| {when(e)} | [{e['kind']}]({TCG_EVENT.format(e['id'])}) {e['title']} | {e['store']}<br>{e['address']} "
                         f"| {e.get('miles', '')} | {fee} | {opens_text(e)} |")
        lines.append("")
    if new_news:
        lines.append("### New official event announcements\n")
        for a in new_news:
            lines.append(f"- [{a['name']}]({a['url']})" + (f": {a['when']}" if a.get("when") else ""))
        lines.append("")
    if new_drops:
        lines.append("### New products\n")
        for d in new_drops:
            extra = ", ".join(x for x in ["Premium Bandai" if d.get("premiumBandai") else "", d.get("price", "")] if x)
            lines.append(f"- [{d['name']}]({d['url']})" + (f" ({extra})" if extra else ""))
        lines.append("")
    mention = " ".join("@" + u for u in cfg.get("mention", []))
    lines.append(f"Everything is on the [Events tab](https://reidsord.github.io/optcg/#events). {mention}".strip())
    return "\n".join(lines) + "\n"


def discord_payloads(new_events, new_news, new_drops, reminders=(), signup_embeds=()):
    """Discord webhook messages: one embed per item, at most 10 embeds per message."""
    embeds = list(signup_embeds)
    for e in sorted(reminders, key=lambda e: e["opens"]):
        t = int(datetime.fromisoformat(e["opens"]).timestamp())
        embeds.append({"title": f"Registration opening soon: {e['kind']} at {e['store']}"[:256], "url": TCG_EVENT.format(e["id"]),
                       "description": f"**Opens <t:{t}:f> (<t:{t}:R>)**\n{e['title']}, {when(e)}\n{e['address']}"[:4000], "color": 0xF2B705})
    for e in sorted(new_events, key=lambda e: e.get("start") or ""):
        fee = "Free" if e.get("fee") == 0 else (f"${e['fee']}" if e.get("fee") is not None else None)
        fields = [{"name": "When", "value": when(e), "inline": True}]
        if e.get("miles") is not None:
            fields.append({"name": "Distance", "value": f"{e['miles']} mi", "inline": True})
        if fee:
            fields.append({"name": "Fee", "value": fee, "inline": True})
        if opens_text(e):
            fields.append({"name": "Registration", "value": discord_opens(e), "inline": True})
        embeds.append({"title": f"{e['kind']}: {e['store']}"[:256], "url": TCG_EVENT.format(e["id"]),
                       "description": f"{e['title']}\n{e['address']}"[:4000], "color": 0xD93F0B, "fields": fields})
    for a in new_news:
        embeds.append({"title": a["name"][:256], "url": a["url"], "description": a.get("when") or "Official announcement",
                       "color": 0x1F8A64})
    for d in new_drops:
        embed = {"title": d["name"][:256], "url": d["url"], "color": 0xB0306A if d.get("premiumBandai") else 0x5865F2,
                 "description": " · ".join(x for x in ["Premium Bandai" if d.get("premiumBandai") else d.get("category", ""), d.get("price", "")] if x) or "New product"}
        if d.get("image"):
            embed["thumbnail"] = {"url": d["image"]}
        embeds.append(embed)
    content = "Sign-up news" if signup_embeds and not (new_events or new_news or new_drops or reminders) else \
        "Registration opens soon" if reminders and not (new_events or new_news or new_drops) else "New on the [Events tab](https://reidsord.github.io/optcg/#events)"
    return [{"username": "OPTCG alerts", "content": content if i == 0 else None,
             "embeds": embeds[i:i + 10], "allowed_mentions": {"parse": []}} for i in range(0, len(embeds), 10)]


def squash(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def test_discord(query, path):
    """Write a Discord test message for live events (and products) matching every word of `query`."""
    cfg = read_json(f"{DATA}/alerts.json", {})
    words = [squash(w) for w in query.split() if squash(w)]
    match = lambda *texts: all(w in squash(" ".join(t or "" for t in texts)) for w in words)
    events, _ = fetch_events(cfg, datetime.now(timezone.utc).date().isoformat())
    hits = [e for e in (events or {}).values() if match(e["kind"], e["title"]) and not e.get("canceled")]
    drops = read_json(f"{DATA}/drops.json", {}).get("items", [])
    products = [d for d in drops if any(w in squash(d["name"]) for w in words if not w.isalpha())][:1]
    print(f"Test '{query}': {len(hits)} events, {len(products)} products")
    payloads = discord_payloads(hits[:9], [], products)
    note = (f"Test alert for \"{query}\": {len(hits)} matching event{'s' if len(hits) != 1 else ''} within {cfg.get('radiusMiles', 50)} miles"
            + ("." if hits else " so far, so this shows the matching product instead. Real alerts post when events go live."))
    if not payloads:
        payloads = [{"username": "OPTCG alerts", "embeds": [], "allowed_mentions": {"parse": []}}]
    payloads[0]["content"] = note
    with open(path, "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False) + "\n")


def merge_seen(found, old, today):
    """Carry first-seen dates over; return the items not seen before."""
    new = []
    for key, item in found.items():
        prev = old.get(key)
        item["seen"] = prev["seen"] if prev else today
        if not prev:
            new.append(item)
    return new


def main(dry_run=False, notify_path=None, test_home=None, discord_path=None):
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    cfg = read_json(f"{DATA}/alerts.json", {})
    if test_home:
        lat, lng = (float(x) for x in test_home.split(","))
        cfg["home"] = {"lat": lat, "lng": lng, "label": "test"}
    notify_kinds = set(cfg.get("notifyKinds", []))
    radius = cfg.get("radiusMiles", 50)

    old = read_json(f"{DATA}/events.json", {})
    old_events = {e["id"]: e for e in old.get("events", [])}
    old_news = {a["id"]: a for a in old.get("announcements", [])}
    old_search = old.get("search") or {}
    old_drops = {d["id"]: d for d in read_json(f"{DATA}/drops.json", {}).get("items", [])}
    old_watch = read_json(f"{DATA}/watch.json", {})
    quick = lambda url: fetch(url, tries=1, timeout=25)

    # Local tournaments. A changed home or radius means a fresh list, not a flood of alerts.
    try:
        events, home = fetch_events(cfg, today)
    except Exception as e:  # keep going so a Bandai TCG+ outage doesn't block the rest
        print(f"Bandai TCG+ failed: {e}")
        events, home = None, cfg.get("home") or {}
    search = {"home": home.get("label") or home.get("zip"), "radiusMiles": radius}
    new_events = []
    if events is None:
        events = old_events
    else:
        fresh_search = search != old_search
        new_events = [e for e in merge_seen(events, old_events, today)
                      if not fresh_search and e["kind"] in notify_kinds and not e.get("canceled")]
        # Keep events the search stops returning (e.g. registration closed) until they are past.
        cutoff = (now - timedelta(days=1)).date().isoformat()
        for eid, prev in old_events.items():
            if eid not in events and (prev.get("start") or "") >= cutoff and not fresh_search:
                events[eid] = prev

    for eid, e in events.items():  # remember which events already had a registration reminder
        if old_events.get(eid, {}).get("reminded"):
            e["reminded"] = True
    reminders = due_reminders(events, notify_kinds, now) if search == old_search else []

    # Sign-up early warning: when series went live, official event pages, store websites.
    old_official = {r["id"]: r for r in old_watch.get("official", [])}
    old_stores = {r["id"]: r for r in old_watch.get("stores", [])}
    series = signups.update_series(events, {r["id"]: r for r in old_watch.get("series", [])}, today)
    pattern = signups.drop_pattern(series, list(dict.fromkeys(e["kind"] for e in events.values())))
    official, official_alerts = old_official, []

    try:
        news = fetch_announcements()
        new_news = merge_seen(news, old_news, today)
        new_news = new_news if old_news else []  # first run: fill the list without alerts
        official, official_alerts = signups.watch_official(news, old_official, quick, now)
    except Exception as e:
        print(f"Official events page failed: {e}")
        news, new_news = old_news, []
    stores, store_alerts = signups.watch_stores(events, old_stores, quick)
    signup_alerts = official_alerts + store_alerts

    drops = fetch_drops()
    new_drops = []
    if drops is None:
        drops = old_drops
    else:
        new_drops = merge_seen(drops, old_drops, today)
        new_drops = new_drops if old_drops else []
        for pid, prev in old_drops.items():  # products fall off the first pages; keep them as history
            drops.setdefault(pid, prev)
    sets = signups.release_dates(drops, {r["id"]: r for r in old_watch.get("sets", [])}, quick, today)
    signup_alerts += signups.predict_drops(sets, series, pattern, now)

    if not dry_run:
        ev_rows = sorted(events.values(), key=lambda e: (e.get("start") or "", e["id"]))
        news_rows = sorted(news.values(), key=lambda a: (a["seen"], a["id"]), reverse=True)
        text = ('{"source":"Bandai TCG+","search":' + json.dumps(search, ensure_ascii=False)
                + ',\n"announcements":' + dump_rows(news_rows).rstrip("\n")
                + ',\n"events":' + dump_rows(ev_rows).rstrip("\n") + "}\n")
        if write_text(f"{DATA}/events.json", text):
            print(f"Wrote {len(ev_rows)} events and {len(news_rows)} announcements.")
        drop_rows = sorted(drops.values(), key=lambda d: (d["seen"], d["id"]), reverse=True)
        if write_text(f"{DATA}/drops.json", '{"items":' + dump_rows(drop_rows).rstrip("\n") + "}\n"):
            print(f"Wrote {len(drop_rows)} products.")
        watch = ('{"pattern":' + json.dumps(pattern, ensure_ascii=False)
                 + ',\n"sets":' + dump_rows(sorted(sets.values(), key=lambda r: r.get("release") or "", reverse=True)).rstrip("\n")
                 + ',\n"series":' + dump_rows(sorted(series.values(), key=lambda r: r.get("drop") or "", reverse=True)).rstrip("\n")
                 + ',\n"official":' + dump_rows(sorted(official.values(), key=lambda r: r["id"])).rstrip("\n")
                 + ',\n"stores":' + dump_rows(sorted(stores.values(), key=lambda r: (r.get("miles") or 999, r["id"]))).rstrip("\n") + "}\n")
        if write_text(f"{DATA}/watch.json", watch):
            print(f"Wrote {len(series)} series, {len(official)} official pages, {len(stores)} store sites.")

    print(f"New worth a notification: {len(new_events)} events, {len(new_news)} announcements, {len(new_drops)} products, "
          f"{len(reminders)} registration reminders, {len(signup_alerts)} sign-up news.")
    if notify_path and (new_events or new_news or new_drops or signup_alerts):
        parts = []
        if signup_alerts:
            parts.append("Sign-up news")
        if new_events:
            parts.append(f"{len(new_events)} new tournament{'s' if len(new_events) > 1 else ''} nearby")
        if new_news:
            parts.append(f"{len(new_news)} event announcement{'s' if len(new_news) > 1 else ''}")
        if new_drops:
            parts.append(f"{len(new_drops)} new product{'s' if len(new_drops) > 1 else ''}")
        with open(notify_path, "w", encoding="utf-8") as f:
            f.write(", ".join(parts) + "\n")
            f.write(signups.alert_markdown(signup_alerts, pattern))
            f.write(notification(new_events, new_news, new_drops, cfg))
    if discord_path and (new_events or new_news or new_drops or reminders or signup_alerts):
        with open(discord_path, "w", encoding="utf-8") as f:
            for payload in discord_payloads(new_events, new_news, new_drops, reminders, signups.alert_embeds(signup_alerts, pattern)):
                f.write(json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False) + "\n")
    if dry_run:
        print("Discord sample:", json.dumps(discord_payloads(sorted(events.values(), key=lambda e: e.get("start") or "")[:2], list(news.values())[:1], list(drops.values())[:1]))[:1500])
        sample = sorted(events.values(), key=lambda e: e.get("start") or "")
        print(notification([e for e in sample if e["kind"] in notify_kinds][:8], list(news.values())[:5], list(drops.values())[:8], cfg))
        kinds = {}
        for e in events.values():
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        print("Event kinds:", kinds)
        print("Sets:", sets)
        print("Prediction alerts:", [a for a in signup_alerts if a["source"] == "Prediction"])
        print("Drop pattern:", pattern, signups.pattern_text(pattern, "Prerelease"))
        print("Series:", sorted((r.get("drop"), r["id"]) for r in series.values())[-15:])
        print("Official sign-up lines:", {r["name"]: r["lines"] for r in official.values() if r["lines"]})
        print("Store sites:", [(r["id"], r.get("error") or len(r["snippets"])) for r in stores.values()])
        print("Store prerelease mentions:", {r["id"]: r["snippets"][:3] for r in stores.values() if r["snippets"]})
        print("Sample sign-up alert:", json.dumps(signups.alert_embeds([{"source": r["id"], "title": r["id"], "url": r["url"], "lines": r["snippets"][:2]} for r in stores.values() if r["snippets"]][:1], pattern))[:800])
        print("Titles by kind:", sorted({(e["kind"], e["title"]) for e in events.values()})[:80])


if __name__ == "__main__":
    args = sys.argv[1:]
    path = args[args.index("--notify") + 1] if "--notify" in args else None
    home = args[args.index("--test-home") + 1] if "--test-home" in args else None
    discord = args[args.index("--discord") + 1] if "--discord" in args else None
    if "--test-discord" in args:
        test_discord(args[args.index("--test-discord") + 1], discord or "discord.jsonl")
        sys.exit(0)
    main(dry_run="--dry-run" in args, notify_path=path, test_home=home, discord_path=discord)
