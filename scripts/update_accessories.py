"""Daily TCGplayer prices for accessories (playmats, sleeves, deck boxes and so on).

data/accessories.json holds one item per line. Reid sets name, cat, qty, myPrice
(his own price, used as the fallback) and optionally productId (from the
TCGplayer product link). For each linked item this job writes:

- tcgPrice: TCGplayer's lowest listed price, or null when nothing is listed;
- tcgAt: the day it was read;
- tcgGroup: [categoryId, groupId] where tcgcsv.com lists the product, so it is
  only searched for once;
- tcgName: TCGplayer's product name;
- tcgSearchedAt: when a link that couldn't be found was last searched for.

Official sleeves and playmats are often in the One Piece category (68); most
other supplies (Dragon Shield, Ultra Pro, ...) are in TCGplayer's Supplies
category. A new link is looked for in both.

New official One Piece accessories are added on their own at 0 owned (auto:
true): any product in a Supplies group named for One Piece or Bandai whose
name or group says One Piece. Every product added this way is remembered in
meta.json `accessoryProducts`, so one Reid deletes on the site stays deleted.

Usage: python3 scripts/update_accessories.py [--dry-run]
"""
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from common import DATA, dump_rows, read_json, write_json, write_text
from update_prices import fetch, lowest_price

TCGCSV = "https://tcgcsv.com/tcgplayer"
ONE_PIECE = 68
MAX_SEARCH_REQUESTS = 600  # a first-time search through Supplies; later runs go straight to the group
PATH = f"{DATA}/accessories.json"


def supply_categories():
    try:
        cats = fetch(f"{TCGCSV}/categories")
    except Exception as e:
        print("  could not list categories:", e)
        return []
    return [c["categoryId"] for c in cats
            if c["categoryId"] != ONE_PIECE and re.search(r"suppl|accessor", f"{c.get('name', '')} {c.get('displayName', '')}", re.I)]


def find_groups(wanted, supply_cats, budget):
    """Find which [category, group] lists each wanted productId. Returns (found, prices by productId).

    Reads each group's product list rather than its prices: a playmat with no listings
    today has no price row but is still in the catalog."""
    found, rows = {}, {}
    requests = 0
    for cat in [ONE_PIECE] + supply_cats:
        try:
            groups = fetch(f"{TCGCSV}/{cat}/groups")
        except Exception as e:
            print(f"  could not list groups in category {cat}:", e)
            continue
        # Newer groups first: recent playmats and sleeves are the likeliest.
        for g in sorted(groups, key=lambda g: -g["groupId"]):
            if not wanted - found.keys() or requests >= budget:
                return found, rows
            requests += 1
            try:
                products = fetch(f"{TCGCSV}/{cat}/{g['groupId']}/products")
            except Exception:
                continue
            for p in products:
                if p["productId"] in wanted:
                    found[p["productId"]] = [cat, g["groupId"]]
                    print(f"  found {p['name']} in {cat}/{g['groupId']} ({g.get('name')})")
            time.sleep(0.1)
    return found, rows


ONE_PIECE_GROUP = re.compile(r"one piece|bandai", re.I)
ONE_PIECE_NAME = re.compile(r"one piece", re.I)
CATEGORY_RULES = [  # first match wins
    ("mat-gear", r"\btube\b|playmat bag|mat bag|mat case"),
    ("playmats", r"play ?mat|game ?mat"),
    ("sleeves", r"sleeve"),
    ("deckboxes", r"deck ?(box|case|holder|vault)"),
    ("binders", r"binder|portfolio|album"),
    ("toploaders", r"top ?loader|one[- ]touch|card saver|magnetic"),
    ("storage", r"storage|card box|card case|\bcase\b|\bbox\b"),
    ("counters", r"\bdice\b|\bdie\b|counter|marker|token"),
]


def accessory_category(name):
    for cat, pattern in CATEGORY_RULES:
        if re.search(pattern, name, re.I):
            return cat
    return "other"


