"""Temporary probe: can past prerelease series and their drop times be read back?"""
import json, sys, urllib.parse
sys.path.insert(0, "scripts")
from update_events import fetch, TCG_API, ONE_PIECE, kind_of

series = {}
for start in ("2025-06-01", "2025-10-01", "2026-01-01", "2026-04-01", "2026-07-01"):
    for off in range(0, 3000, 100):
        params = [("game_title_id", ONE_PIECE), ("limit", 100), ("offset", off), ("country_code[]", "US"), ("order", 1),
                  ("start_date", start), ("end_date", start[:8] + "28"), ("current_lat", 39.6134), ("current_lng", -86.1047), ("distance", 300)]
        try:
            s = json.loads(fetch(TCG_API + "?" + urllib.parse.urlencode(params), tries=1)).get("success") or {}
        except Exception as e:
            print(start, off, "ERR", e); break
        page = s.get("event_list") or []
        if off == 0: print(start, "total", s.get("total"), "first", page[:1] and page[0].get("start_datetime"))
        for e in page:
            t = e.get("event_series_title") or ""
            k = kind_of(t)
            if k in ("Prerelease", "Release Event", "Treasure Cup", "Store Championship", "Regionals"):
                d = series.setdefault(t, {"kind": k, "n": 0, "min_apply": "9", "min_start": "9", "created": "9", "ex": e["id"]})
                d["n"] += 1
                d["min_apply"] = min(d["min_apply"], e.get("apply_start_datetime") or "9")
                d["min_start"] = min(d["min_start"], e.get("start_datetime") or "9")
                d["created"] = min(d["created"], e.get("event_created_at") or "9")
        if len(page) < 100: break
for t, d in sorted(series.items(), key=lambda kv: kv[1]["min_start"]):
    rel = ""
    try:
        rel = json.loads(fetch(f"https://api.bandai-tcg-plus.com/api/user/event/{d['ex']}", tries=1))["success"]["event"].get("webReleaseStartDate")
    except Exception as e:
        rel = f"ERR {e}"
    print(f"{d['kind']:18} n={d['n']:3} first event {d['min_start']} | drop {rel} | earliest apply {d['min_apply']} | {t}")
