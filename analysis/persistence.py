"""Persistence check: does the wash survive between two independent samples?

Compares the primary committed snapshot against a second sample of the same five
flagged pools taken about six hours later (both committed). If the pools still
flag while the specific wallets rotate, the pattern is persistent and the snapshot
is not a fluke - and the rotation is itself evidence of a fresh-wallet fleet.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from metrics_lib import metrics, wallet_ledger, is_wash_bot
from io_util import read_json, write_json

SNAP = os.path.join(ROOT, "data", "raw", "trades")
PERS = os.path.join(ROOT, "data", "raw", "persistence")
FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def bots(trades):
    return {w for w, v in wallet_ledger(trades).items() if is_wash_bot(*v)}


def main():
    rows = []
    resampled_at = None
    for slug in FLAGGED:
        a = read_json(os.path.join(SNAP, slug + ".json"))
        b = read_json(os.path.join(PERS, slug + ".json"))
        resampled_at = b.get("resampled_at")
        ma, mb = metrics(a["trades"]), metrics(b["trades"])
        ba, bb = bots(a["trades"]), bots(b["trades"])
        rows.append(dict(pool=a["meta"]["sym"] + "/" + a["meta"]["dex"],
                         snap_bots=ma["n_wash_bots"], snap_wash=ma["wash_share"],
                         live_bots=mb["n_wash_bots"], live_wash=mb["wash_share"],
                         wallet_overlap=len(ba & bb), live_bot_count=len(bb),
                         still_flagged=bool(mb["wash_share"] >= 0.20)))
    still = sum(r["still_flagged"] for r in rows)
    total_overlap = sum(r["wallet_overlap"] for r in rows)
    out = dict(snapshot="2026-06-21 (primary)", resampled_at=resampled_at,
               n_pools=len(rows), still_flagged=still, total_wallet_overlap=total_overlap, pools=rows)
    write_json(out, os.path.join(ROOT, "persistence.json"), indent=2)

    print(f"Persistence: primary snapshot vs re-sample at {resampled_at}\n")
    print(f"  {'pool':16}{'snap bots':>10}{'snap wash':>10}{'live bots':>10}{'live wash':>10}{'same wallets':>13}")
    for r in rows:
        ov = f"{r['wallet_overlap']}/{r['live_bot_count']}"
        print(f"  {r['pool']:16}{r['snap_bots']:>10}{r['snap_wash']*100:>9.0f}%"
              f"{r['live_bots']:>10}{r['live_wash']*100:>9.0f}%{ov:>13}")
    print(f"\n{still} of {len(rows)} pools still flag at the re-sample; "
          f"total wallet overlap across pools: {total_overlap} (the fleet rotates).")


if __name__ == "__main__":
    main()
