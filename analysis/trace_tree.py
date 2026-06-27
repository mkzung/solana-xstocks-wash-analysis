"""Walk the funding tree upward from the 14 wash bots to find the root(s).

Recursively traces each wallet's originator (the payer of its first transaction)
until reaching wallets that are either high-activity (likely a CEX/aggregator hot
wallet, which we do not expand) or already seen. Builds the edge list and reports
convergence points - a shared root is direct evidence of a single operator.

Resumable: reuses the per-wallet cache written by fund_trace.trace_one.
"""
import os
import sys
import time
from io_util import read_json, write_json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fund_trace import trace_one, OUT

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HOT_WALLET_SIGS = 2000     # at/above this we treat a node as an exchange/aggregator hot wallet and stop
MAX_DEPTH = 6
STATE = "/tmp/tree_state.json"


def main():
    seed = read_json("/tmp/wash_wallets.json")
    state = read_json(STATE) if os.path.exists(STATE) else {"edges": [], "done": []}
    edges = {tuple(e[:2]): e for e in state["edges"]}
    done = set(state["done"])

    frontier = set(seed)
    for depth in range(MAX_DEPTH):
        nxt = set()
        for w in sorted(frontier):
            if w in done:
                rec = read_json(os.path.join(OUT, w + ".json")) if os.path.exists(os.path.join(OUT, w + ".json")) else None
            else:
                rec, _ = trace_one(w)
                done.add(w)
                time.sleep(0.2)
            if not rec or not rec.get("funder"):
                write_json({"edges": list(edges.values()), "done": sorted(done)}, STATE)
                continue
            f = rec["funder"]
            edges[(f, w)] = [f, w, rec.get("seed_amount"), rec.get("n_sigs")]
            # expand the parent only if we have not seen it and the child was not a hot wallet
            if f not in done and rec.get("n_sigs", 0) < HOT_WALLET_SIGS:
                nxt.add(f)
            write_json({"edges": list(edges.values()), "done": sorted(done)}, STATE)   # save per wallet
        write_json({"edges": list(edges.values()), "done": sorted(done)}, STATE)
        frontier = nxt - done
        print(f"depth {depth}: traced, frontier now {len(frontier)}")
        if not frontier:
            break

    # report: in-degree of each parent (how many wallets it originated) = convergence
    from collections import defaultdict
    children = defaultdict(list)
    sigcount = {}
    for f, w, seed_amt, nsig in edges.values():
        children[f].append(w)
    for w in done:
        fn = os.path.join(OUT, w + ".json")
        if os.path.exists(fn):
            sigcount[w] = read_json(fn).get("n_sigs")
    print(f"\n{len(edges)} funding edges, {len(done)} wallets traced")
    print("\nparents by number of wallets they originated (convergence points):")
    for f, kids in sorted(children.items(), key=lambda kv: -len(kv[1])):
        if len(kids) >= 2:
            print(f"  {f}  originated {len(kids)} wallets  (its own sigs: {sigcount.get(f,'?')})")
    write_json({"edges": list(edges.values())}, os.path.join(ROOT, "data", "funding_edges.json"), indent=1)
    print("\nwrote data/funding_edges.json")


if __name__ == "__main__":
    main()
