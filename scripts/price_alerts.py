"""Discord price alerts, run right after the daily price update.

- Cards you own: posts when a card's price has moved by `movePct` or more since the
  last time it was alerted on (or since it was first tracked). Measuring from the last
  alert, not from yesterday, means a slow climb still alerts once it adds up, and a
  card is not posted again until it moves that much further. Cards under `minPrice`
  both before and after are skipped so bulk commons stay quiet.
- Price targets: posts when a card falls to or under the price set for it on the site
  (data/price-alerts.json `targets`), once per dip; it can post again after the price
  goes back above the target.

Settings live in data/price-alerts.json; what the job last saw lives in
data/price-alert-state.json. Messages go to --discord (one webhook message per line).

Usage: python3 scripts/price_alerts.py [--dry-run] [--discord PATH] [--test]
"""
import json
import sys
from datetime import datetime, timezone

from common import DATA, dump_rows, money_round, read_json, write_text

SETTINGS = f"{DATA}/price-alerts.json"
STATE = f"{DATA}/price-alert-state.json"
SITE = "https://reidsord.github.io/optcg/"
DEFAULTS = {"movePct": 0.15, "minPrice": 5, "targets": {}}
MAX_LINES = 20  # per embed, so a wild day stays readable
UP, DOWN, TARGET = 0x2EAD6B, 0xD9534F, 0xD9B44A


def load_cards():
    out = []
    for s in read_json(f"{DATA}/sets.json", []):
        for c in read_json(f"{DATA}/cards/{s['file']}", []):
            out.append({**c, "set": s["code"]})
    return out


def money(x):
    return f"${x:,.2f}"


def tcg(c):
    return f"https://www.tcgplayer.com/product/{c['productId']}"


def label(c):
    bits = [b for b in (c.get("cardId"), c["set"]) if b]
    return f"[{c['name']}]({tcg(c)})" + (f" · {' · '.join(dict.fromkeys(bits))}" if bits else "")


def check(cards, settings, state):
    """Return (moves, hits, new_state). Moves are (card, before, after); hits are (card, target)."""
    move_pct, min_price = settings["movePct"], settings["minPrice"]
    targets = {int(p): t for p, t in (settings.get("targets") or {}).items() if t is not None}
    old = {r["p"]: r for r in state}
    new, moves, hits = {}, [], []
    seen = set()
    for c in cards:
        p, price = c["productId"], c.get("price")
        if p in seen or price is None:
            continue
        seen.add(p)
        row = {"p": p}
        prev = old.get(p, {})
        if (c.get("qty") or 0) > 0 and price > 0:
            base = prev.get("base")
            if base and abs(price - base) / base >= move_pct and max(price, base) >= min_price:
                moves.append((c, base, price))
                base = price
            row["base"] = base if base else price
        if p in targets:
            below = price <= targets[p]
            if below and not prev.get("below"):
                hits.append((c, targets[p]))
            if below:
                row["below"] = True
        if len(row) > 1:
            new[p] = row
    return moves, hits, [new[p] for p in sorted(new)]


def move_line(c, before, after):
    pct = (after - before) / before
    qty = c.get("qty") or 0
    arrow = "▲" if after > before else "▼"
    return (f"{arrow} **{abs(pct):.0%}** {label(c)}\n"
            f"{money(before)} → **{money(after)}** · you own {qty} ({'+' if after > before else '−'}{money(abs(after - before) * qty)})")


def hit_line(c, target):
    have = c.get("qty") or 0
    return f"{label(c)}\nNow **{money(c['price'])}**, at or under your {money(target)} target · you own {have}"


def embed(title, color, lines, total):
    more = total - len(lines)
    desc = "\n\n".join(lines)
    if more > 0:
        desc += f"\n\n…and {more} more on [the site]({SITE})."
    return {"title": title[:256], "color": color, "description": desc[:4096], "url": SITE}


def discord_payloads(moves, hits, today, test=False):
    ups = sorted([m for m in moves if m[2] > m[1]], key=lambda m: -(m[2] - m[1]) * (m[0].get("qty") or 0))
    downs = sorted([m for m in moves if m[2] < m[1]], key=lambda m: (m[2] - m[1]) * (m[0].get("qty") or 0))
    embeds = []
    if hits:
        embeds.append(embed(f"{len(hits)} card{'s' * (len(hits) != 1)} hit your price target", TARGET,
                            [hit_line(*h) for h in hits[:MAX_LINES]], len(hits)))
    if ups:
        embeds.append(embed(f"{len(ups)} card{'s' * (len(ups) != 1)} you own went up", UP,
                            [move_line(*m) for m in ups[:MAX_LINES]], len(ups)))
    if downs:
        embeds.append(embed(f"{len(downs)} card{'s' * (len(downs) != 1)} you own went down", DOWN,
                            [move_line(*m) for m in downs[:MAX_LINES]], len(downs)))
    if not embeds:
        return []
    net = sum((a - b) * (c.get("qty") or 0) for c, b, a in moves)
    content = f"**{'Test: ' if test else ''}Price alerts for {today}**"
    if moves:
        content += f" · net {'+' if net >= 0 else '−'}{money(abs(net))} on the cards below"
    return [{"username": "OPTCG prices", "content": content, "embeds": embeds, "allowed_mentions": {"parse": []}}]


def write_payloads(path, payloads):
    with open(path, "w", encoding="utf-8") as f:
        for payload in payloads:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def test_payloads(cards, settings):
    """A sample built from your most valuable cards, to check the webhook works."""
    owned = sorted([c for c in cards if (c.get("qty") or 0) > 0 and c.get("price")], key=lambda c: -c["price"] * c["qty"])
    moves = [(c, money_round(c["price"] / (1 + settings["movePct"])), c["price"]) for c in owned[:2]]
    moves += [(c, money_round(c["price"] / (1 - settings["movePct"])), c["price"]) for c in owned[2:3]]
    hits = [(c, money_round(c["price"] + 1)) for c in owned[3:4]]
    return discord_payloads(moves, hits, datetime.now(timezone.utc).date().isoformat(), test=True)


def main(args):
    settings = {**DEFAULTS, **read_json(SETTINGS, {})}
    cards = load_cards()
    discord = args[args.index("--discord") + 1] if "--discord" in args else None
    if "--test" in args:
        payloads = test_payloads(cards, settings)
        if discord:
            write_payloads(discord, payloads)
        print(json.dumps(payloads, ensure_ascii=False, indent=2)[:3000])
        return 0

    state = read_json(STATE, None)
    first_run = state is None
    moves, hits, new_state = check(cards, settings, state or [])
    if first_run:
        moves, hits = [], []  # the first run only records where prices start
        print("First run: recorded starting prices, nothing to alert on yet.")
    today = datetime.now(timezone.utc).date().isoformat()
    payloads = discord_payloads(moves, hits, today)
    print(f"{len(moves)} owned-card moves of {settings['movePct']:.0%}+ (cards from {money(settings['minPrice'])}), "
          f"{len(hits)} price-target hits, tracking {len(new_state)} cards")
    for c, before, after in moves:
        print(f"  move: {c['set']} {c.get('cardId', '')} {c['name']}: {money(before)} -> {money(after)}")
    for c, target in hits:
        print(f"  target: {c['set']} {c.get('cardId', '')} {c['name']}: {money(c['price'])} <= {money(target)}")
    if "--dry-run" in args:
        if payloads:
            print("Discord sample:", json.dumps(payloads[0], ensure_ascii=False)[:1500])
        return 0
    write_text(STATE, dump_rows(new_state))
    if discord and payloads:
        write_payloads(discord, payloads)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
