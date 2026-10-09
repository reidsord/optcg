"""Temporary probe: what does Bandai TCG+ expose before registration opens?"""
import json, re, sys, urllib.parse
from datetime import datetime, timezone
sys.path.insert(0, "scripts")
from update_events import fetch, TCG_API, ONE_PIECE, kind_of

now = datetime.now(timezone.utc).isoformat()
def q(extra, label):
    params = [("game_title_id", ONE_PIECE), ("limit", 100), ("offset", 0), ("country_code[]", "US"), ("order", 1)] + extra
    try:
        body = json.loads(fetch(TCG_API + "?" + urllib.parse.urlencode(params), tries=1))
    except Exception as e:
        print(label, "ERR", e); return []
    s = body.get("success") or {}
    page = s.get("event_list") or []
    later = [e for e in page if (e.get("apply_start_datetime") or "") > now]
    print(f"{label}: total {s.get('total')} page {len(page)} pre-entry {len(later)} keys={list(s.keys())}")
    return page

page = q([("start_date", now[:10])], "US all from today")
if page:
    print("EVENT KEYS:", sorted(page[0].keys()))
    print("SAMPLE:", json.dumps(page[0])[:1500])
for flg in ("0", "1", "2", "3"):
    q([("start_date", now[:10]), ("application_open_flg", flg)], f"flg={flg}")
for k, v in [("status", "0"), ("entry_status", "0"), ("event_status", "1"), ("is_before_entry", "1"), ("application_status", "1"), ("apply_status", "0")]:
    q([("start_date", now[:10]), (k, v)], f"{k}={v}")
pre = q([("start_date", "2026-11-01"), ("keyword", "pre")], "from Nov keyword")
# far-future events nationally, sorted by start
for off in (0, 100, 200, 300):
    pg = q([("start_date", "2026-11-15"), ("offset", off)], f"US from Nov 15 offset {off}")
    for e in pg:
        if kind_of(e.get("event_series_title")) == "Prerelease" or (e.get("apply_start_datetime") or "") > now:
            print("  ", e.get("id"), e.get("start_datetime"), "apply", e.get("apply_start_datetime"), e.get("event_series_title"), "|", e.get("organizer_name"))
# website JS: find API paths and params
for url in ["https://www.bandai-tcg-plus.com/", "https://www.bandai-tcg-plus.com/event"]:
    try:
        html = fetch(url, tries=1)
    except Exception as e:
        print(url, "ERR", e); continue
    srcs = re.findall(r'src="([^"]+\.js)"', html)
    print(url, len(html), srcs[:20])
    for s in srcs[:15]:
        u = urllib.parse.urljoin(url, s)
        try:
            js = fetch(u, tries=1)
        except Exception as e:
            print(" ", u, "ERR", e); continue
        apis = sorted(set(re.findall(r'["\'`](/?api/[a-z_/{}$.]+)', js)))
        if apis: print(" ", u, apis[:80])
        for m in set(re.findall(r'(apply[a-z_]*|application[a-z_]*|entry_[a-z_]*|publish[a-z_]*|release_[a-z_]*)', js)):
            pass
        flags = sorted(set(re.findall(r'\b(apply[a-z_]{2,30}|application_[a-z_]{2,30}|entry_[a-z_]{2,30}|publish[a-z_]{0,30})\b', js)))
        if flags: print("   fields:", flags[:80])
# event detail endpoints
if page:
    eid = page[0]["id"]
    for path in [f"https://api.bandai-tcg-plus.com/api/user/event/{eid}", f"https://api.bandai-tcg-plus.com/api/user/event/detail?event_id={eid}", f"https://api.bandai-tcg-plus.com/api/user/event/detail/{eid}"]:
        try:
            print(path, fetch(path, tries=1)[:1200])
        except Exception as e:
            print(path, "ERR", e)
