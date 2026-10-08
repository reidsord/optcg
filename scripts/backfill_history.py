"""One-time backfill of price and value history from tcgcsv.com's daily price archives.

tcgcsv.com keeps a 7-Zip archive of every day's TCGplayer prices since 2024-02-08.
This takes one day per week for the last N weeks, records each card's lowest listed
price, and estimates the collection value on each of those days. Past values use
today's quantities (the old app kept no record of when cards were added), so they
show how prices moved rather than how the collection grew.

Usage: python3 scripts/backfill_history.py [--weeks 52]   (needs: pip install py7zr)
"""
import argparse
import os
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, timedelta

import py7zr

from common import (DATA, add_price_point, money_round, read_json, read_price_history, read_value_history,
                    write_price_history, write_value_history)
from update_prices import UA, lowest_price

ARCHIVE = os.environ.get("ARCHIVE_URL", "https://tcgcsv.com/archive/tcgplayer/prices-{day}.ppmd.7z")
CATEGORY = "68"
FIRST_DAY = date(2024, 2, 8)


def day_prices(day, groups, tmp):
    """{productId: lowest listed price} for the tracked groups on one day, or None if there is no archive."""
    path = os.path.join(tmp, f"{day}.7z")
    try:
        req = urllib.request.Request(ARCHIVE.format(day=day), headers=UA)
        with urllib.request.urlopen(req, timeout=300) as r, open(path, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    out = os.path.join(tmp, str(day))
    with py7zr.SevenZipFile(path) as z:
        # Members look like 2024-02-08/68/<groupId>/prices.
        wanted = [n for n in z.getnames()
                  if n.count("/") == 3 and n.endswith("/prices") and n.split("/")[1] == CATEGORY
                  and n.split("/")[2].isdigit() and int(n.split("/")[2]) in groups]
        z.extract(path=out, targets=wanted)
    os.remove(path)
    prices = {}
    for name in wanted:
        rows = {}
        for p in (read_json(os.path.join(out, name), {}) or {}).get("results", []):
            rows.setdefault(p["productId"], []).append(p)
        for pid, price_rows in rows.items():
            prices[pid] = lowest_price(price_rows)
    return prices


def main(weeks):
    sets = read_json(f"{DATA}/sets.json", [])
    cards = [c for s in sets for c in read_json(f"{DATA}/cards/{s['file']}", [])]
    groups = {s["groupId"] for s in sets}
    products = {c["productId"] for c in cards}
    existing = read_price_history()
    value_rows = read_value_history()
    first_tracked = min([r["date"] for r in value_rows] + [pt[0] for h in existing.values() for pt in h] or ["9999"])

    days = []
    d = date.fromisoformat(first_tracked) - timedelta(days=7) if first_tracked != "9999" else date.today()
    for _ in range(weeks):
        if d < FIRST_DAY:
            break
        days.append(d)
        d -= timedelta(days=7)
    days.reverse()

    history = {p: [] for p in products}
    past_values = []
    with tempfile.TemporaryDirectory() as tmp:
        for day in days:
            prices = None
            for back in range(3):  # an archive can be missing for a day; try the day before
                prices = day_prices(day - timedelta(days=back), groups, tmp)
                if prices is not None:
                    break
            if prices is None:
                print(f"{day}: no archive")
                continue
            iso = day.isoformat()
            for pid, price in prices.items():
                if pid in history:
                    add_price_point(history[pid], iso, price)
            value = sum((c.get("qty") or 0) * (prices.get(c["productId"]) or 0) for c in cards)
            past_values.append({"date": iso, "value": money_round(value), "copies": sum(c.get("qty") or 0 for c in cards), "backfill": True})
            print(f"{iso}: {len(prices)} prices, collection ${value:,.2f}")

    # Existing tracked points come after the backfilled ones.
    for pid, points in existing.items():
        merged = history.setdefault(pid, [])
        for day, price in points:
            add_price_point(merged, day, price)
    write_price_history(history)
    backfilled = {r["date"] for r in past_values}
    write_value_history(past_values + [r for r in value_rows if r["date"] not in backfilled])
    print(f"Backfilled {len(past_values)} weeks")
    return 0 if past_values or not days else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=52)
    sys.exit(main(ap.parse_args().weeks))
