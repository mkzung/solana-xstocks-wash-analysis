"""Trace each wash-bot wallet to its funding source via free Solana RPC.

For every wallet: walk getSignaturesForAddress back to its oldest transaction
(activity span + count), then read that first transaction to find who sent it its
initial SOL (the funder). Shared funders across the fleet are coordination evidence.

Caches one file per wallet to data/raw/wallets/ so it is resumable and the
analysis is deterministic over committed data.
"""
import os
import json
import time
import urllib.request
import urllib.error
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "data", "raw", "wallets")
os.makedirs(OUT, exist_ok=True)
ENDPOINTS = ["https://api.mainnet-beta.solana.com", "https://solana-rpc.publicnode.com"]
MAX_PAGES = 2             # cap history walk (2k sigs) to bound runtime; note if capped


def rpc(method, params, tries=5):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for i in range(tries):
        ep = ENDPOINTS[i % len(ENDPOINTS)]
        try:
            req = urllib.request.Request(ep, data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
            r = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if "result" in r:
                return r["result"]
            time.sleep(1 + i)
        except urllib.error.HTTPError:
            time.sleep(2 + 2 * i)
        except Exception:
            time.sleep(1 + i)
    return None


def all_signatures(wallet):
    sigs = []
    before = None
    for _ in range(MAX_PAGES):
        params = [wallet, {"limit": 1000}] if not before else [wallet, {"limit": 1000, "before": before}]
        page = rpc("getSignaturesForAddress", params)
        if not page:
            break
        sigs.extend(page)
        if len(page) < 1000:
            return sigs, False
        before = page[-1]["signature"]
        time.sleep(0.3)
    return sigs, True    # capped


STABLES = {"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
           "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC"}


def find_funder(wallet, oldest_sig):
    """Read the wallet's oldest transaction and identify who originated it.

    For a fresh wallet, the fee-payer/first-signer of its earliest transaction is
    the originator: that party paid to create the wallet's token account and seed
    it. Returns (originator, method, seed_amount, seed_token). Falls back to the
    seed transfer's authority if the wallet itself signed first.
    """
    tx = rpc("getTransaction", [oldest_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
    if not tx:
        return None, "no_tx", None, None
    msg = tx["transaction"]["message"]
    ak = msg["accountKeys"]
    signer = next((k["pubkey"] for k in ak if isinstance(k, dict) and k.get("signer")), None)

    # find a stablecoin seed transfer in this tx (the funding amount)
    seed_amt, seed_tok, seed_auth = None, None, None

    def scan(instrs):
        nonlocal seed_amt, seed_tok, seed_auth
        for ix in instrs or []:
            p = ix.get("parsed") if isinstance(ix, dict) else None
            if isinstance(p, dict) and p.get("type") in ("transfer", "transferChecked"):
                info = p.get("info", {})
                amt = info.get("amount") or (info.get("tokenAmount") or {}).get("amount")
                mint = info.get("mint")
                if amt:
                    try:
                        val = int(amt) / 1e6
                    except (TypeError, ValueError):
                        continue
                    seed_amt = round(val, 2)
                    seed_tok = STABLES.get(mint, mint[:6] if mint else "?")
                    seed_auth = info.get("authority") or info.get("source")
    scan(msg.get("instructions"))
    for inner in (tx.get("meta", {}) or {}).get("innerInstructions", []) or []:
        if seed_amt is None:
            scan(inner.get("instructions"))

    originator = signer if (signer and signer != wallet) else seed_auth
    method = "first_signer" if (signer and signer != wallet) else ("seed_authority" if seed_auth else "self")
    return originator, method, seed_amt, seed_tok


def trace_one(w):
    fn = os.path.join(OUT, w + ".json")
    if os.path.exists(fn):
        return read_json(fn), True
    sigs, capped = all_signatures(w)
    if not sigs:
        return None, False
    oldest = sigs[-1]
    funder, method, seed_amt, seed_tok = find_funder(w, oldest["signature"])
    rec = dict(wallet=w, n_sigs=len(sigs), capped=capped,
               first_ts=oldest.get("blockTime"), last_ts=sigs[0].get("blockTime"),
               oldest_sig=oldest["signature"], funder=funder, funder_method=method,
               seed_amount=seed_amt, seed_token=seed_tok)
    write_json(rec, fn, indent=1)
    return rec, False


def main():
    wallets = read_json("/tmp/wash_wallets.json")
    print(f"tracing {len(wallets)} wash-bot wallets\n")
    for w in wallets:
        rec, cached = trace_one(w)
        if not rec:
            print(f"  ERR     {w[:8]}.. no sigs"); continue
        seed = f"{rec['seed_amount']} {rec['seed_token']}" if rec.get("seed_amount") else "?"
        print(f"  {'cached' if cached else 'traced'}  {w[:8]}.. {rec['n_sigs']} sigs  "
              f"originator {str(rec['funder'])[:8]} ({rec['funder_method']}) seed {seed}")
        if not cached:
            time.sleep(0.3)


if __name__ == "__main__":
    main()
