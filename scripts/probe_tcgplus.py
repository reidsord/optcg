"""Temporary probe: can events be seen (by id) before they are released in the app?"""
import json, re, sys, urllib.parse
from datetime import datetime, timezone
sys.path.insert(0, "scripts")
from update_events import fetch, TCG_API, ONE_PIECE

now = datetime.now(timezone.utc).isoformat()
API = "https://api.bandai-tcg-plus.com/api/user"
def get(url):
    try:
        return json.loads(fetch(url, tries=1, timeout=30))
    except Exception as e:
        return {"ERR": str(e)}

print(fetch("https://www.bandai-tcg-plus.com/js/api_url.js", tries=1)[:600])
html = fetch("https://www.bandai-tcg-plus.com/event", tries=1)
print(html[:2400])

ids = []
for order in ("1", "2", "3", "4", "5"):
    params = [("game_title_id", ONE_PIECE), ("limit", 100), ("offset", 0), ("country_code[]", "US"), ("order", order), ("start_date", now[:10])]
    s = get(TCG_API + "?" + urllib.parse.urlencode(params)).get("success") or {}
    page = s.get("event_list") or []
    mx = max((e["id"] for e in page), default=0)
    print("order", order, "max id", mx, "newest created", max((e.get("event_created_at") or "" for e in page), default=""))
    ids.append(mx)
top = max(ids)
print("TOP", top)
found = 0
for eid in range(top + 1, top + 400):
    d = get(f"{API}/event/{eid}")
    ev = (d.get("success") or {}).get("event")
    if not ev:
        if eid < top + 6: print(eid, json.dumps(d)[:200])
        continue
    found += 1
    if found <= 3:
        print("DETAIL KEYS", sorted(ev.keys()))
    rel = ev.get("webReleaseStartDate") or ""
    print(eid, ev.get("game_title_id"), ev.get("pref_code"), ev.get("start_datetime"), "release", rel, "future" if rel > now else "", "|", ev.get("event_series_title"), "|", ev.get("organizer_name"),
          {k: ev.get(k) for k in ev if re.search(r"appl|entry|release|status|open|publish", k, re.I)})
print("found", found)
for path in ["event_series/8033", "event-series/8033", "event_series/detail/8033", "event_series/list?game_title_id=4", "event/series/8033", "event_series?game_title_id=4"]:
    print(path, json.dumps(get(f"{API}/{path}"))[:600])
