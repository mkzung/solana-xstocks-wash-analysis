"""Assemble the wallet-cluster / funding forensics into cluster.json (deterministic).

Derives the wash-bot set from the committed flagged-pool trade snapshots, attaches
each bot's funding origin + seed (from the committed RPC traces), reconstructs the
per-pool creation chains from the funding edges, and flags wallets that wash more
than one pool and sibling wallets that run identical parameters.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics_lib import wallet_ledger, is_wash_bot
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAWT = os.path.join(ROOT, "data", "raw", "trades")
RAWW = os.path.join(ROOT, "data", "raw", "wallets")

FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def bots_in(slug):
    d = read_json(os.path.join(RAWT, slug + ".json"))
    led = wallet_ledger(d["trades"])
    out = []
    for w, (b, s, bu, su) in led.items():
        if is_wash_bot(b, s, bu, su):
            out.append(dict(wallet=w, buys=b, sells=s, buy_usd=round(bu), sell_usd=round(su),
                            matched_usd=round(2 * min(bu, su)), balance=round(min(bu, su) / max(bu, su), 3)))
    out.sort(key=lambda r: -r["matched_usd"])
    return d["meta"], out


def trace(w):
    fn = os.path.join(RAWW, w + ".json")
    return read_json(fn) if os.path.exists(fn) else None


def main():
    edges = {}
    if os.path.exists(os.path.join(ROOT, "data", "funding_edges.json")):
        for f, w, seed, nsig in read_json(os.path.join(ROOT, "data", "funding_edges.json"))["edges"]:
            edges[w] = dict(parent=f, seed=seed)

    pools = {}
    wallet_pools = defaultdict(list)
    all_bots = set()
    for slug in FLAGGED:
        meta, bots = bots_in(slug)
        key = meta["sym"] + "/" + meta["dex"] + "/" + slug.split("__")[2]   # pool id keeps the two SPYX/orca pools distinct
        for bt in bots:
            tr = trace(bt["wallet"])
            bt["origin"] = (tr or {}).get("funder")
            bt["seed"] = (tr or {}).get("seed_amount")
            bt["n_txs"] = (tr or {}).get("n_sigs")
            bt["first_ts"] = (tr or {}).get("first_ts")
            wallet_pools[bt["wallet"]].append(key)
            all_bots.add(bt["wallet"])
        pools[slug] = dict(pool=meta, key=key, n_bots=len(bots), bots=bots,
                           bot_matched_usd=sum(b["matched_usd"] for b in bots))

    # creation chains: follow each bot up through the funding edges
    def chain(w):
        path = [w]
        seen = {w}
        while w in edges and edges[w]["parent"] and edges[w]["parent"] not in seen:
            w = edges[w]["parent"]; path.append(w); seen.add(w)
        return path

    chains = {slug: [chain(b["wallet"]) for b in pools[slug]["bots"]] for slug in FLAGGED}
    multi = {w: ps for w, ps in wallet_pools.items() if len(set(ps)) > 1}

    # sibling fleets: bots in the same pool with the same trade count and seed within a tight band
    siblings = {}
    for slug in FLAGGED:
        groups = defaultdict(list)
        for b in pools[slug]["bots"]:
            groups[(b["buys"], b["sells"])].append(b["wallet"])
        sib = {f"{k[0]}b/{k[1]}s": v for k, v in groups.items() if len(v) >= 2}
        if sib:
            siblings[pools[slug]["key"]] = sib

    out = dict(
        snapshot="2026-06-21", n_flagged_pools=len(FLAGGED), n_named_bots=len(all_bots),
        total_bot_matched_usd=round(sum(p["bot_matched_usd"] for p in pools.values())),
        pools={pools[s]["key"]: dict(n_bots=pools[s]["n_bots"], bots=pools[s]["bots"],
                                     matched_usd=pools[s]["bot_matched_usd"]) for s in FLAGGED},
        creation_chains={pools[s]["key"]: chains[s] for s in FLAGGED},
        multi_pool_wallets=multi, sibling_fleets=siblings,
        funding_edges=edges)
    write_json(out, os.path.join(ROOT, "cluster.json"), indent=2)

    print(f"named wash bots across {len(FLAGGED)} flagged pools: {len(all_bots)}")
    print(f"total matched (manufactured) USD in the snapshots: ${out['total_bot_matched_usd']:,}\n")
    for s in FLAGGED:
        p = pools[s]
        print(f"  {p['key']:14} {p['n_bots']} bots, ${p['bot_matched_usd']:,} matched")
    print(f"\nwallets washing >1 pool: {len(multi)}")
    for w, ps in multi.items():
        print(f"  {w[:14]}.. -> {sorted(set(ps))}")
    print("\nsibling fleets (same pool, identical buy/sell counts):")
    for k, sib in siblings.items():
        for params, ws in sib.items():
            print(f"  {k:14} {params}: {len(ws)} wallets")
    print("\nlongest creation chain:")
    longest = max((c for cs in chains.values() for c in cs), key=len)
    print("  " + " <- ".join(w[:8] for w in longest) + f"  ({len(longest)} wallets)")
    print("\nwrote cluster.json")


if __name__ == "__main__":
    main()
