"""Temporary probe: find the newest event ids and look for events not yet released."""
import json, sys, time
from datetime import datetime, timezone
sys.path.insert(0, "scripts")
from update_events import fetch

now = datetime.now(timezone.utc).isoformat()
API = "https://api.bandai-tcg-plus.com/api/user"
def ev(eid):
    try:
        return (json.loads(fetch(f"{API}/event/{eid}", tries=1, timeout=20)).get("success") or {}).get("event")
    except Exception as e:
        return None if "404" in str(e) else {"ERR": str(e)}

def exists_near(eid, span=40):
    for i in range(0, span, 4):
        e = ev(eid + i)
        if e and "ERR" not in e:
            return e
    return None

t0 = time.time()
lo, hi = 8621386, 8621386 + 50000
while exists_near(hi):
    lo, hi = hi, hi + 50000
while hi - lo > 40:
    mid = (lo + hi) // 2
    if exists_near(mid):
        lo = mid
    else:
        hi = mid
print("frontier about", lo, "in", round(time.time() - t0), "s")
e = exists_near(lo)
print("near frontier:", e and {k: e.get(k) for k in ("id", "event_series_title", "apply_start_datetime", "webReleaseStartDate", "pref_code", "game_title_id")})
for k in (2000, 6000):
    x = exists_near(lo - k)
    print(f"{k} ids back:", x and {kk: x.get(kk) for kk in ("id", "apply_start_datetime", "webReleaseStartDate")})

stats = {"seen": 0, "op": 0, "future_release": 0, "future_apply": 0}
series = {}
for eid in range(lo + 60, lo - 3000, -1):
    e = ev(eid)
    if not e or "ERR" in e:
        continue
    stats["seen"] += 1
    rel, app = e.get("webReleaseStartDate") or "", e.get("apply_start_datetime") or ""
    if rel > now: stats["future_release"] += 1
    if app > now: stats["future_apply"] += 1
    if str(e.get("game_title_id")) != "4":
        continue
    stats["op"] += 1
    key = e.get("event_series_title")
    s = series.setdefault(key, {"n": 0, "release": rel, "apply": set(), "countries": set(), "example": eid})
    s["n"] += 1; s["apply"].add(app[:16]); s["countries"].add(e.get("country_code") or e.get("pref_code"))
    if rel > now or app > now:
        print("PRE-RELEASE", eid, e.get("pref_code"), e.get("start_datetime"), "release", rel, "apply", app, "|", key, "|", e.get("organizer_name"), "status", e.get("status_id"), "approval", e.get("approval_status"))
print(stats, round(time.time() - t0), "s")
for k, s in sorted(series.items(), key=lambda kv: -kv[1]["n"]):
    print(f"{s['n']:4} {k} | release {s['release']} | apply {sorted(s['apply'])[-3:]} | {sorted(map(str, s['countries']))[:6]} | e.g. {s['example']}")
