"""Early warning for Bandai TCG+ sign-ups.

Bandai TCG+ shows no event until its series goes live, and every store's events in a
series go live at the same moment. So the job looks for sign-up news elsewhere first:

- the official event pages, for lines about registration or entry dates;
- the websites of stores near home that host events, for new prerelease mentions;

and records when each series went live, so alerts can say when drops usually happen.
"""
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from html import unescape
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}|\d{1,2}/\d{1,2}"
SIGNUP_WORDS = re.compile(r"registration|register|entry|entries|apply|application|sign[- ]?up|lottery|tcg ?\+", re.I)
PRERELEASE = re.compile(r"[^.!?\n]{0,160}\bpre-?release\b[^.!?\n]{0,200}", re.I)
# Social sites need a login or block automated visits, so their pages can't be read.
UNREADABLE = ("facebook.com", "fb.com", "instagram.com", "x.com", "twitter.com", "discord.gg", "discord.com", "tiktok.com", "youtube.com")
MAX_SNIPPETS = 12
# Store search pages mix in other games and search boilerplate; skip those lines.
OTHER_GAMES = re.compile(r"pok[eé]mon|swsh|\bsv\d|magic|mtg|lorcana|yu-?gi-?oh|digimon|flesh and blood|star wars|gundam|dragon ball|weiss|union arena|sorcery|altered|riftbound", re.I)
BOILERPLATE = re.compile(r"results? (found )?for|search results|^search:", re.I)


def page_text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html or "")
    html = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h\d|tr|td)>", "\n", html)
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    return "\n".join(re.sub(r"[ \t ​]+", " ", line).strip() for line in text.splitlines() if line.strip())


# ---------- When series go live ----------

def update_series(events, old, today):
    """One row per event series seen near home, with the time it went live (its earliest registration opening)."""
    series = {k: dict(v) for k, v in old.items()}
    for e in events.values():
        title, opens = e.get("title"), e.get("opens")
        if not title or not opens:
            continue
        s = series.setdefault(title, {"id": title, "kind": e["kind"], "seen": today})
        s["drop"] = min(s.get("drop") or opens, opens)
        if e.get("start"):
            s["firstEvent"] = min(s.get("firstEvent") or e["start"], e["start"])
    return series


def drop_pattern(series, kinds):
    """For each kind: how many series, the usual drop time (Eastern) and days from drop to first event."""
    out = {}
    for kind in kinds:
        rows = [s for s in series.values() if s.get("kind") == kind and s.get("drop") and s.get("firstEvent")]
        if not rows:
            continue
        drops = [datetime.fromisoformat(s["drop"]).astimezone(ET) for s in rows]
        leads = [(datetime.fromisoformat(s["firstEvent"]).date() - d.date()).days for s, d in zip(rows, drops)]
        hours = [d.hour + d.minute / 60 for d in drops]
        hour = statistics.mode(round(h * 2) / 2 for h in hours)
        out[kind] = {"series": len(rows), "hourET": hour, "leadDays": round(statistics.median(leads))}
    return out


def pattern_text(pattern, kind):
    p = pattern.get(kind)
    if not p:
        return ""
    h = int(p["hourET"])
    clock = f"{h % 12 or 12}:{'30' if p['hourET'] % 1 else '00'} {'AM' if h < 12 else 'PM'} ET"
    return (f"{kind} series near you have gone live around {clock}, about {p['leadDays']} days before the first event "
            f"({p['series']} series seen).")


# ---------- Predicted prerelease drops ----------
# Reid's rule of thumb: prerelease sign-ups go live on Bandai TCG+ about two weeks before the
# prerelease. Prereleases usually run the week before a set's release, so the guess is
# release date - 7 days - 14 days, at 10 AM Eastern. Drops seen near home replace these numbers.

PRERELEASE_BEFORE_RELEASE = 7
DEFAULT_LEAD_DAYS = 14
DEFAULT_HOUR_ET = 10
SET_CODE = re.compile(r"\[((?:OP|EB|PRB)-?\d{2})\]", re.I)
RELEASE = re.compile(r"Release Date\s*[:\uff1a]?\s*([A-Za-z]{3,9}\.?\s*\d{1,2}\s*,\s*\d{4})|AVAILABLE\s+([A-Za-z]{3,9}\.?\s*\d{1,2}\s*,\s*\d{4})", re.I)


