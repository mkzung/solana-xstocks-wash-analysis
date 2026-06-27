"""Temporal + volume forensics: pool age/onset, robotic cadence, manufactured USD.

Reads the committed trade snapshots + OHLCV. Writes temporal.json.

  onset         pool age (days of daily OHLCV) and whether the bots predate the pool
  cadence       for each pool's busiest bots: inter-trade seconds and how regular /
                alternating (buy<->sell) the sequence is - a bot signature
  manufactured  per pool, wash_share x 24h reported volume = manufactured USD/day
"""
import os
import glob
import statistics as st
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAWT = os.path.join(ROOT, "data", "raw", "trades")
RAWO = os.path.join(ROOT, "data", "raw", "ohlcv")
RAWW = os.path.join(ROOT, "data", "raw", "wallets")

import sys
sys.path.insert(0, HERE)
from metrics_lib import wallet_ledger, is_wash_bot, metrics, top_roundtrippers
from io_util import read_json, write_json


def window_hours(trades):
    tt = sorted(t["block_timestamp"] for t in trades if t.get("block_timestamp"))
    return round((ts(tt[-1]) - ts(tt[0])) / 3600, 2) if len(tt) >= 2 else None

FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def pool_age(slug):
    fn = os.path.join(RAWO, slug + "__day.json")
    if not os.path.exists(fn):
        return None
    ol = read_json(fn)["ohlcv"]
    if not ol:
        return None
    times = sorted(o[0] for o in ol)
    days = (times[-1] - times[0]) / 86400
    first = datetime.fromtimestamp(times[0], timezone.utc).date().isoformat()
    return dict(n_days=len(ol), span_days=round(days, 1), first_bar=first,
                vol_total=round(sum(o[5] for o in ol)))


def cadence(trades):
    """For the busiest wash bots: inter-trade seconds and alternation rate."""
    led = wallet_ledger(trades)
    bots = sorted([(w, v) for w, v in led.items() if is_wash_bot(*v)], key=lambda kv: -(kv[1][0] + kv[1][1]))
    out = []
    for w, _ in bots[:3]:
        seq = sorted([(ts(t["block_timestamp"]), t["kind"]) for t in trades if t.get("tx_from_address") == w])
        if len(seq) < 4:
            continue
        gaps = [round(seq[i + 1][0] - seq[i][0], 1) for i in range(len(seq) - 1)]
        kinds = [k for _, k in seq]
        alt = sum(1 for i in range(len(kinds) - 1) if kinds[i] != kinds[i + 1]) / (len(kinds) - 1)
        med = st.median(gaps)
        out.append(dict(wallet=w, n=len(seq), median_gap_s=med,
                        gap_iqr_s=round(st.quantiles(gaps, n=4)[2] - st.quantiles(gaps, n=4)[0], 1) if len(gaps) >= 4 else None,
                        alternation=round(alt, 3),
                        span_min=round((seq[-1][0] - seq[0][0]) / 60, 1)))
    return out


def main():
    pools = {}
    total_manu_floor = total_manu_share = total_manu_rate = 0.0
    for slug in FLAGGED:
        d = read_json(os.path.join(RAWT, slug + ".json"))
        meta = d["meta"]
        m = metrics(d["trades"])
        floor = sum(r["matched_usd"] for r in top_roundtrippers(d["trades"], k=999) if r["wash_bot"])
        age = pool_age(slug)
        vol24 = meta.get("vol") or 0
        win_h = window_hours(d["trades"]) or None
        # Two honest 24h extrapolations that bracket the truth (they can disagree by an order of
        # magnitude, so we report the RANGE, not a point estimate, and lean on the in-window floor):
        #   share-based: wash_share x reported 24h volume  (assumes the snapshot share holds all day)
        #   rate-based:  bot USD per hour x 24h            (assumes the in-window bot rate holds all day)
        manu_share = vol24 * m["wash_share"]
        manu_rate = (floor / win_h * 24) if win_h else 0
        total_manu_floor += floor
        total_manu_share += manu_share
        total_manu_rate += manu_rate
        key = meta["sym"] + "/" + meta["dex"] + " " + d["pool"][:4]
        pools[key] = dict(pool=d["pool"], turnover=meta.get("turn"), vol_24h=vol24, window_h=win_h,
                          n_bots=m["n_wash_bots"], wash_share=m["wash_share"], matched_in_window=round(floor),
                          manufactured_24h_share=round(manu_share), manufactured_24h_rate=round(manu_rate),
                          age=age, cadence=cadence(d["trades"]))

    # when did the bots first appear? restrict to the NAMED wash bots (not the upstream
    # funding intermediaries, which are older and are not the flagged actors).
    named = set()
    for slug in FLAGGED:
        d = read_json(os.path.join(RAWT, slug + ".json"))
        named |= {r["wallet"] for r in top_roundtrippers(d["trades"], k=999) if r["wash_bot"]}
    bot_first, intermediary_first = [], []
    for fn in glob.glob(os.path.join(RAWW, "*.json")):
        r = read_json(fn)
        if not r.get("first_ts"):
            continue
        (bot_first if r["wallet"] in named else intermediary_first).append(r["first_ts"])
    out = dict(snapshot="2026-06-21", pools=pools,
               matched_in_window_floor=round(total_manu_floor),
               manufactured_24h_rate=round(total_manu_rate), manufactured_24h_share=round(total_manu_share),
               earliest_bot=datetime.fromtimestamp(min(bot_first), timezone.utc).date().isoformat() if bot_first else None,
               earliest_funder=datetime.fromtimestamp(min(intermediary_first), timezone.utc).date().isoformat() if intermediary_first else None)
    write_json(out, os.path.join(ROOT, "temporal.json"), indent=2)

    print("pool window + wash share + 24h extrapolations (share-based / rate-based):")
    for k, p in pools.items():
        print(f"  {k:22} window {str(p['window_h'])+'h':>7}, 24h vol ${p['vol_24h']:>12,}, wash {p['wash_share']*100:3.0f}%, "
              f"matched ${p['matched_in_window']:>8,}  ->  share ${p['manufactured_24h_share']:>11,} / rate ${p['manufactured_24h_rate']:>11,}")
    print(f"\nearliest NAMED bot first tx: {out['earliest_bot']}  | earliest funding intermediary: {out['earliest_funder']}")
    print(f"\nmanufactured/day: floor ${out['matched_in_window_floor']:,} (matched, in-window, hard) | "
          f"24h range ${out['manufactured_24h_rate']:,} (rate) .. ${out['manufactured_24h_share']:,} (share)")
    print("\nrobotic cadence (busiest bots):")
    for k, p in pools.items():
        for c in p["cadence"]:
            print(f"  {k:14} {c['wallet'][:10]}.. {c['n']} trades, median gap {c['median_gap_s']}s, "
                  f"alternation {c['alternation']*100:.0f}%, over {c['span_min']}min")
    print("\nwrote temporal.json")


if __name__ == "__main__":
    main()
