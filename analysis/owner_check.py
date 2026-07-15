"""Confirm each named wash bot is a System-Program-owned account, i.e. a wallet
(not a program-derived router / AMM / aggregator account), via public Solana RPC.

Network collector, run once to build the committed snapshot. For each named bot it
calls getAccountInfo and records the account owner. An ordinary wallet account is
owned by the System Program (11111111111111111111111111111111); a router/PDA/program
account is owned by some program id. This distinguishes a wallet from a program - it
does NOT by itself prove the key is on-curve. Output: data/raw/wallet_owners.json,
which analysis/verify.py then checks offline (so the "wallet, not a router" claim in
the post recomputes deterministically from committed data, key-less).
"""
import os
import sys
import json
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "raw")

SYSTEM_PROGRAM = "11111111111111111111111111111111"
RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")


def owner(wallet, tries=5):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getAccountInfo",
                       "params": [wallet, {"encoding": "base64"}]}).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body,
                                         headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            r = json.loads(urllib.request.urlopen(req, timeout=30).read())
            return ((r.get("result") or {}).get("value") or {}).get("owner")
        except Exception:
            time.sleep(1 + k)
    return None


def named_bots():
    c = read_json(os.path.join(ROOT, "cluster.json"))
    seen, order = set(), []
    for p in c["pools"].values():
        for b in p["bots"]:
            if b["wallet"] not in seen:
                seen.add(b["wallet"]); order.append(b["wallet"])
    return order


def main():
    bots = named_bots()
    owners = {}
    for w in bots:
        o = owner(w)
        owners[w] = o
        print(f"  {w[:10]}.. owner {o}{'  (System Program)' if o == SYSTEM_PROGRAM else ''}")
        time.sleep(0.2)
    out = dict(snapshot="2026-06-21", rpc=RPC, system_program=SYSTEM_PROGRAM, owners=owners)
    write_json(out, os.path.join(OUT, "wallet_owners.json"), indent=2)
    n_sys = sum(1 for o in owners.values() if o == SYSTEM_PROGRAM)
    print(f"\n{n_sys}/{len(bots)} named bots are System-Program-owned accounts (not routers)")
    print("wrote data/raw/wallet_owners.json")


if __name__ == "__main__":
    main()
