"""Temporary: product and event announcement markup on the official card game site."""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode("utf-8", "replace")


b = get("https://en.onepiece-cardgame.com/products/")
i = b.find("linkListCol")
print(re.sub(r"[ \t]+", " ", b[i - 1500:i + 6000]))
print("count", b.count("linkListColTitle"))
d = get("https://en.onepiece-cardgame.com/products/card_collection_asl.html")
i = d.find("PREMIUM BANDAI")
print(re.sub(r"\s+", " ", d[max(0, i - 3000):i + 3000]))
print("p-bandai links", set(re.findall(r'https?://p-bandai[^"\']+', d)))
e = get("https://en.onepiece-cardgame.com/events/")
i = e.find("treasure-cup-dec-2026")
print(re.sub(r"[ \t]+", " ", e[i - 2500:i + 2500]))
