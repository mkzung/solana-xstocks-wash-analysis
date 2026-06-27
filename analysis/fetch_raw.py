"""Fetch + cache the raw on-chain dataset for the analysis (free, key-less).

Point-in-time snapshot (2026-06-21). Caches GeckoTerminal tx-level trades and
OHLCV per pool to data/raw/ so the analysis + tests run deterministically over
committed data. Resumable (skips files already present); rate-limit aware.

Sources, all free and without an API key:
  Dexscreener      universe + turnover snapshot      -> data/universe.json (already pulled)
  GeckoTerminal    300 recent tx-level trades / pool  (wallet + tx hash + side + USD)
  GeckoTerminal    daily + hourly OHLCV / pool        (volume time series)
"""
import os
import json
import time
import urllib.request
import urllib.error
from io_util import read_json, write_json

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "data", "raw")
os.makedirs(os.path.join(RAW, "trades"), exist_ok=True)
os.makedirs(os.path.join(RAW, "ohlcv"), exist_ok=True)
NET = "solana"
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
MIN_VOL = 50000          # only pools with real 24h activity


def get(url, tries=4):
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=12).read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 + 2 * i); continue
            raise
        except Exception:
            time.sleep(1 + i)
    raise RuntimeError("failed: " + url)


def slug(p, addr):
    return f"{p['sym']}__{p['dex']}__{addr[:8]}"


def main():
    universe = read_json(os.path.join(ROOT, "data", "universe.json"))
    pools = {a: p for a, p in universe.items() if (p.get("vol") or 0) >= MIN_VOL}
    print(f"{len(pools)} pools with 24h vol >= ${MIN_VOL:,}")
    for addr, p in sorted(pools.items(), key=lambda kv: -(kv[1].get("vol") or 0)):
        tf = os.path.join(RAW, "trades", slug(p, addr) + ".json")
        if not os.path.exists(tf):
            try:
                d = get(f"https://api.geckoterminal.com/api/v2/networks/{NET}/pools/{addr}/trades")["data"]
                write_json({"pool": addr, "meta": p, "trades": [t["attributes"] for t in d]}, tf)
                print(f"  trades  {slug(p, addr):34} {len(d)}")
                time.sleep(1.1)
            except Exception as e:
                print(f"  trades  {slug(p, addr):34} ERR {str(e)[:40]}")
        for tfr in ("day", "hour"):
            of = os.path.join(RAW, "ohlcv", f"{slug(p, addr)}__{tfr}.json")
            if os.path.exists(of):
                continue
            try:
                d = get(f"https://api.geckoterminal.com/api/v2/networks/{NET}/pools/{addr}/ohlcv/{tfr}?aggregate=1&limit=1000")
                ol = d["data"]["attributes"]["ohlcv_list"]
                write_json({"pool": addr, "meta": p, "tf": tfr, "ohlcv": ol}, of)
                print(f"  ohlcv   {slug(p, addr):34} {tfr} {len(ol)} bars")
                time.sleep(1.1)
            except Exception as e:
                print(f"  ohlcv   {slug(p, addr):34} {tfr} ERR {str(e)[:40]}")


if __name__ == "__main__":
    main()
