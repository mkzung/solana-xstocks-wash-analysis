"""Flatten the flagged-pool wash-bot set into data/named_wallets.json (deterministic).

One row per (wallet, flagged pool) that the detector marks a wash bot, with a sample
transaction hash, ordered by matched USD. The dashboard reads this file for its wallet
table and the post's Appendix cites it. It recomputes from the committed trade snapshots,
so verify.py can assert it matches the detector exactly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics_lib import wallet_ledger, is_wash_bot
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAWT = os.path.join(ROOT, "data", "raw", "trades")

FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def first_tx(trades, wallet):
    """Earliest transaction hash of `wallet` in this pool (a sample to paste into an explorer)."""
    hits = sorted((t.get("block_timestamp") or "", t.get("tx_hash") or "")
                  for t in trades if t.get("tx_from_address") == wallet)
    return hits[0][1] if hits else None


def main():
    rows = []
    for slug in FLAGGED:
        d = read_json(os.path.join(RAWT, slug + ".json"))
        pool = d["meta"]["sym"] + "/" + d["meta"]["dex"]
        bots = [(w, b, s, bu, su) for w, (b, s, bu, su) in wallet_ledger(d["trades"]).items()
                if is_wash_bot(b, s, bu, su)]
        bots.sort(key=lambda r: -2 * min(r[3], r[4]))
        for w, b, s, bu, su in bots:
            # pool_id keeps the two distinct SPYX/orca pools apart (the display "pool" string collides)
            rows.append(dict(pool=pool, pool_id=d["pool"], wallet=w, buys=b, sells=s,
                             buy_usd=round(bu), sell_usd=round(su),
                             sample_tx=first_tx(d["trades"], w)))
    write_json(rows, os.path.join(ROOT, "data", "named_wallets.json"), indent=1)
    print(f"{len(rows)} (wallet, pool) wash-bot rows, {len({r['wallet'] for r in rows})} distinct wallets")
    print("wrote data/named_wallets.json")


if __name__ == "__main__":
    main()
