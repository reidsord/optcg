"""One-time import of a backup exported from the old ChatGPT-hosted app.

Usage: python3 scripts/import_backup.py path/to/optcg-backup.json
"""
import json
import sys
from datetime import datetime, timezone

from common import DATA, card_row, dump_rows, set_file, write_json, write_text


def to_number(value):
    if isinstance(value, (int, float)):
        return value
    if value in (None, "", "-"):
        return None
    try:
        n = float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None
    return int(n) if n == int(n) else n


def main(path):
    with open(path, encoding="utf-8") as f:
        backup = json.load(f)

    sets, cards_by_set = [], {}
    for c in backup["cards"]:
        code = c["set"]
        if code not in cards_by_set:
            cards_by_set[code] = []
            sets.append({"code": code, "name": c["setName"], "groupId": c["groupId"], "file": set_file(code)})
        row = card_row({**c, "qty": c.get("qty") or 0})
        cards_by_set[code].append(row)

    # A set can carry two names (e.g. a renamed promo group); keep the most common one.
    for s in sets:
        names = [c["setName"] for c in backup["cards"] if c["set"] == s["code"]]
        s["name"] = max(set(names), key=names.count)

    for s in sets:
        write_text(f"{DATA}/cards/{s['file']}", dump_rows(cards_by_set[s["code"]]))
    write_json(f"{DATA}/sets.json", sets)

    orders = []
    for o in backup.get("orders", []):
        orders.append({
            "id": o["id"],
            "qty": o.get("qty"),
            "set": o.get("set") or "",
            "store": o.get("store") or "",
            "order": o.get("order") or "",
            "date": str(o.get("date") or "")[:10],
            "paid": to_number(o.get("paid")),
            "remaining": to_number(o.get("remaining")),
            "note": "" if o.get("item") in (None, "") else str(o["item"]),
        })
    write_json(f"{DATA}/orders.json", orders)

    notes = next((n.get("text", "") for n in backup.get("notes", [])), "")
    write_json(f"{DATA}/notes.json", {"text": notes})
    write_text(f"{DATA}/history.json", "[]\n")

    price_times = [c["priceAt"] for c in backup["cards"] if c.get("priceAt")]
    write_json(f"{DATA}/meta.json", {
        "pricesUpdatedAt": max(price_times) if price_times else None,
        "priceSource": "TCGplayer market price (imported from the old app)",
        "importedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # Groups above this id are new releases and get added automatically.
        "groupWatermark": max(s["groupId"] for s in sets),
        # Groups deliberately left out of the collection.
        "excludedGroups": [24306],
    })
    print(f"Imported {sum(len(v) for v in cards_by_set.values())} cards in {len(sets)} sets and {len(orders)} orders.")


if __name__ == "__main__":
    main(sys.argv[1])
