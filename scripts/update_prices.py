"""Daily price and catalog update from TCGplayer data published by tcgcsv.com.

- Sets each card's price to TCGplayer's lowest listed price (English cards only:
  category 68 is the English One Piece Card Game; Japanese is a separate category).
- Adds cards newly listed in a tracked set, at 0 owned.
- Adds whole sets released after the newest set already tracked.

Usage: python3 scripts/update_prices.py [--dry-run]
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

from common import DATA, card_row, classify, dump_rows, read_json, set_file, write_json, write_text

BASE = "https://tcgcsv.com/tcgplayer/68"
UA = {"User-Agent": "reidsord-optcg-inventory/1.0 (+https://github.com/reidsord/optcg)"}


def fetch(url, tries=4):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = json.load(r)
            if not body.get("success", True):
                raise RuntimeError(f"{url}: {body.get('errors')}")
            return body.get("results", [])
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** (attempt + 1))


def extended(product, key):
    for e in product.get("extendedData") or []:
        if e.get("name") == key:
            return e.get("value")
    return None


def lowest_price(price_rows):
    """Lowest listed price across printings (Normal/Foil) of one product."""
    lows = [p["lowPrice"] for p in price_rows if p.get("lowPrice") is not None]
    if not lows:
        return None
    low = round(min(lows), 2)
    return int(low) if low == int(low) else low  # match how the site writes numbers


def main(dry_run=False):
    today = datetime.now(timezone.utc).date().isoformat()
    meta = read_json(f"{DATA}/meta.json", {})
    sets = read_json(f"{DATA}/sets.json", [])
    excluded = set(meta.get("excludedGroups", []))
    excluded_products = set(meta.get("excludedProducts", []))  # listings Reid removed on purpose
    watermark = meta.get("groupWatermark", 0)

    cards = {s["code"]: read_json(f"{DATA}/cards/{s['file']}", []) for s in sets}
    known_products = {c["productId"] for rows in cards.values() for c in rows}

    groups = fetch(f"{BASE}/groups")
    tracked = {s["groupId"] for s in sets}
    codes = {s["code"] for s in sets}
    new_sets = []
    for g in sorted(groups, key=lambda g: g["groupId"]):
        if g["groupId"] <= watermark or g["groupId"] in tracked or g["groupId"] in excluded:
            continue
        code = (g.get("abbreviation") or g["name"]).strip()
        if code in codes:
            code = f"{code} ({g['groupId']})"
        entry = {"code": code, "name": g["name"], "groupId": g["groupId"], "file": set_file(code), "added": today}
        sets.append(entry)
        cards[code] = []
        codes.add(code)
        new_sets.append(code)
    if groups:
        meta["groupWatermark"] = max(watermark, max(g["groupId"] for g in groups))

    # Several tracked sets can share one TCGplayer group (e.g. the Starter Deck 4 revision pack).
    by_group = {}
    for s in sets:
        by_group.setdefault(s["groupId"], []).append(s["code"])

    def value():
        return sum((c.get("qty") or 0) * (c.get("price") or 0) for rows in cards.values() for c in rows)

    value_before = value()
    price_changes, new_cards, failed = 0, [], []
    for group_id, set_codes in by_group.items():
        try:
            products = fetch(f"{BASE}/{group_id}/products")
            prices = fetch(f"{BASE}/{group_id}/prices")
        except Exception as e:  # keep yesterday's prices for this set and carry on
            failed.append(f"{group_id}: {e}")
            continue

        rows_by_product = {}
        for p in prices:
            rows_by_product.setdefault(p["productId"], []).append(p)

        for code in set_codes:
            for c in cards[code]:
                low = lowest_price(rows_by_product.get(c["productId"], []))
                if low is not None and low != c.get("price"):
                    c["price"] = low
                    price_changes += 1

        # New listings go to the first set mapped to this group.
        home = set_codes[0]
        for p in sorted(products, key=lambda p: (not extended(p, "Number"), extended(p, "Number") or "", p["name"])):
            if p["productId"] in known_products or p["productId"] in excluded_products or "Japanese" in p["name"]:
                continue
            number = extended(p, "Number") or ""
            alt, target = classify(p["name"], number, home)
            card = card_row({
                "id": f"p{p['productId']}",
                "productId": p["productId"],
                "cardId": number,
                "name": p["name"],
                "rarity": extended(p, "Rarity") or "",
                "alt": alt,
                "target": target,
                "qty": 0,
                "price": lowest_price(rows_by_product.get(p["productId"], [])),
                "added": today,
            })
            cards[home].append(card)
            known_products.add(p["productId"])
            new_cards.append(f"{home} {number} {p['name']}")

    print(f"Collection value ${value_before:,.2f} -> ${value():,.2f}")
    print(f"{price_changes} price changes, {len(new_cards)} new cards, {len(new_sets)} new sets, {len(failed)} failed groups")
    for line in new_sets:
        print("  new set:", line)
    for line in new_cards[:200]:
        print("  new card:", line)
    for line in failed:
        print("  failed:", line)
    if dry_run:
        return 0
    if len(failed) == len(by_group):
        print("Every group failed; leaving data unchanged.")
        return 1

    for s in sets:
        write_text(f"{DATA}/cards/{s['file']}", dump_rows(cards[s["code"]]))
    write_json(f"{DATA}/sets.json", sets)
    meta["pricesUpdatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta["priceSource"] = "TCGplayer lowest listed price (English)"
    write_json(f"{DATA}/meta.json", meta)
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