def parse_date(text):
    text = re.sub(r"\s*,\s*", ", ", text.replace(".", "")).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text.title(), fmt).date()
        except ValueError:
            pass
    return None


def release_dates(drops, old, fetch, today):
    """Release dates of booster sets from their official product pages (cached once known and past)."""
    sets = {k: dict(v) for k, v in old.items()}
    for d in drops.values():
        m = SET_CODE.search(d.get("name") or "")
        if not m or d.get("category") != "Boosters":
            continue
        code = m.group(1).upper().replace("-", "")
        prev = sets.get(code) or {}
        if prev.get("release") and prev["release"] < today:
            continue
        try:
            found = RELEASE.search(page_text(fetch(d["url"])))
        except Exception as e:
            print(f"Product page {d['url']} failed: {e}")
            continue
        date = parse_date(next(g for g in found.groups() if g)) if found else None
        if date:
            sets[code] = {**prev, "id": code, "name": d["name"], "url": d["url"], "release": date.isoformat()}
    return sets


def predict_drops(sets, series, pattern, now):
    """Expected sign-up time for each upcoming set's prerelease, and alerts as it gets close."""
    p = pattern.get("Prerelease") or {}
    lead, hour = p.get("leadDays", DEFAULT_LEAD_DAYS), p.get("hourET", DEFAULT_HOUR_ET)
    learned = bool(p)
    alerts = []
    for code, s in sets.items():
        release = datetime.fromisoformat(s["release"]).date()
        if release < now.date():
            continue
        prerelease = release - timedelta(days=PRERELEASE_BEFORE_RELEASE)
        at = datetime.combine(prerelease - timedelta(days=lead), time(int(hour), 30 if hour % 1 else 0), ET)
        s.update({"prerelease": prerelease.isoformat(), "expected": at.isoformat(), "learned": learned})
        live = [x for x in series.values() if x.get("kind") == "Prerelease" and code in re.sub(r"[^A-Z0-9]", "", x["id"].upper())]
        if live:
            s["live"] = min(x["drop"] for x in live)
            continue
        hours = (at - now).total_seconds() / 3600
        stage = "today" if -48 <= hours <= 18 else "soon" if 0 < hours <= 72 else None
        if stage and stage not in (s.get("alerted") or []):
            s["alerted"] = (s.get("alerted") or []) + [stage]
            alerts.append({"source": "Prediction", "title": f"{code} prerelease sign-ups expected {'now' if hours <= 0 else 'soon'}",
                           "url": s["url"], "lines": [predict_text(s, lead, learned)]})
    return alerts


def predict_text(s, lead, learned):
    at = datetime.fromisoformat(s["expected"]).astimezone(ET)
    basis = (f"prerelease series near you have gone live about {lead} days ahead" if learned
             else "sign-ups usually go live about two weeks before the prerelease")
    return (f"{s['name']} releases {datetime.fromisoformat(s['release']):%b %-d}, so the prerelease is likely around "
            f"{datetime.fromisoformat(s['prerelease']):%b %-d}. Based on that, {basis}: watch Bandai TCG+ from "
            f"{at:%a %b %-d}, {at:%-I:%M %p} ET.")


# ---------- Official event pages ----------

def signup_lines(text):
    lines = []
    for line in text.split("\n"):
        parts = [line] if len(line) < 300 else [line[max(0, m.start() - 120):m.end() + 160] for m in SIGNUP_WORDS.finditer(line)]
        for part in parts:
            part = part.strip()
            if len(part) > 12 and SIGNUP_WORDS.search(part) and re.search(MONTHS, part, re.I):
                lines.append(part)
    return list(dict.fromkeys(lines))[:8]


