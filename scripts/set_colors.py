"""Give each set the main color of its booster box (or starter deck) art.

Samples the product image TCGplayer shows for the set's box, skips the white
background and greys, and keeps the most common strong color. The site uses it
for the set's tile on Home. Pre-release and release event sets (OP14-PR) take
their main set's color. Sets that already have a color are left alone, so a
color can also be set by hand in data/sets.json.

Usage: python3 scripts/set_colors.py [--all] [--dry-run]
Needs Pillow (pip install pillow).
"""
import colorsys
import io
import re
import sys
import time
import urllib.request

from PIL import Image

from common import DATA, read_json, write_json

IMAGE = "https://tcgplayer-cdn.tcgplayer.com/product/{}_200w.jpg"
UA = {"User-Agent": "reidsord-optcg-inventory/1.0 (+https://github.com/reidsord/optcg)"}

# Which sealed product best shows a set's look, best first.
PICKS = [
    re.compile(r"Booster Box(?! Case)|\b(Collection|Edition) Box$"),
    re.compile(r"^(Super Pre-Release )?(Starter Deck|Ultra Deck)|Deck Set$"),
    re.compile(r"(?<!Sleeved )Booster Pack$|Edition Pack$|Collection Pack$"),
]
SKIP = re.compile(r"DON!!|Case|Display|Bonus|Set of|Promotion")


def box_product(cards):
    sealed = [c for c in cards if not c.get("cardId") and not SKIP.search(c["name"])]
    for pattern in PICKS:
        for c in sealed:
            if pattern.search(c["name"]):
                return c
    return None


def fetch_image(product_id, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(IMAGE.format(product_id), headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return Image.open(io.BytesIO(r.read())).convert("RGB")
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def main_color(img):
    """Average of the pixels in the most common strong hue, as #rrggbb."""
    img.thumbnail((96, 96))
    bins = {}
    data = img.tobytes()
    for i in range(0, len(data), 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s < 0.35 or v < 0.2:  # white background, greys, shadows
            continue
        k = int(h * 24) % 24
        w = s * s * v  # favor vivid box colors over skin tones and muted art
        acc = bins.setdefault(k, [0.0, 0.0, 0.0, 0.0])
        acc[0] += w
        acc[1] += r * w
        acc[2] += g * w
        acc[3] += b * w
    if not bins:
        return None
    # Let neighbouring hue bins vote together so a gradient isn't split in two.
    best = max(bins, key=lambda k: bins[k][0] + 0.5 * (bins.get((k - 1) % 24, [0])[0] + bins.get((k + 1) % 24, [0])[0]))
    w, r, g, b = bins[best]
    return "#{:02x}{:02x}{:02x}".format(round(r / w), round(g / w), round(b / w))


def main(redo=False, dry_run=False):
    sets = read_json(f"{DATA}/sets.json", [])
    by_code = {s["code"]: s for s in sets}
    changed = 0
    for s in sets:
        if s.get("color") and not redo:
            continue
        if re.search(r"-PR$", s["code"]):
            continue  # filled from the main set below
        product = box_product(read_json(f"{DATA}/cards/{s['file']}", []))
        if not product:
            print(f"{s['code']}: no box or deck product")
            continue
        try:
            color = main_color(fetch_image(product["productId"]))
        except Exception as e:
            print(f"{s['code']}: image failed ({e})")
            continue
        print(f"{s['code']}: {color} from {product['name']}")
        if color:
            s["color"] = color
            changed += 1
    for s in sets:
        m = re.match(r"(.+)-PR$", s["code"])
        parent = m and by_code.get(m.group(1))
        if parent and parent.get("color") and (redo or not s.get("color")) and s.get("color") != parent["color"]:
            s["color"] = parent["color"]
            print(f"{s['code']}: {s['color']} from {parent['code']}")
            changed += 1
    print(f"{changed} set colors {'would change' if dry_run else 'changed'}")
    if changed and not dry_run:
        write_json(f"{DATA}/sets.json", sets)


if __name__ == "__main__":
    main(redo="--all" in sys.argv, dry_run="--dry-run" in sys.argv)
