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


def classify(name, card_number, set_code):
    """Return (alt, target) for a newly listed product, following the existing rules:
    sealed product has no card number and counts once; alternate arts count once;
    base cards count four times, except the loose Promo set which counts once."""
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
