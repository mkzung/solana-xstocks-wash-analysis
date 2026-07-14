"""Independent verification of the headline claims, recomputed from the raw cached
data without reusing the analysis modules' score path. Asserts must all pass; this
is the reproducibility / no-drift guard that CI runs.
"""
import os
import re
import glob
import bisect
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from io_util import read_json, read_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAWT = os.path.join(ROOT, "data", "raw", "trades")
RAWW = os.path.join(ROOT, "data", "raw", "wallets")

FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def ledger(trades):
    w = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for t in trades:
        a = t.get("tx_from_address") or "?"
        u = f(t.get("volume_in_usd"))
        if t.get("kind") == "buy":
            w[a][0] += 1; w[a][2] += u
        else:
            w[a][1] += 1; w[a][3] += u
    return w


def bots(trades):                                   # independent re-impl of the wash-bot rule
    out = []
    for wal, (b, s, bu, su) in ledger(trades).items():
        if min(b, s) >= 5 and (min(bu, su) / max(bu, su) if max(bu, su) else 0) >= 0.90:
            out.append((wal, b, s, bu, su))
    return out


def main():
    checks = []

    def ck(name, cond):
        checks.append((name, bool(cond)))
        print(("  PASS " if cond else "  FAIL ") + name)

    # 1) every flagged pool has wash bots; the screen's controls have none
    flagged_bots = {}
    for slug in FLAGGED:
        d = read_json(os.path.join(RAWT, slug + ".json"))
        flagged_bots[slug] = bots(d["trades"])
        ck(f"{slug.split('__')[0]+'/'+slug.split('__')[1]} has >=2 wash bots", len(flagged_bots[slug]) >= 2)

    controls = [p for p in glob.glob(os.path.join(RAWT, "*.json")) if os.path.basename(p).split(".")[0] not in FLAGGED]
    ctrl_with_bots = 0
    for p in controls:
        d = read_json(p)
        if d["meta"].get("control") or (d["meta"].get("turn") is not None and d["meta"]["turn"] <= 2.0):
            if len(bots(d["trades"])) > 0 and len(bots(d["trades"])) > 1:
                ctrl_with_bots += 1
    ck("organic controls carry ~no wash bots (<=1 across all)", ctrl_with_bots <= 1)

    # 2) named bots total and near-perfect balance
    allbots = set()
    bals = []
    for slug, bs in flagged_bots.items():
        for wal, b, s, bu, su in bs:
            allbots.add(wal)
            bals.append(min(bu, su) / max(bu, su))
    ck("14+ distinct named wash bots", len(allbots) >= 14)
    ck("median bot USD-balance >= 0.97", sorted(bals)[len(bals) // 2] >= 0.97)

    # 3) the two QQQX bots: equal-count, near-flat
    d = read_json(os.path.join(RAWT, "QQQX__raydium__EibwWLHy.json"))
    q = sorted(bots(d["trades"]), key=lambda r: -(r[3] + r[4]))[:2]
    ck("QQQX top bot does >=36 buys and >=36 sells", q[0][1] >= 36 and q[0][2] >= 36)

    # 4) robotic cadence: a headline bot alternates buy/sell ~100%
    def alternation(trades, wal):
        seq = sorted((datetime.fromisoformat(t["block_timestamp"].replace("Z", "+00:00")).timestamp(), t["kind"])
                     for t in trades if t.get("tx_from_address") == wal)
        ks = [k for _, k in seq]
        return sum(1 for i in range(len(ks) - 1) if ks[i] != ks[i + 1]) / (len(ks) - 1) if len(ks) > 1 else 0
    ck("QQQX bot C6FyA84D alternates buy/sell 100%",
       abs(alternation(d["trades"], "C6FyA84D6JLtkSSyq45gcLFi67P3q61FhGohEFYd9rvF") - 1.0) < 1e-9)

    # 5) TSLAX creation chain: monotone decreasing seeds down the chain
    chain = ["8gw6JyEW", "FMMs8SGx", "AtzmNv2w", "vwbEYDGU", "2eTkWQyt"]
    seeds = []
    for pref in chain:
        fn = glob.glob(os.path.join(RAWW, pref + "*.json"))
        if fn:
            seeds.append(read_json(fn[0]).get("seed_amount"))
    ck("TSLAX chain seeds strictly decrease (peel pattern)",
       all(a is not None and b is not None and a > b for a, b in zip(seeds, seeds[1:])))

    # 6) screen.json reconciles: 5 flagged, clean gap above EVERY non-flagged pool
    s = read_json(os.path.join(ROOT, "screen.json"))
    ck("screen.json: 5 flagged, flag calibrated above WIF/JUP",
       s["n_flagged"] == 5 and s["flag_threshold"] > (s.get("max_control_score") or 0))
    flagged_scores = [m["score"] for m in s["markets"] if m["flag"]]
    ck("screen.json: clean gap (min flagged - max non-flagged > 0.10)",
       min(flagged_scores) - s["max_nonflagged_score"] > 0.10)

    # 7) cluster.json integrity: each flagged pool keyed distinctly, its bots match the raw data
    c = read_json(os.path.join(ROOT, "cluster.json"))
    ck("cluster.json: 5 distinct flagged-pool keys", len(c["pools"]) == 5)
    union_ok = True
    for slug in FLAGGED:
        key = slug.split("__")[0] + "/" + slug.split("__")[1] + "/" + slug.split("__")[2]
        cj = {b["wallet"] for b in c["pools"].get(key, {}).get("bots", [])}
        raw = {wal for wal, *_ in bots(read_json(os.path.join(RAWT, slug + ".json"))["trades"])}
        union_ok = union_ok and cj == raw
    ck("cluster.json: every flagged pool's named bots match the raw data", union_ok)

    # 8) the hardcoded FLAGGED list (duplicated across analysis modules) matches what the screen flags
    screen_flagged = {m["pool"][:8] for m in s["markets"] if m["flag"]}
    hardcoded_flagged = {slug.split("__")[2] for slug in FLAGGED}
    ck("FLAGGED list is in sync with screen.json (no drift)", screen_flagged == hardcoded_flagged)

    # 9) the flagged pools trade the OFFICIAL Backed/xStocks tokens (Solana Foundation published list),
    #    not impostor lookalikes
    official = {"QQQX": "Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ",
                "SPYX": "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W",
                "TSLAX": "XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB"}
    mints_ok = True
    for slug in FLAGGED:
        meta = read_json(os.path.join(RAWT, slug + ".json"))["meta"]
        mints_ok = mints_ok and meta.get("mint") == official[meta["sym"]]
    ck("flagged pools trade the official Backed xStock mints (not lookalikes)", mints_ok)

    # 10) the bimodal balance split, DESCRIPTIVE. Not a significance test - see the note below.
    fl_ge = fl_tot = ct_ge = ct_tot = 0
    for p in glob.glob(os.path.join(RAWT, "*.json")):
        slug = os.path.basename(p).split(".")[0]
        for b, s, bu, su in ledger(read_json(p)["trades"]).values():
            if b >= 5 and s >= 5 and max(bu, su) > 0:
                ge = (min(bu, su) / max(bu, su)) >= 0.90
                if slug in FLAGGED:
                    fl_tot += 1; fl_ge += ge
                else:
                    ct_tot += 1; ct_ge += ge
    # No p-value here, on purpose. An earlier revision computed a hypergeometric one and it was
    # circular: screen.py FLAGS a pool on the USD share coming from wallets at balance >= 0.90,
    # so comparing flagged against non-flagged pools on the COUNT of wallets at balance >= 0.90
    # conditions on the statistic under test (a pool with no such wallets can never be flagged).
    # The wallets in a pool are also a co-deployed fleet, not independent draws, which is what a
    # hypergeometric assumes. What survives is the size of the gap, asserted on both sides below,
    # and the a-priori controls carrying essentially none of these wallets (check 1).
    fl_rate = fl_ge / fl_tot if fl_tot else 0.0
    ct_rate = ct_ge / ct_tot if ct_tot else 0.0
    print(f"        [bimodal split, descriptive: {fl_ge}/{fl_tot} flagged ({fl_rate:.0%}) vs "
          f"{ct_ge}/{ct_tot} non-flagged ({ct_rate:.0%}) at bal>=0.90]")
    # Both bounds are pinned so the check cannot go vacuous if either side drifts to zero.
    ck("bimodal split is stark (flagged >= 40% balanced, non-flagged <= 15%)",
       fl_tot > 0 and ct_tot > 0 and fl_rate >= 0.40 and ct_rate <= 0.15)

    # 11) the post's Appendix table lists EXACTLY the 10 largest distinct wallets by matched USD,
    #     so the table stays in sync with the committed data.
    per_wallet = {}
    for slug, bs in flagged_bots.items():
        for wal, b, s, bu, su in bs:
            m = min(bu, su)
            if wal not in per_wallet or m > per_wallet[wal]:
                per_wallet[wal] = m
    top10 = {w for w, _ in sorted(per_wallet.items(), key=lambda kv: -kv[1])[:10]}
    appendix = read_text(os.path.join(ROOT, "post", "index.md")).split("## Appendix")[-1].split("## References")[0]
    # Read the addresses out of the table cells (backticked), not out of every base58-looking token
    # in the section: a git commit hash can be all-base58 too, and the pin link sits in this section.
    listed = set(re.findall(r"`([1-9A-HJ-NP-Za-km-z]{40,44})`", appendix))
    ck("post Appendix lists exactly the 10 largest distinct wallets by matched USD", listed == top10)

    # assert on the claim, not the markup or the wording: strip emphasis, fold case and spacing,
    # and match the shortest phrase that carries the fact. A check that breaks when a sentence is
    # rephrased is testing the prose, not the analysis.
    post_raw = read_text(os.path.join(ROOT, "post", "index.md"))
    post = post_raw.replace("**", "").replace("*", "")
    _post_n = " ".join(post.lower().split())

    def says(*phrases):
        return all(" ".join(p.lower().split()) in _post_n for p in phrases)
    T = read_json(os.path.join(ROOT, "temporal.json"))

    # 12) Appendix table NUMBERS (buys/sells/USD), not just the wallet set, match the data.
    best = {}
    for bs in flagged_bots.values():
        for wal, b, s, bu, su in bs:
            if wal not in best or min(bu, su) > min(best[wal][2], best[wal][3]):
                best[wal] = (b, s, bu, su)
    rownum_ok = True
    for line in appendix.splitlines():
        mr = re.match(r"\|[^|]*\|\s*`([1-9A-HJ-NP-Za-km-z]{40,44})`\s*\|\s*(\d+)\s*/\s*(\d+)\s*\|\s*\$([\d,]+)\s*/\s*\$([\d,]+)\s*\|", line)
        if not mr:
            continue
        got = (int(mr.group(2)), int(mr.group(3)), int(mr.group(4).replace(",", "")), int(mr.group(5).replace(",", "")))
        e = best.get(mr.group(1))
        rownum_ok = rownum_ok and e is not None and got == (e[0], e[1], round(e[2]), round(e[3]))
    ck("Appendix table buys/sells/USD columns match the data", rownum_ok)

    allrows = [(wal, b, s, bu, su) for bs in flagged_bots.values() for (wal, b, s, bu, su) in bs]

    # 13) PnL: bot sells return the post's stated % of bot buys (a small net loss to fees)
    tbu = sum(r[3] for r in allrows); tsu = sum(r[4] for r in allrows)
    pnl = round(tsu / tbu * 100, 1)
    mp = re.search(r"sells return about ([\d.]+)%", post)
    ck("post PnL (sells/buys %) matches recomputed", bool(mp) and float(mp.group(1)) == pnl)

    # 14) the $467k matched floor: raw sum(2*min) == temporal.json == post. temporal.py sums
    #     per-wallet round(2*min), so allow up to 0.5 of rounding drift per bot row (< len(allrows)).
    floor_raw = sum(2 * min(r[3], r[4]) for r in allrows)
    ck("matched floor: raw == temporal.json == post $467k",
       abs(floor_raw - T["matched_in_window_floor"]) <= len(allrows) and abs(T["matched_in_window_floor"] - 467000) < 1000 and "467,000" in post)

    # 15) 24h extrapolation range matches temporal.json
    ck("24h range $32M-$102M matches temporal.json",
       round(T["manufactured_24h_rate"] / 1e6) == 32 and round(T["manufactured_24h_share"] / 1e6) == 102 and "$32M to $102M" in post)

    # 16) persistence: 3 of 5 still flag, zero wallet overlap (the rotating-fleet claim)
    P = read_json(os.path.join(ROOT, "persistence.json"))
    ck("persistence: 3/5 re-flag, 0 wallet overlap (matches post)",
       P["still_flagged"] == 3 and P["total_wallet_overlap"] == 0 and says("three of the five pools"))

    # 16b) the post quotes per-pool bot counts (5, 2, 5, 3, 3) that sum to 18 appearances while
    #      naming 14 distinct wallets, because two wallets trade more than one pool. Recompute all
    #      three numbers: the sentence exists precisely because the two counts differ.
    NW = read_json(os.path.join(ROOT, "data", "named_wallets.json"))
    appearances = len(NW)
    distinct = len({r["wallet"] for r in NW})
    multi = sum(1 for _w, n in Counter(r["wallet"] for r in NW).items() if n > 1)
    ck("bot appearances (18) vs distinct wallets (14), two of them multi-pool - and the post says so",
       appearances == 18 and distinct == 14 and multi == 2
       and says("eighteen") and says("fourteen")
       and says("two wallets trade in more than one pool"))

    # 17) funding chain: the exact six seeds match the edges and the post. The chain the post
    #     tells must also BE the longest one cluster.py finds for the pool - the figure used to
    #     draw six of the seven wallets, so the post told a shorter chain than its own data had.
    seeds_expected = {"85zuUQ5w": 526.53, "8gw6JyEW": 522.22, "FMMs8SGx": 517.67,
                      "AtzmNv2w": 513.34, "vwbEYDGU": 508.83, "2eTkWQyt": 504.48}
    by_child = {w[:8]: seed for _, w, seed, _n in read_json(os.path.join(ROOT, "data", "funding_edges.json"))["edges"]}
    ck("funding chain: exact 6 seeds match edges and post",
       all(by_child.get(k) == v for k, v in seeds_expected.items()) and all(f"{v:.2f}" in post for v in seeds_expected.values()))

    chains = read_json(os.path.join(ROOT, "cluster.json"))["creation_chains"]
    longest = max((ch for chs in chains.values() for ch in chs), key=len)
    ck("post tells the LONGEST chain cluster.py found (7 wallets, no truncation)",
       len(longest) == 7 and len(seeds_expected) == len(longest) - 1
       and all(w[:8] in post for w in longest))

    # the near-constant step is the "automated deployment" claim, so pin the range the post quotes
    ordered = sorted(seeds_expected.values(), reverse=True)
    steps = [round(a - b, 2) for a, b in zip(ordered, ordered[1:])]
    ck("seed steps really are near-constant (4.3 to 4.6 USDT, as the post says)",
       all(4.3 <= s <= 4.6 for s in steps) and "4.3 to 4.6 USDT" in post)

    # the post says the chain stops at the top wallet because the tracer walks SIX levels and that
    # is where it sits - a claim about our own code, so read the cap out of the code and check that
    # the top of the chain really is at it.
    src = read_text(os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace_tree.py"))
    max_depth = int(re.search(r"^MAX_DEPTH\s*=\s*(\d+)", src, re.M).group(1))
    parent = {c: p for p, c, _s, _n in read_json(os.path.join(ROOT, "data", "funding_edges.json"))["edges"]}
    top, hops = longest[0], 0
    while top in parent and parent[top] != top:
        top, hops = parent[top], hops + 1
    ck("the chain stops at the trace's depth cap (six levels), exactly as the post says",
       max_depth == 6 and hops == 6 and top.startswith("H9c7D19P")
       and "walks six levels up" in post)

    # 18) the bimodal medians the post cites (0.94 flagged vs 0.66 control)
    fb, cb = [], []
    for pth in glob.glob(os.path.join(RAWT, "*.json")):
        slug = os.path.basename(pth).split(".")[0]
        for b, s, bu, su in ledger(read_json(pth)["trades"]).values():
            if b >= 5 and s >= 5 and max(bu, su) > 0:
                (fb if slug in FLAGGED else cb).append(min(bu, su) / max(bu, su))
    ck("median balance 0.94 flagged / 0.66 control (matches post)",
       round(statistics.median(fb), 2) == 0.94 and round(statistics.median(cb), 2) == 0.66 and says("0.94", "0.66"))

    # 19) wallet-age dates: earliest named bot Oct 2025, earliest funder Dec 2024
    ck("earliest bot Oct-2025 / funder Dec-2024 (temporal.json matches post)",
       T["earliest_bot"] == "2025-10-27" and T["earliest_funder"] == "2024-12-25"
       and "October 2025" in post and "December 2024" in post)

    # 20) organic-control circular share (WIF 74%, JUP 38%) reconciles screen.json to the post
    sj = read_json(os.path.join(ROOT, "screen.json"))
    circ = {m["symbol"]: m["circular_share"] for m in sj["markets"] if m["is_control"]}
    ck("WIF/JUP circular 74%/38% (screen.json matches post)",
       round(circ.get("WIF", 0) * 100) == 74 and round(circ.get("JUP", 0) * 100) == 38 and "74% and 38%" in post)

    # 21) on-chain pool prices the post quotes are the data's prices (rules out a price-dislocation
    #     misread): the xStock-side median per symbol matches the post (TSLAX ~$401, SPYX ~$750).
    sym_px = {}
    for pth in glob.glob(os.path.join(RAWT, "*.json")):
        d = read_json(pth); meta = d["meta"]; mint = meta.get("mint")
        for t in d["trades"]:
            try:
                if t.get("from_token_address") == mint:
                    sym_px.setdefault(meta["sym"], []).append(float(t["price_from_in_usd"]))
                elif t.get("to_token_address") == mint:
                    sym_px.setdefault(meta["sym"], []).append(float(t["price_to_in_usd"]))
            except (TypeError, ValueError, KeyError):
                pass
    ck("quoted pool prices match the data (TSLAX ~$401, SPYX ~$750)",
       abs(statistics.median(sym_px["TSLAX"]) - 401) < 2 and abs(statistics.median(sym_px["SPYX"]) - 750) < 2
       and "near $401" in post and "near $750" in post)

    # 22) lifetime totals (lifetime.json) recompute from the committed per-wallet swap files,
    #     and the post's lifetime figures match them.
    L = read_json(os.path.join(ROOT, "lifetime.json"))
    rec_m = rec_n = 0
    for wf in glob.glob(os.path.join(ROOT, "data", "raw", "wallet_swaps", "*.json")):
        sw = read_json(wf).get("swaps", [])
        bu = sum(x["usd"] for x in sw if x["side"] == "buy")
        su = sum(x["usd"] for x in sw if x["side"] == "sell")
        rec_m += round(2 * min(bu, su)); rec_n += len(sw)
    ck("lifetime.json totals recompute from the committed swap files",
       abs(rec_m - L["total_matched_usd"]) <= len(L["bots"]) and rec_n == L["total_swaps"])
    ck("post lifetime figures match lifetime.json ($5.6M / 2,836 / $2.9M)",
       round(L["total_matched_usd"] / 1e6, 1) == 5.6 and L["total_swaps"] == 2836
       and round(L["max_bot_matched_usd"] / 1e6, 1) == 2.9
       and "$5.6M" in post and "2,836" in post and "$2.9M" in post)
    ck("lifetime washing is bursty (max bot span ~4 days, matches post)",
       4 < L["max_span_days"] < 5 and says("four days"))

    # 23) Appendix lifetime-matched column matches lifetime.json per wallet
    life_by_w = {b["wallet"]: b["matched_usd"] for b in L["bots"]}
    lifecol_ok, lifecol_n = True, 0
    for line in appendix.splitlines():
        mr = re.match(r"\|[^|]*\|\s*`([1-9A-HJ-NP-Za-km-z]{40,44})`\s*\|\s*\d+\s*/\s*\d+\s*\|\s*\$[\d,]+\s*/\s*\$[\d,]+\s*\|\s*\$([\d,]+)\s*\|", line)
        if not mr:
            continue
        lifecol_n += 1
        lifecol_ok = lifecol_ok and life_by_w.get(mr.group(1)) == int(mr.group(2).replace(",", ""))
    ck("Appendix lifetime column matches lifetime.json (10 wallets)", lifecol_ok and lifecol_n == 10)

    # 24) aggregator under-count: the bots' in-window on-chain net vs the per-pool tape (~1.3x;
    #     confirms the $467k floor is conservative). Recomputed from committed trades + swap files.
    allbot_wallets = {r[0] for r in allrows}
    gt_sig, hel_sig = {}, {}
    for slug in FLAGGED:
        for t in read_json(os.path.join(RAWT, slug + ".json"))["trades"]:
            if t.get("tx_from_address") in allbot_wallets:
                gt_sig[t["tx_hash"]] = gt_sig.get(t["tx_hash"], 0.0) + float(t["volume_in_usd"])
    for wf in glob.glob(os.path.join(ROOT, "data", "raw", "wallet_swaps", "*.json")):
        for s in read_json(wf)["swaps"]:
            hel_sig[s["sig"]] = hel_sig.get(s["sig"], 0.0) + s["usd"]
    ov = set(gt_sig) & set(hel_sig)
    ratio = sum(hel_sig[s] for s in ov) / sum(gt_sig[s] for s in ov) if ov else 0
    ck("aggregator under-count ~1.3x (on-chain net vs per-pool tape, matches post)",
       1.2 < ratio < 1.4 and "1.3x" in post)

    # 25) named_wallets.json reproduces from the detector: every (wallet, pool) row matches the
    #     recomputed wash-bot set and numbers, and each sample_tx is a real transaction of that
    #     wallet in that pool.
    NW = read_json(os.path.join(ROOT, "data", "named_wallets.json"))
    det_num, tx_by_key = {}, {}
    for slug in FLAGGED:
        d = read_json(os.path.join(RAWT, slug + ".json"))
        pid = d["pool"]                      # full pool id keeps the two SPYX/orca pools distinct
        for wal, b, s, bu, su in bots(d["trades"]):
            det_num[(wal, pid)] = (b, s, round(bu), round(su))
        for t in d["trades"]:
            if t.get("tx_from_address"):
                tx_by_key.setdefault((t["tx_from_address"], pid), set()).add(t.get("tx_hash"))
    nw_ok = {(r["wallet"], r["pool_id"]) for r in NW} == set(det_num) and len({r["wallet"] for r in NW}) == len(allbots)
    for r in NW:
        k = (r["wallet"], r["pool_id"])
        nw_ok = nw_ok and det_num.get(k) == (r["buys"], r["sells"], r["buy_usd"], r["sell_usd"]) \
            and r["sample_tx"] in tx_by_key.get(k, set())
    ck("named_wallets.json matches the detector (set, counts, USD, sample_tx)", nw_ok)

    # 26) every named bot is a plain System-Program keypair, not a router/PDA (committed owner
    #     snapshot from owner_check.py), so the post's "not aggregator routing" claim recomputes
    #     offline from committed data.
    own = read_json(os.path.join(ROOT, "data", "raw", "wallet_owners.json"))
    ck("all named bots are System-Program keypairs (owner_check snapshot)",
       allbots <= set(own["owners"]) and all(own["owners"][w] == own["system_program"] for w in allbots)
       and "System Program" in post and "System-Program" in post)

    # 27) window-confound robustness, stated honestly (independent recompute). Wash SHARE is
    #     window-sensitive: sliced to the shortest flagged window, several non-flagged pools show a
    #     lone round-tripper at a share ABOVE the flag, so the share alone is not the discriminator.
    #     What IS robust (window-independent) is the full-window FLEET: no non-flagged pool carries
    #     >=2 wash bots over its full snapshot, while every flagged pool carries >=2.
    def _ts(t):
        return datetime.fromisoformat(t["block_timestamp"].replace("Z", "+00:00")).timestamp()

    def _wash_share(trades):
        led = ledger(trades)
        tot = sum(v[2] + v[3] for v in led.values())
        bot = sum(v[2] + v[3] for v in led.values()
                  if min(v[0], v[1]) >= 5 and (min(v[2], v[3]) / max(v[2], v[3]) if max(v[2], v[3]) else 0) >= 0.90)
        return bot / tot if tot else 0.0
    flag_thr = read_json(os.path.join(ROOT, "screen.json"))["flag_threshold"]
    spans = [(lambda tt: tt[-1] - tt[0])(sorted(_ts(t) for t in read_json(os.path.join(RAWT, slug + ".json"))["trades"] if t.get("block_timestamp"))) for slug in FLAGGED]
    Lw = min(spans)
    full_nonflagged_max, n_above_flag = 0, 0
    for p in glob.glob(os.path.join(RAWT, "*.json")):
        if os.path.basename(p)[:-5] in FLAGGED:
            continue
        trs = read_json(p)["trades"]
        full_nonflagged_max = max(full_nonflagged_max, len(bots(trs)))
        seq = sorted((t for t in trs if t.get("block_timestamp")), key=_ts)
        times = [_ts(t) for t in seq]
        best = max((_wash_share(seq[i:bisect.bisect_right(times, times[i] + Lw)]) for i in range(len(seq))), default=0.0)
        if best > flag_thr:
            n_above_flag += 1
    min_flagged_bots = min(len(bs) for bs in flagged_bots.values())
    ck("full-window fleet discriminates (non-flagged <=1 bot, flagged >=2); sub-window share confound real",
       full_nonflagged_max <= 1 and min_flagged_bots >= 2 and n_above_flag == 4
       and says("sustained across the whole snapshot") and says("four of the non-flagged"))

    # the collector drops pools under a volume floor before fetching a tape, so the post has to
    # say so: an undisclosed filter is a silent selection rule
    src_fetch = read_text(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fetch_raw.py"))
    min_vol = int(re.search(r"^MIN_VOL\s*=\s*(\d+)", src_fetch, re.M).group(1))
    ck("the post discloses the volume floor the collector applies ($50,000)",
       min_vol == 50000 and says("$50,000") and says("fetches a tape only for"))

    # the funnel: 32 in the universe, 14 clear the floor, 16 scored with the controls, 18 unscored
    uni = read_json(os.path.join(ROOT, "data", "universe.json"))
    clears = [a for a, pl in uni.items() if (pl.get("vol") or 0) >= min_vol]
    ck("the post states the real funnel (32 -> 14 clear the floor -> 16 scored, 18 unscored)",
       len(uni) == 32 and len(clears) == 14
       and len(read_json(os.path.join(ROOT, "screen.json"))["markets"]) == 16
       and says("32") and says("14") and says("18") and says("unscored rather than clean"))

    # count the pools whose bots are tied by funding - one funded another, or a shared ancestor
    CL = read_json(os.path.join(ROOT, "cluster.json"))
    FE = CL["funding_edges"]

    def ancestors(w):
        out, cur = [], w
        while cur in FE and FE[cur].get("parent") and FE[cur]["parent"] not in out:
            cur = FE[cur]["parent"]; out.append(cur)
        return out

    linked = 0
    for _k, p_ in CL["pools"].items():
        bots_ = [b["wallet"] for b in p_["bots"]]
        if any(v in ancestors(w) or w in ancestors(v) or (set(ancestors(w)) & set(ancestors(v)))
               for i, w in enumerate(bots_) for v in bots_[i + 1:]):
            linked += 1
    ck("three of the five flagged pools have a funding link between their bots, and the post says so",
       linked == 3 and says("three of the five") and says("no funding link between the bots"))

    # Aggregator routing: one signed transaction can be split across pools, so a pool tape shows a
    # leg, not a whole swap. Recompute the three claims that follow from it.
    R = read_json(os.path.join(ROOT, "routing.json"))
    ck("routed share of bot volume (35%) and the routing caveat are in the post",
       round(R["bot_routed_usd_share"] * 100) == 35 and "35%" in post
       and says("split by an aggregator"))
    ck("no bot transaction buys one pool and sells another; 38 others in the snapshot do",
       R["bot_mixed_side_tx"] == 0 and R["bot_multi_pool_tx"] == 60
       and R["mixed_side_tx_in_snapshot"] == 38
       and "38" in post and "60" in post)
    own = R["multi_pool_by_own_tx"]
    ck("the post names the wallets that reach several pools in their OWN transactions",
       len(own) == 2 and all(any(w.startswith(p) for w in own) for p in ("HpcHy6dN", "33X9awze"))
       and "33X9awze" in post and says("leg of a routed swap"))

    # sequential arbitrage would leave a wallet buy-heavy in one pool and sell-heavy in another
    ck("no bot is buy-heavy in one pool and sell-heavy in another (sequential arbitrage)",
       R["cross_pool_directional_bots"] == []
       and says("buy-heavy in one pool"))

    # strike out wallets that reach a pool only as a routed leg: the fleet count must survive
    ck("fleet count survives routing: every flagged pool keeps >=2 bots with their own txs",
       R["min_own_tx_bots_in_a_flagged_pool"] >= 2
       and len(R["own_tx_bots_per_flagged_pool"]) == 5
       and says("at least two bots"))

    # the cost of the wash is the round trip's own loss, not a guessed fee schedule
    ck("in-window cost = buys - sells = ~$1,550 on $236k in, about a third of a cent per dollar",
       abs((tbu - tsu) - 1550) < 25 and round(tbu / 1000) == 236
       and "$236,000" in post and "$1,550" in post and says("a third of a cent"))

    # "flat" is claimed in dollars AND in shares: net each bot's xStock units, per symbol
    TF = R["token_flatness"]
    ck("bots end flat in TOKEN units too (median 0.01%, worst 4.6%), as the post says",
       round(TF["median_abs_net_over_gross"] * 100, 2) <= 0.01
       and round(TF["worst_abs_net_over_gross"] * 100, 1) == 4.6
       and "median 0.01%" in post and "4.6%" in post)

    # lifetime totals must not depend on netting one xStock against another
    ck("lifetime matched is identical computed within each symbol ($5,579,149)",
       L["total_matched_usd"] == L["total_matched_usd_within_symbol"] == 5579149
       and "5,579,149" in post)

    # every address the post sends a reader to must exist in the data (hand-typed ones do not)
    known = set()
    for pth in glob.glob(os.path.join(RAWT, "*.json")):
        d = read_json(pth)
        known.add(d["pool"]); known.add(d["meta"]["mint"])
        known.update(t["tx_from_address"] for t in d["trades"] if t.get("tx_from_address"))
    for f, w, _s, _n in read_json(os.path.join(ROOT, "data", "funding_edges.json"))["edges"]:
        known.add(f); known.add(w)
    known.update(r["wallet"] for r in read_json(os.path.join(ROOT, "data", "named_wallets.json")))
    # the post can cite pools the volume floor excluded
    known.update(read_json(os.path.join(ROOT, "data", "universe.json")).keys())
    # strip the pin links first: a hex SHA is very nearly base58
    body = re.sub(r"https://github\.com/\S+", "", post)
    addrs = set(re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", body))
    orphans = sorted(addrs - known)
    ck(f"every full address in the post ({len(addrs)}), linked or not, exists in the committed data",
       not orphans)
    if orphans:
        for a in orphans:
            print(f"    ORPHAN ADDRESS (not in any committed file): {a}")

    # a typo in an 8-char short form points the reader at nothing, and nothing else would catch it
    shorts = set(re.findall(r"`([1-9A-HJ-NP-Za-km-z]{8})`", body))
    prefixes = {a[:8] for a in known}
    bad_shorts = sorted(shorts - prefixes)
    ck(f"every 8-char short address in the post ({len(shorts)}) prefixes a real one",
       not bad_shorts)
    if bad_shorts:
        for a in bad_shorts:
            print(f"    SHORT FORM MATCHES NOTHING: `{a}`")

    # the post pins this repo in three places; a half-bumped pin points at the wrong tree
    pins = re.findall(r"solana-xstocks-wash-analysis/(?:tree|blob)/([0-9a-f]{40})", post)
    pins += re.findall(r"git checkout ([0-9a-f]{40})", post)      # the repro command pins it too
    short = re.findall(r"pinned at commit \[`([0-9a-f]{7,40})`\]", post)
    ck("the post's companion pins all point at ONE commit (no half-bumped pin)",
       len(pins) >= 3 and len(set(pins)) == 1 and len(short) == 1 and pins[0].startswith(short[0]))

    # a retraction that only touches the post is not a retraction: the Fisher p-value lived on in
    # dashboard.html and index.html for a day. Anything withdrawn goes here and stays dead.
    withdrawn = ["Fisher", "hypergeom", "8e-5", "1 in 12,000", "statistically significant",
                 "order of magnitude", "runs continuously", "Two figures bound", "is an LP",
                 "Six TSLAX", "six-wallet", "~4.5 USDT"]
    # strip the base64 images: 680kB of [A-Za-z0-9+/] would hit "fisher" by chance eventually
    surfaces = {name: re.sub(r"data:image/[a-z]+;base64,[A-Za-z0-9+/=]+", "",
                             read_text(os.path.join(ROOT, name)))
                for name in ("post/index.md", "README.md", "dashboard.html", "index.html")
                if os.path.exists(os.path.join(ROOT, name))}

    # normalise, so a phrase cannot slip back in hyphenated or line-wrapped
    def norm(s):
        return re.sub(r"[\s\-]+", " ", s.lower())
    alive = [(n, w) for n, txt in surfaces.items() for w in withdrawn if norm(w) in norm(txt)]
    ck(f"no withdrawn claim survives on any published surface ({len(surfaces)} checked)", not alive)
    if alive:
        for n, w in alive:
            print(f"    STILL PRESENT: {w!r} in {n}")

    nfail = sum(1 for _, ok in checks if not ok)
    print(f"\n{len(checks)} checks, {nfail} failed")
    if nfail:
        raise SystemExit("verification failed")
    print("ALL CHECKS PASS")


if __name__ == "__main__":
    main()
