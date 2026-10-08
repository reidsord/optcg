"""Temporary: learn the Bandai TCG+ event API parameters and Premium Bandai item markup."""
import json
import re
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}


def get(url, timeout=60):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            print(f"{r.status} {len(body)}b {time.time() - t:.1f}s {url}")
            return body
    except Exception as e:
        print(f"ERR {e} {time.time() - t:.1f}s {url}")
        return ""


print("#### api_url.js")
print(get("https://www.bandai-tcg-plus.com/js/api_url.js")[:1500])
bundle = get("https://www.bandai-tcg-plus.com/dist/js/bundle.js")
print("#### bundle: event list call sites")
for m in list(re.finditer(r"event/list", bundle))[:8]:
    print("...", bundle[max(0, m.start() - 1500):m.start() + 800].replace("\n", " "), "\n")
print("#### bundle: query keys near event")
keys = sorted(set(re.findall(r'[?&]([a-z_]+)=', bundle)) | set(re.findall(r'"?(\w*(?:pref|country|series|tab|keyword|area|geo|lat|lng|distance|radius|date|status|sort|order)\w*)"?\s*:', bundle)))
print(keys[:400])
print("#### series ids/titles")
print(sorted(set(re.findall(r'(?:series|Series)[A-Za-z_]*["\']?\s*[:=]\s*["\']?[^,}{]{0,60}', bundle)))[:80])

print("#### event list samples")
for q in ["game_title_id=4&limit=50&offset=0&country_code=US",
          "game_title_id=4&limit=50&offset=0&selected_tab=3",
          "game_title_id=4&limit=50&offset=0&pref_code=US-TX"]:
    body = get(f"https://api.bandai-tcg-plus.com/api/user/event/list?{q}", timeout=90)
    try:
        d = json.loads(body)["success"]
        ev = d.get("event_list", [])
        print("keys", [k for k in d if k != "event_list"], {k: d[k] for k in d if k != "event_list"})
        print("countries", sorted({e.get("country_code") for e in ev}), "count", len(ev))
        for e in ev[:50]:
            print(" ", e["id"], e.get("country_code"), e.get("pref_code"), e.get("start_datetime"), "apply", e.get("apply_start_datetime"),
                  "|", e.get("event_series_title"), "|", e.get("organizer_name"), "| fmt", e.get("game_format_ids"), "st", e.get("status_id"), e.get("series_type"))
    except Exception as e:
        print("parse fail", e, body[:300])

print("#### event detail")
print(get("https://api.bandai-tcg-plus.com/api/user/event/7008890")[:3000])

print("#### premium bandai series page")
page = get("https://p-bandai.com/us/series/onepiece-series")
for m in list(re.finditer(r"/us/item/(F\d+)", page))[:3]:
    print("...", re.sub(r"\s+", " ", page[max(0, m.start() - 600):m.start() + 1500]), "\n")
print("#### item page")
item = get("https://p-bandai.com/us/item/F2909282001")
print(re.sub(r"\s+", " ", item)[:6000])
print("json-ld:", re.findall(r'<script type="application/ld\+json">(.*?)</script>', item, re.S)[:3])
