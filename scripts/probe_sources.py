"""Temporary: event search parameters and where Premium Bandai lists products."""
import json
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}


def get(url, timeout=60, show=True):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            print(f"{r.status} {len(body)}b {time.time() - t:.1f}s {url}")
            return body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"HTTP {e.code} {time.time() - t:.1f}s {url} {body[:300]!r}")
        return ""
    except Exception as e:
        print(f"ERR {e} {time.time() - t:.1f}s {url}")
        return ""


bundle = get("https://www.bandai-tcg-plus.com/dist/js/bundle.js")
print("#### createSendQuery")
for m in list(re.finditer(r"createSendQuery:function", bundle))[:2]:
    print(bundle[m.start():m.start() + 4000], "\n")
print("#### tabList")
for m in list(re.finditer(r"tabList:", bundle))[:2]:
    print(bundle[m.start():m.start() + 800], "\n")

print("#### params")
p = get("https://api.bandai-tcg-plus.com/api/user/event/list/params")
try:
    d = json.loads(p)["success"]
    for k, v in d.items():
        if isinstance(v, list):
            print(k, len(v))
            for row in v:
                if str(row.get("game_title_id", "")) == "4" or "event_series" not in k:
                    print("   ", json.dumps(row)[:400])
        else:
            print(k, json.dumps(v)[:2000])
except Exception as e:
    print("parse", e, p[:500])


def summary(q):
    body = get(f"https://api.bandai-tcg-plus.com/api/user/event/list?{q}", timeout=120)
    try:
        d = json.loads(body)["success"]
        ev = d["event_list"]
        print("   total", d.get("total"), "n", len(ev), "countries", sorted({e.get("country_code") for e in ev}),
              "prefs", sorted({e.get("pref_code") for e in ev})[:12], "series", sorted({e.get("event_series_title") for e in ev})[:8],
              "start", min((e["start_datetime"] for e in ev), default=None), max((e["start_datetime"] for e in ev), default=None))
    except Exception as e:
        print("   parse", e, body[:200])


print("#### filter tests")
for q in ["game_title_id=4&limit=20&offset=0&country_code[]=US",
          "game_title_id=4&limit=20&offset=0&country_code[]=US&pref_code[]=US-TX",
          "game_title_id=4&limit=20&offset=0&country_code[]=US&start_date=2026-11-01",
          "game_title_id=4&limit=20&offset=0&country_code[]=US&latitude=32.78&longitude=-96.80&distance=50",
          "game_title_id=4&limit=20&offset=0&country_code[]=US&lat=32.78&lng=-96.80&distance=50"]:
    summary(q)

print("#### premium bandai")
for u in ["https://p-bandai.com/robots.txt", "https://p-bandai.com/sitemap.xml", "https://p-bandai.com/us/sitemap.xml"]:
    b = get(u)
    print(b[:1500])
page = get("https://p-bandai.com/us/series/onepiece-series")
js = re.findall(r'src="(/assets/[^"]+\.js)"', page) + re.findall(r'href="(/assets/[^"]+\.js)"', page)
print("assets", js)
found = set()
for path in js[:15]:
    src = get("https://p-bandai.com" + path, show=False)
    found |= set(re.findall(r'["\'`](/(?:api|v\d|us/api)[^"\'`\s]{2,120})', src))
    found |= set(re.findall(r'https://[a-z0-9.-]+/[a-z0-9/_-]*api[^"\'`\s]{0,120}', src))
print("api paths", sorted(found)[:120])
print("links on series page", sorted(set(re.findall(r'href="(/us/[^"]+)"', page)))[:150])
