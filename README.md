# OPTCG collection

Reid's One Piece Card Game inventory: a small website (GitHub Pages) backed by
JSON files in this repo.

- **Home**: quick card search, collection value over time, the week's biggest
  price movers, buy list, newest cards, notes and progress for every set.
- **Cards**: every card with search, filters and shortcuts (owned, buy list,
  most valuable, not owned, new). Tap + or − to change quantities, or tap a card
  for its details, price history and other printings.
- **Packs**: type card numbers as you open packs; each one adds a copy.
- **Decks**: paste a decklist to see what you own, what's missing and what it
  costs; missing cards copy straight into TCGplayer Mass Entry.
- **Orders**: orders and preorders with paid and remaining totals.
- **History**: recent quantity changes, with undo.

## How it works

| Path | What it holds |
| --- | --- |
| `site/` | The website (plain HTML, CSS and JavaScript, no build step). |
| `data/sets.json` | Tracked sets, in display order, with their TCGplayer group ids. A set split out of others (EB04, printed inside OP14 and OP15) lists every source group in `groupIds` and claims new cards by `cardPrefix`. |
| `data/cards/*.json` | One file per set, one card per line. |
| `data/orders.json`, `data/notes.json` | Orders and the notes box. |
| `data/history.json` | The latest 1,000 quantity changes. |
| `data/meta.json` | When prices were updated, plus the settings the daily job uses. |
| `data/price-history.json` | Each card's price whenever it moved at least 5% and 10¢, one card per line. |
| `data/value-history.json` | Collection value on each day the price job ran. |
| `data/decks.json` | Decks saved on the Decks tab. |
| `scripts/update_prices.py` | Daily job: lowest listed TCGplayer price (English cards), new cards and new sets. |
| `scripts/import_backup.py` | One-time import of a backup from the old ChatGPT-hosted app. |

Anyone with the link can view the site. Saving needs a GitHub fine-grained
token with **Contents: Read and write** on this repository only; the site walks
through creating one under **Sign in**. The token stays in that browser.
Each save is a commit, so every change is in the repo history too.

The **Update prices and new cards** workflow runs every morning. It pulls
TCGplayer data from [tcgcsv.com](https://tcgcsv.com), sets each card to its
lowest listed price, adds newly listed cards to their set at 0 owned, and adds
sets released after the newest one tracked. Targets follow the old workbook:
four copies of base cards, ten of each DON!! card, and one of each alternate art,
promo and sealed product.
To leave a new set out, add its group id to `excludedGroups` in `data/meta.json`
and remove it from `data/sets.json` and `data/cards/`. To drop a single card for
good, delete its line and add its `productId` to `excludedProducts`.

## Setup

1. In **Settings → Pages**, set **Source** to **GitHub Actions**.
2. Run the **Deploy site** workflow once (later changes under `site/` deploy on their own).
3. Optionally run **Update prices and new cards** to switch from the imported
   market prices to lowest listed prices right away.

On a phone, open the site and use **Share → Add to Home Screen** (iPhone) or
**Install app** (Android). It then opens full screen and shows the last loaded
collection when offline.

## Local preview

```sh
python3 -m http.server 8000
# open http://localhost:8000/site/  (reads data/ from this checkout)
```