def watch_official(news, old, fetch):
    """Registration and entry lines on each official event page. Returns (rows, new alerts)."""
    rows, alerts = {}, []
    for a in news.values():
        prev = old.get(a["url"]) or {}
        try:
            lines = signup_lines(page_text(fetch(a["url"])))
        except Exception as e:
            print(f"Official page {a['url']} failed: {e}")
            rows[a["url"]] = prev or {"id": a["url"], "name": a["name"], "lines": []}
            continue
        rows[a["url"]] = {"id": a["url"], "name": a["name"], "lines": lines}
        fresh = [l for l in lines if l not in (prev.get("lines") or [])]
        if prev and fresh:  # a page seen for the first time fills in quietly
            alerts.append({"source": "Official site", "title": a["name"], "url": a["url"], "lines": fresh})
    print(f"Official pages: {sum(len(r['lines']) for r in rows.values())} sign-up lines on {len(rows)} pages")
    return rows, alerts


# ---------- Store websites ----------

def store_pages(events):
    """Readable store websites from nearby events, one per store."""
    stores = {}
    for e in events.values():
        for url in (e.get("storeUrl"), e.get("storeSns")):
            if not url or not url.startswith("http"):
                continue
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if not host or any(host == d or host.endswith("." + d) for d in UNREADABLE):
                continue
            stores.setdefault(host, {"id": host, "store": e.get("store"), "url": url, "miles": e.get("miles")})
    return stores


def read_store(store, fetch):
    url = store["url"]
    html = fetch(url)
    texts = [page_text(html)]
    if "cdn.shopify.com" in html or "Shopify" in html:  # Shopify search lists prerelease tickets
        root = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        try:
            texts.append(page_text(fetch(urljoin(root, "/search?q=prerelease&type=product"))))
        except Exception:
            pass
    snippets = []
    for text in texts:
        for m in PRERELEASE.finditer(text):
            s = re.sub(r"\s+", " ", m.group(0)).strip()
            if len(s) > 15 and not OTHER_GAMES.search(s) and not BOILERPLATE.search(s):
                snippets.append(s[:300])
    return list(dict.fromkeys(snippets))[:MAX_SNIPPETS]


def watch_stores(events, old, fetch):
    """Prerelease mentions on nearby store websites. Returns (rows, new alerts)."""
    stores = store_pages(events)
    for host, prev in old.items():  # keep stores whose events have passed
        stores.setdefault(host, {k: prev[k] for k in ("id", "store", "url", "miles") if k in prev})

    def check(store):
        try:
            return store, read_store(store, fetch), None
        except Exception as e:
            return store, None, str(e)[:120]

    rows, alerts = {}, []
    with ThreadPoolExecutor(8) as pool:
        for store, snippets, err in pool.map(check, stores.values()):
            prev = old.get(store["id"]) or {}
            if snippets is None:
                rows[store["id"]] = {**store, "snippets": prev.get("snippets") or [], "error": err}
                continue
            rows[store["id"]] = {**store, "snippets": snippets}
            fresh = [s for s in snippets if s not in (prev.get("snippets") or [])]
            if prev and fresh:
                alerts.append({"source": store.get("store") or store["id"], "title": f"Prerelease news from {store.get('store') or store['id']}",
                               "url": store["url"], "lines": fresh[:4], "miles": store.get("miles")})
    ok = sum(1 for r in rows.values() if not r.get("error"))
    print(f"Store websites: {ok} of {len(rows)} readable, {sum(len(r['snippets']) for r in rows.values())} prerelease mentions")
    return rows, alerts


# ---------- Messages ----------

def alert_markdown(alerts, pattern):
    if not alerts:
        return ""
    out = ["### Sign-up news\n"]
    for a in alerts:
        out.append(f"- [{a['title']}]({a['url']})")
        out += [f"  > {l}" for l in a["lines"]]
    hint = pattern_text(pattern, "Prerelease")
    if hint:
        out.append(f"\n{hint}")
    return "\n".join(out) + "\n"


def alert_embeds(alerts, pattern):
    hint = pattern_text(pattern, "Prerelease")
    embeds = []
    for a in alerts:
        text = "\n".join(f"> {l}" for l in a["lines"])
        if hint:
            text += f"\n\n{hint}"
        embeds.append({"title": f"Sign-up news: {a['title']}"[:256], "url": a["url"], "description": text[:4000], "color": 0x8E44AD,
                       "footer": {"text": a["source"] + (f" · {a['miles']} mi" if a.get("miles") is not None else "")}})
    return embeds
