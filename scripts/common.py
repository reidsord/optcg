"""Shared helpers for reading and writing the inventory data files."""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

# Card fields in the order they are written. One card per line keeps git diffs
# small and lets a price update and a quantity edit merge cleanly.
CARD_FIELDS = ["id", "productId", "cardId", "name", "rarity", "alt", "target", "qty", "price", "added"]

ALT_PATTERN = re.compile(
    r"\((?:[^)]*\b(?:Alternate Art|Parallel|SP|Manga|Textured Foil|Dash Pack|Box Topper|"
    r"Wanted Poster|TR|Pandaman Art|Full Art|Gold|Silver)\b[^)]*)\)"
)


def set_file(code):
    """File name for a set code, e.g. 'OP04 - Prerelease' -> 'OP04-Prerelease.json'."""
    return re.sub(r"[^A-Za-z0-9]+", "-", code).strip("-") + ".json"


def set_groups(s):
    """TCGplayer groups a set's cards come from. Usually one; a set split out of others lists several."""
    return s.get("groupIds") or [s["groupId"]]


def classify(name, card_number, set_code):
    """Return (alt, target) for a newly listed product, following the existing rules:
    sealed product has no card number and counts once; alternate arts count once;
    base cards count four times, except the loose Promo set which counts once;
    DON!! cards count ten times."""
    if re.match(r"DON!! Card(?! Pack)", name or ""):
        return None, 10  # DON!! cards: a full set of ten
    if not card_number:
        return None, 1
    if ALT_PATTERN.search(name or ""):
        return True, 1
    return False, 1 if set_code == "Promo" else 4


def dump_rows(rows):
    """JSON array with one compact object per line."""
    if not rows:
        return "[]\n"
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n]\n"


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = None
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if old == text:
        return False
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, value):
    return write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def card_row(card):
    return {k: card[k] for k in CARD_FIELDS if card.get(k) is not None or k in ("qty", "price", "alt")}


# ---------- Price and value history ----------
# price-history.json: one line per product, {"p": productId, "h": [[date, price], ...]}.
# A point is stored only when the price moves enough to matter, which keeps the
# file small while the daily job runs for years.
PRICE_HISTORY = os.path.join(DATA, "price-history.json")
VALUE_HISTORY = os.path.join(DATA, "value-history.json")
HISTORY_DAYS = 400
MIN_MOVE, MIN_MOVE_PCT = 0.10, 0.05


def read_price_history():
    return {r["p"]: r["h"] for r in read_json(PRICE_HISTORY, [])}


def write_price_history(history, cutoff=None):
    rows = []
    for p in sorted(history):
        points = history[p]
        if cutoff:
            # Keep the last point before the cutoff so the price at the cutoff is still known.
            old = [pt for pt in points if pt[0] < cutoff]
            points = old[-1:] + [pt for pt in points if pt[0] >= cutoff]
        if points:
            rows.append({"p": p, "h": points})
    return write_text(PRICE_HISTORY, dump_rows(rows))


def add_price_point(points, date, price):
    """Append (date, price) to one product's points if it moved enough. Points must arrive in date order."""
    if price is None:
        return
    if points and points[-1][0] >= date:
        return
    if points:
        last = points[-1][1]
        if abs(price - last) < max(MIN_MOVE, MIN_MOVE_PCT * last):
            return
    points.append([date, price])


def read_value_history():
    return read_json(VALUE_HISTORY, [])


def write_value_history(rows):
    rows = sorted(rows, key=lambda r: r["date"])
    return write_text(VALUE_HISTORY, dump_rows(rows))


def money_round(x):
    x = round(x, 2)
    return int(x) if x == int(x) else x
