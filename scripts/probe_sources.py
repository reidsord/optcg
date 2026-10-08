"""Temporary: find a machine-readable Premium Bandai product list."""
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"HTTP {e.code} {time.time() - t:.1f}s {url} {body[:300]!r}")
        return ""
    except Exception as e:
        print(f"ERR {e} {time.time() - t:.1f}s {url}")
        return ""


sm = get("https://p-bandai.com/us/sitemap-product_1.xml")
print(sm[:3000])
urls = re.findall(r"<url>(.*?)</url>", sm, re.S)
print("url entries", len(urls))
op = [u for u in urls if re.search(r"one ?piece|onepiece", u, re.I)]
print("one piece entries", len(op))
for u in op[:60]:
    print("  ", re.sub(r"\s+", " ", u)[:400])
print("lastmods", sorted(set(re.findall(r"<lastmod>([^<]+)", sm)))[-10:])

for u in ["https://p-bandai.com/api/series/top/onepiece-series", "https://p-bandai.com/us/api/series/top/onepiece-series",
          "https://p-bandai.com/api/series/list", "https://p-bandai.com/api/news?_lc=en_US"]:
    print(get(u)[:1500])

page = get("https://p-bandai.com/us/series/onepiece-series")
src = ""
for path in ["/assets/searchResultService-D9XX0xkb.js", "/assets/AreaSeriesModel-C5_li7lO.js", "/assets/featureService-BXi44G6h.js"]:
    s = get("https://p-bandai.com" + path)
    print(path, s[:2500])

print("#### official card game site products")
for u in ["https://en.onepiece-cardgame.com/products/", "https://en.onepiece-cardgame.com/events/", "https://en.onepiece-cardgame.com/topics/"]:
    b = get(u)
    print(sorted(set(re.findall(r'href="([^"]+)"', b)))[:120])
    for m in list(re.finditer(r"(?i)premium bandai|p-bandai", b))[:5]:
        print("   pb:", re.sub(r"\s+", " ", b[max(0, m.start() - 300):m.start() + 300]))