def find_new_official(cats, known, today):
    """Official One Piece accessories in the Supplies categories that aren't tracked yet."""
    new = []
    for cat in cats:
        try:
            groups = fetch(f"{TCGCSV}/{cat}/groups")
        except Exception as e:
            print(f"  could not list groups in category {cat}:", e)
            continue
        matching = [g for g in groups if ONE_PIECE_GROUP.search(g.get("name", ""))]
        print(f"  category {cat}: {len(groups)} groups, One Piece/Bandai groups: {[g['name'] for g in matching]}")
        for g in matching:
            group_is_op = bool(ONE_PIECE_NAME.search(g["name"]))
            try:
                products = fetch(f"{TCGCSV}/{cat}/{g['groupId']}/products")
            except Exception as e:
                print(f"  failed {cat}/{g['groupId']}: {e}")
                continue
            for p in sorted(products, key=lambda p: p["productId"]):
                name = p.get("name") or ""
                if p["productId"] in known or "Japanese" in name or not (group_is_op or ONE_PIECE_NAME.search(name)):
                    continue
                known.add(p["productId"])
                new.append({"id": f"p{p['productId']}", "cat": accessory_category(name), "name": name, "qty": 0,
                            "productId": p["productId"], "auto": True, "added": today,
                            "tcgGroup": [cat, g["groupId"]], "tcgName": name})
    return new


def product_names(cat, group, ids):
    if not ids:
        return {}
    try:
        return {p["productId"]: p["name"] for p in fetch(f"{TCGCSV}/{cat}/{group}/products") if p["productId"] in ids}
    except Exception:
        return {}


def main(dry_run=False):
    items = read_json(PATH, [])
    meta = read_json(f"{DATA}/meta.json", {})
    today = datetime.now(timezone.utc).date().isoformat()

    cats = supply_categories()
    seen = set(meta.get("accessoryProducts", []))
    known = seen | {a["productId"] for a in items if a.get("productId")}
    new = find_new_official(cats, known, today)
    items.extend(new)
    seen |= {a["productId"] for a in new}
    print(f"{len(new)} new official accessories")
    for a in new[:100]:
        print(f"  new: [{a['cat']}] {a['name']}")

    linked = [a for a in items if a.get("productId")]

    # Links not found before are searched again once a week (a new listing can show up later).
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    unknown = {a["productId"] for a in linked if not a.get("tcgGroup") and a.get("tcgSearchedAt", "") <= week_ago}
    found, found_rows = find_groups(unknown, cats, MAX_SEARCH_REQUESTS) if unknown else ({}, {})
    for a in linked:
        if a["productId"] in found:
            a["tcgGroup"] = found[a["productId"]]
            a.pop("tcgSearchedAt", None)
        elif a["productId"] in unknown:
            a["tcgSearchedAt"] = today

    by_group = {}
    for a in linked:
        if a.get("tcgGroup"):
            by_group.setdefault(tuple(a["tcgGroup"]), []).append(a)

    changes, missing = 0, []
    for (cat, group), group_items in by_group.items():
        ids = {a["productId"] for a in group_items}
        if ids <= found_rows.keys():
            rows = found_rows
        else:
            try:
                rows = {}
                for p in fetch(f"{TCGCSV}/{cat}/{group}/prices"):
                    rows.setdefault(p["productId"], []).append(p)
            except Exception as e:  # keep yesterday's price
                print(f"  failed {cat}/{group}: {e}")
                continue
        names = product_names(cat, group, {a["productId"] for a in group_items if not a.get("tcgName")})
        for a in group_items:
            if a["productId"] in names:
                a["tcgName"] = names[a["productId"]]
            low = lowest_price(rows.get(a["productId"], []))
            if low != a.get("tcgPrice"):
                changes += 1
                print(f"  {a['name']}: {a.get('tcgPrice')} -> {low}")
            a["tcgPrice"] = low
            a["tcgAt"] = today

    for a in linked:
        if not a.get("tcgGroup"):
            missing.append(f"{a['name']} (product {a['productId']})")

    print(f"{len(linked)} linked accessories, {changes} price changes, {len(missing)} not found on tcgcsv")
    for line in missing:
        print("  not found:", line)
    if not dry_run:
        write_text(PATH, dump_rows(items))
        if seen != set(meta.get("accessoryProducts", [])):
            meta["accessoryProducts"] = sorted(seen)
            write_json(f"{DATA}/meta.json", meta)


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
