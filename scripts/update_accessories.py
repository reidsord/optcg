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

Usage: python3 scripts/update_accessories.py [--dry-run]
"""
import re
import sys
import time
from datetime import datetime, timedelta, timezone

from common import DATA, dump_rows, read_json, write_text
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


def find_groups(wanted, budget):
    """Find which [category, group] lists each wanted productId. Returns (found, prices by productId)."""
    found, rows = {}, {}
    requests = 0
    cats = [ONE_PIECE] + supply_categories()
    for cat in cats:
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
                prices = fetch(f"{TCGCSV}/{cat}/{g['groupId']}/prices")
            except Exception:
                continue
            for p in prices:
                if p["productId"] in wanted:
                    found[p["productId"]] = [cat, g["groupId"]]
                    rows.setdefault(p["productId"], []).append(p)
            time.sleep(0.1)
    return found, rows


def product_names(cat, group, ids):
    if not ids:
        return {}
    try:
        return {p["productId"]: p["name"] for p in fetch(f"{TCGCSV}/{cat}/{group}/products") if p["productId"] in ids}
    except Exception:
        return {}


def main(dry_run=False):
    items = read_json(PATH, [])
    linked = [a for a in items if a.get("productId")]
    if not linked:
        print("No accessories linked to TCGplayer.")
        return
    today = datetime.now(timezone.utc).date().isoformat()

    # Links not found before are searched again once a week (a new listing can show up later).
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    unknown = {a["productId"] for a in linked if not a.get("tcgGroup") and a.get("tcgSearchedAt", "") <= week_ago}
    found, found_rows = find_groups(unknown, MAX_SEARCH_REQUESTS) if unknown else ({}, {})
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


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
