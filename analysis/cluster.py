"""Assemble the wallet-cluster / funding forensics into cluster.json (deterministic).

Derives the wash-bot set from the committed flagged-pool trade snapshots, attaches
each bot's funding origin + seed (from the committed RPC traces), reconstructs the
per-pool creation chains from the funding edges, and flags wallets that wash more
than one pool and sibling wallets that run identical parameters.
"""
import os
import sys
import glob
import statistics
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

    # every pool tape, not just the flagged ones: a routed swap can land in any of them
    raw = {os.path.basename(p)[:-5]: read_json(p)["trades"]
           for p in glob.glob(os.path.join(ROOT, "data", "raw", "trades", "*.json"))}

    # Aggregator routing: one signed transaction split across pools shows up in several tapes, so
    # a wallet can look like it trades several pools when one routed swap put it there. Measure it,
    # and keep it apart from what would be arbitrage: legs on opposite sides in the same tx.
    tx_legs = defaultdict(list)
    for slug, trades in raw.items():
        for t in trades:
            tx_legs[t["tx_hash"]].append((slug, str(t.get("kind", "")).lower(),
                                          float(t["volume_in_usd"]), t.get("tx_from_address")))
    def n_pools(tx):
        return len({s for s, _k, _u, _w in tx_legs[tx]})

    bot_usd = bot_routed_usd = 0.0
    bot_multi_tx, bot_mixed_tx = set(), set()
    own_pools = defaultdict(set)          # pools a wallet reaches WITHOUT a routed leg
    for slug, trades in raw.items():
        for t in trades:
            w = t.get("tx_from_address")
            if w not in all_bots:
                continue
            usd, tx = float(t["volume_in_usd"]), t["tx_hash"]
            bot_usd += usd
            if n_pools(tx) > 1:
                bot_routed_usd += usd
                bot_multi_tx.add(tx)
                if len({k for _s, k, _u, _w in tx_legs[tx]}) > 1:
                    bot_mixed_tx.add(tx)
            else:
                own_pools[w].add(slug)
    routing = dict(
        multi_pool_tx_in_snapshot=sum(1 for tx in tx_legs if n_pools(tx) > 1),
        total_tx_in_snapshot=len(tx_legs),
        # legs on opposite sides = cross-pool arbitrage. It exists here; it is just not the bots'.
        mixed_side_tx_in_snapshot=sum(1 for tx in tx_legs if n_pools(tx) > 1
                                      and len({k for _s, k, _u, _w in tx_legs[tx]}) > 1),
        bot_multi_pool_tx=len(bot_multi_tx),
        bot_mixed_side_tx=len(bot_mixed_tx),
        bot_routed_usd_share=round(bot_routed_usd / bot_usd, 4) if bot_usd else 0.0,
        # wallets reaching several pools in their own transactions, not as legs of one routed swap
        multi_pool_by_own_tx={w: sorted(p) for w, p in own_pools.items() if len(p) > 1})

    # A wallet can arb two pools minutes apart, with no transaction straddling both. That leaves
    # it buy-heavy in one and sell-heavy in the other, so check for that directly.
    side_usd = defaultdict(lambda: [0.0, 0.0])
    for slug, trades in raw.items():
        for t in trades:
            w = t.get("tx_from_address")
            if w not in all_bots:
                continue
            usd = float(t["volume_in_usd"])
            side_usd[(w, slug)][0 if str(t.get("kind", "")).lower().startswith("buy") else 1] += usd
    lean = defaultdict(dict)              # wallet -> pool -> signed imbalance (+ = buy-heavy)
    for (w, slug), (b, s) in side_usd.items():
        if b + s < 500:                   # ignore dust legs
            continue
        lean[w][slug] = round((b - s) / max(b, s), 4)
    directional = {w: v for w, v in lean.items()
                   if any(x > 0.10 for x in v.values()) and any(x < -0.10 for x in v.values())}
    routing["cross_pool_directional_bots"] = sorted(directional)

    # the fleet count must not rest on routing: recount without wallets that only appear as legs
    own_bots = {}
    for slug in FLAGGED:
        keep = []
        for b in pools[slug]["bots"]:
            w = b["wallet"]
            if any(t.get("tx_from_address") == w and n_pools(t["tx_hash"]) == 1 for t in raw[slug]):
                keep.append(w)
        own_bots[pools[slug]["key"]] = keep
    routing["own_tx_bots_per_flagged_pool"] = {k: len(v) for k, v in own_bots.items()}
    routing["min_own_tx_bots_in_a_flagged_pool"] = min(len(v) for v in own_bots.values())
    routing["per_pool_imbalance"] = {f"{w[:8]}/{s.split('__')[0]}/{s.split('__')[1]}": v
                                     for w, d in lean.items() for s, v in d.items()}

    # equal dollars in and out do not prove equal shares in and out. The tape carries the token
    # amounts, so net each bot's xStock units per symbol and compare with what it turned over.
    units = defaultdict(lambda: [0.0, 0.0])   # (wallet, symbol) -> [net, gross]
    for slug, trades in raw.items():
        sym = slug.split("__")[0]
        for t in trades:
            w = t.get("tx_from_address")
            if w not in all_bots:
                continue
            got = float(t.get("to_token_amount") or 0)     # units received on a buy
            gave = float(t.get("from_token_amount") or 0)  # units given up on a sell
            if str(t.get("kind", "")).lower().startswith("buy"):
                units[(w, sym)][0] += got; units[(w, sym)][1] += got
            else:
                units[(w, sym)][0] -= gave; units[(w, sym)][1] += gave
    resid = {f"{w[:8]}/{sym}": round(abs(net) / gross, 4)
             for (w, sym), (net, gross) in units.items() if gross > 0}
    routing["token_flatness"] = dict(
        worst_abs_net_over_gross=max(resid.values()),
        median_abs_net_over_gross=round(statistics.median(resid.values()), 4),
        per_bot=dict(sorted(resid.items(), key=lambda kv: -kv[1])))
    write_json(routing, os.path.join(ROOT, "routing.json"), indent=2)

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
