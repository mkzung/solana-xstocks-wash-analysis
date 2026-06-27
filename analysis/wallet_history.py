"""Reconstruct each named wash bot's full xStock swap history via the Helius
Enhanced Transactions API.

For each named bot this pages the address's transaction history and classifies
every transaction from the wallet's NET token-balance change
(accountData.tokenBalanceChanges): an xStock-token leg against a stablecoin leg
is a swap (a buy if the wallet received the xStock, a sell if it sent it; the USD
size is the stablecoin leg). The net change cancels the routing / change /
aggregator legs that the gross tokenTransfers list would double-count. Every swap
is recorded so the in-window slice can be cross-checked against the committed
GeckoTerminal trades; analysis/lifetime.py aggregates these files into the
lifetime totals (lifetime.json).

The Helius API key is read from the WH_HELIUS_KEY environment variable and is
never written to a committed file. Output: one file per wallet (its swap list) in
data/raw/wallet_swaps/.
"""
import os
import glob
import json
import time
import urllib.request
import urllib.error
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAWT = os.path.join(ROOT, "data", "raw", "trades")
OUT = os.path.join(ROOT, "data", "raw", "wallet_swaps")
os.makedirs(OUT, exist_ok=True)

KEY = os.environ.get("WH_HELIUS_KEY", "")
BASE = "https://api.helius.xyz/v0/addresses/{}/transactions"
STABLES = {"Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
MAX_PAGES = 60


def get(url, tries=6):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(2 + 2 * k); continue
            return None                      # 4xx other than rate limit: give up on this URL
        except Exception:
            time.sleep(1 + k)
    return None


def classify(tx, wallet, mints):
    """(sym, side, usd) if this tx nets an xStock<->stablecoin swap for `wallet`, else None.

    Uses the wallet's NET token-balance changes (accountData.tokenBalanceChanges), which
    cancel routing/change/intermediate legs - the gross tokenTransfers list double-counts them.
    """
    by, stable = {}, 0.0
    for ad in tx.get("accountData", []):
        for tb in ad.get("tokenBalanceChanges", []):
            if tb.get("userAccount") != wallet:
                continue
            rt = tb.get("rawTokenAmount", {})
            try:
                amt = int(rt.get("tokenAmount", 0)) / 10 ** int(rt.get("decimals", 0))
            except (TypeError, ValueError):
                continue
            mt = tb.get("mint")
            if mt in STABLES:
                stable += amt
            elif mt in mints:
                by[mt] = by.get(mt, 0.0) + amt
    if abs(stable) < 1e-6:
        return None
    for mt, net in by.items():
        if abs(net) > 1e-9 and (net > 0) != (stable > 0):      # opposite legs = a swap
            return mints[mt], ("buy" if net > 0 else "sell"), abs(stable)
    return None


def pull(wallet, mints):
    fn = os.path.join(OUT, wallet + ".json")
    if os.path.exists(fn):
        rec = read_json(fn)
        if rec.get("done"):
            return rec, "cached"
    swaps, seen, before, pages, walked = [], set(), None, 0, 0
    while pages < MAX_PAGES:
        url = BASE.format(wallet) + f"?api-key={KEY}&limit=100" + (f"&before={before}" if before else "")
        d = get(url)
        if d is None:
            return {"_failed": True}, "failed"
        if not d:
            break
        for t in d:
            sig = t.get("signature")
            if sig in seen:
                continue
            seen.add(sig); walked += 1
            c = classify(t, wallet, mints)
            if c:
                swaps.append(dict(ts=t.get("timestamp"), sym=c[0], side=c[1], usd=round(c[2], 2), sig=sig))
        before = d[-1]["signature"]
        pages += 1
        if len(d) < 100:
            break
        time.sleep(0.15)
    rec = dict(wallet=wallet, n_swaps=len(swaps), n_txns_walked=walked, pages=pages, swaps=swaps, done=True)
    tmp = fn + ".tmp"
    write_json(rec, tmp)
    os.replace(tmp, fn)
    return rec, "done"


def named_bots():
    c = read_json(os.path.join(ROOT, "cluster.json"))
    seen, order = set(), []
    for p in c["pools"].values():
        for b in p["bots"]:
            if b["wallet"] not in seen:
                seen.add(b["wallet"]); order.append(b["wallet"])
    return order


def xstock_mints():
    mints = {}
    for f in glob.glob(os.path.join(RAWT, "*.json")):
        if os.path.basename(f).startswith("CTRL_"):
            continue
        m = read_json(f)["meta"]
        if m.get("mint"):
            mints[m["mint"]] = m["sym"]
    return mints


def main():
    if not KEY:
        raise SystemExit("set WH_HELIUS_KEY (Helius API key) in the environment to run the collector")
    bots = named_bots()
    mints = xstock_mints()
    for w in bots:
        rec, status = pull(w, mints)
        if status == "failed":
            print(f"  {w[:10]}.. FAILED (API error), rerun to retry"); continue
        s = rec["swaps"]
        nb = sum(1 for x in s if x["side"] == "buy"); ns = len(s) - nb
        bu = sum(x["usd"] for x in s if x["side"] == "buy"); su = sum(x["usd"] for x in s if x["side"] == "sell")
        ts = [x["ts"] for x in s if x["ts"]]
        span = (max(ts) - min(ts)) / 86400 if ts else 0
        print(f"  {w[:10]}.. {rec['n_swaps']:>4} swaps ({nb}b/{ns}s) ${bu:,.0f}/${su:,.0f} matched ${2*min(bu,su):,.0f} span {span:.1f}d  [{status}]")
    done = sum(1 for w in bots if os.path.exists(os.path.join(OUT, w + ".json")))
    print(f"wallets done: {done}/{len(bots)}")


if __name__ == "__main__":
    main()
