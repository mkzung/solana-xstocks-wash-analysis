"""Aggregate the committed per-wallet swap histories into lifetime washing totals.

Reads data/raw/wallet_swaps/*.json (collected by wallet_history.py from the Helius
enhanced API: each named bot's full xStock<->stablecoin swap record, classified from
the wallet's NET token-balance change per transaction). Writes lifetime.json with
per-bot and overall totals. Deterministic over the committed swap files - CI reruns it.

Note on scope: matched_usd here is the wallet's total stablecoin cycled across ALL its
xStock swaps and pools, computed from net balance changes. This captures DEX-aggregator
swaps that a per-pool trade tape (GeckoTerminal) only partly attributes, so it is a
fuller measure than - and a different scope from - the in-window per-pool floor in
temporal.json. Both are reported in the post.
"""
import os
import csv
import glob
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SW = os.path.join(ROOT, "data", "raw", "wallet_swaps")


def main():
    bots = []
    for f in sorted(glob.glob(os.path.join(SW, "*.json"))):
        d = read_json(f)
        s = d.get("swaps", [])
        if not s:
            continue
        nb = sum(1 for x in s if x["side"] == "buy")
        bu = sum(x["usd"] for x in s if x["side"] == "buy")
        su = sum(x["usd"] for x in s if x["side"] == "sell")
        ts = [x["ts"] for x in s if x["ts"]]
        # 2 * min(buys, sells) over all swaps could net a buy of one xStock against a sale of
        # another. Carry the per-symbol figure too: if they agree, no cross-asset netting happened.
        matched_within = 0.0
        for sym in {x["sym"] for x in s}:
            leg = [x for x in s if x["sym"] == sym]
            matched_within += 2 * min(sum(x["usd"] for x in leg if x["side"] == "buy"),
                                      sum(x["usd"] for x in leg if x["side"] == "sell"))
        bots.append(dict(
            wallet=d["wallet"], n_swaps=len(s), buys=nb, sells=len(s) - nb,
            buy_usd=round(bu), sell_usd=round(su), matched_usd=round(2 * min(bu, su)),
            matched_usd_within_symbol=round(matched_within),
            span_days=round((max(ts) - min(ts)) / 86400, 1) if ts else 0.0,
            first=min(ts) if ts else None, last=max(ts) if ts else None,
            syms="+".join(sorted(set(x["sym"] for x in s)))))
    bots.sort(key=lambda b: -b["matched_usd"])
    out = dict(
        snapshot="2026-06-21", n_bots=len(bots),
        total_swaps=sum(b["n_swaps"] for b in bots),
        total_matched_usd=sum(b["matched_usd"] for b in bots),
        total_matched_usd_within_symbol=sum(b["matched_usd_within_symbol"] for b in bots),
        max_bot=bots[0]["wallet"] if bots else None,
        max_bot_matched_usd=bots[0]["matched_usd"] if bots else 0,
        max_span_days=max((b["span_days"] for b in bots), default=0),
        bots=bots)
    write_json(out, os.path.join(ROOT, "lifetime.json"), indent=2)

    # flat per-wallet CSV for the article bundle (commit processed datasets in-directory)
    cols = ["wallet", "n_swaps", "buys", "sells", "buy_usd", "sell_usd", "matched_usd", "span_days", "syms"]
    with open(os.path.join(ROOT, "data", "lifetime.csv"), "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for b in bots:
            writer.writerow({c: b[c] for c in cols})

    print(f"{out['n_bots']} named bots, {out['total_swaps']} lifetime swaps, "
          f"${out['total_matched_usd']:,} matched (net stablecoin cycled)")
    if out["max_bot"]:
        print(f"largest single wallet: {out['max_bot'][:10]}.. ${out['max_bot_matched_usd']:,}")
    print(f"every bot's wash activity spans <= {out['max_span_days']} days (bursty)\n")
    for b in bots:
        print(f"  {b['wallet'][:10]}.. {b['n_swaps']:>4} swaps  ${b['matched_usd']:>11,}  "
              f"{b['span_days']:>4}d  {b['syms']}")


if __name__ == "__main__":
    main()
