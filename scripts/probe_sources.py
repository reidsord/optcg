"""Temporary: print what Bandai TCG+ and Premium Bandai return to a plain HTTP client."""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "application/json, text/html;q=0.9, */*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}

URLS = [
    "https://www.bandai-tcg-plus.com/",
    "https://www.bandai-tcg-plus.com/event",
    "https://api.bandai-tcg-plus.com/api/user/event/list?game_title_id=4&limit=3&offset=0",
    "https://api.bandai-tcg-plus.com/api/user/event/list?limit=3&offset=0",
    "https://api.bandai-tcg-plus.com/api/user/game_title/list",
    "https://api.bandai-tcg-plus.com/api/user/master/game_title",
    "https://p-bandai.com/us/series/onepiece-series",
    "https://p-bandai.com/us/search?keyword=one%20piece%20card",
]

for url in URLS:
    print("=" * 100)
    print(url)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            print("status", r.status, r.headers.get("content-type"), len(body))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print("HTTP", e.code, len(body))
    except Exception as e:
        print("ERR", e)
        continue
    print(body[:2500])
    print("-- script srcs:", re.findall(r'<script[^>]+src="([^"]+)"', body)[:20])
    print("-- api-ish:", sorted(set(re.findall(r'https?://[a-z0-9.-]*(?:api|bandai)[a-z0-9.-]*/[^"\'\s<>)]{0,120}', body)))[:60])
    for m in re.finditer(r'(__NEXT_DATA__|__NUXT__|window\.__[A-Z_]+__)', body):
        print("-- embedded state at", m.start(), body[m.start():m.start() + 3000])
        break
