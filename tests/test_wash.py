"""Invariant + unit tests over the committed data and analysis outputs.

Deterministic: runs entirely over the committed snapshot, no network. CI runs the
analysis scripts first, then these assert the published claims hold.
"""
import os
import sys
import glob
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
from metrics_lib import metrics, is_wash_bot, top_roundtrippers  # noqa: E402
from io_util import read_json

RAWT = os.path.join(ROOT, "data", "raw", "trades")
FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]


def trades(slug):
    return read_json(os.path.join(RAWT, slug + ".json"))["trades"]


# ---- detector unit tests ----

def test_is_wash_bot_rule():
    assert is_wash_bot(20, 20, 10000, 10000)            # balanced heavy round-tripper
    assert not is_wash_bot(20, 20, 10000, 2000)         # unbalanced (net directional) -> not a bot
    assert not is_wash_bot(3, 3, 100, 100)              # too few round-trips
    assert not is_wash_bot(40, 0, 9000, 0)              # one-sided -> not a bot


def test_metrics_on_organic_control_are_clean():
    for fn in glob.glob(os.path.join(RAWT, "CTRL_*.json")):
        m = metrics(read_json(fn)["trades"])
        assert m["n_wash_bots"] == 0, fn
        assert m["wash_share"] < 0.10, fn


# ---- screen invariants ----

def test_screen_separates_flagged_from_controls():
    s = read_json(os.path.join(ROOT, "screen.json"))
    assert s["n_flagged"] == 5
    # flag calibrated above the a-priori organic controls (WIF/JUP), not a turnover threshold
    assert s["flag_threshold"] > (s["max_control_score"] or 0)
    flagged = [m for m in s["markets"] if m["flag"]]
    assert min(m["score"] for m in flagged) >= s["flag_threshold"]
    # clean gap above EVERY non-flagged pool (incl. same-class clean xStock pools)
    assert min(m["score"] for m in flagged) - s["max_nonflagged_score"] > 0.10


def test_every_flagged_pool_has_named_bots():
    for slug in FLAGGED:
        bots = [r for r in top_roundtrippers(trades(slug), k=50) if r["wash_bot"]]
        assert len(bots) >= 2, slug
        for b in bots:
            assert b["balance"] >= 0.90


# ---- cluster invariants ----

def test_cluster_named_bots_and_chain():
    c = read_json(os.path.join(ROOT, "cluster.json"))
    assert c["n_named_bots"] >= 14
    # the longest creation chain spans several distinct fresh wallets
    longest = max((ch for chs in c["creation_chains"].values() for ch in chs), key=len)
    assert len(longest) >= 5
    assert len(set(longest)) == len(longest)            # all distinct


def test_qqqx_two_balanced_bots():
    bots = sorted([r for r in top_roundtrippers(trades("QQQX__raydium__EibwWLHy"), k=50) if r["wash_bot"]],
                  key=lambda r: -r["matched_usd"])
    assert len(bots) >= 2
    top = bots[0]
    assert top["buys"] >= 36 and top["sells"] >= 36
    assert top["balance"] >= 0.99


# ---- temporal invariants ----

def test_headline_bot_alternates_perfectly():
    ts = trades("QQQX__raydium__EibwWLHy")
    W = "C6FyA84D6JLtkSSyq45gcLFi67P3q61FhGohEFYd9rvF"
    seq = sorted((datetime.fromisoformat(t["block_timestamp"].replace("Z", "+00:00")).timestamp(), t["kind"])
                 for t in ts if t.get("tx_from_address") == W)
    kinds = [k for _, k in seq]
    alt = sum(1 for i in range(len(kinds) - 1) if kinds[i] != kinds[i + 1]) / (len(kinds) - 1)
    assert len(seq) >= 60
    assert alt == 1.0                                   # perfect buy/sell alternation


def test_earliest_bot_is_a_named_bot_not_an_intermediary():
    # the 'earliest bot' date must come from a named wash bot (2025), not an older funder (2024)
    t = read_json(os.path.join(ROOT, "temporal.json"))
    assert t["earliest_bot"] >= "2025-01-01"
    assert t["earliest_funder"] < t["earliest_bot"]    # intermediaries are older, reported separately


def test_persistence_recurs_with_full_wallet_rotation():
    p = read_json(os.path.join(ROOT, "persistence.json"))
    assert p["still_flagged"] >= 3                       # most pools re-flag at the later sample
    assert p["total_wallet_overlap"] == 0               # the fleet rotates wholesale between samples


def test_manufactured_volume_is_material():
    t = read_json(os.path.join(ROOT, "temporal.json"))
    assert t["matched_in_window_floor"] > 100000        # hard, directly-observed in-window floor
    # the two 24h extrapolations bracket the estimate and should both be material
    assert t["manufactured_24h_rate"] > 10_000_000
    assert t["manufactured_24h_share"] > t["manufactured_24h_rate"]


# ---- lifetime invariants ----

def _swap_files():
    return glob.glob(os.path.join(ROOT, "data", "raw", "wallet_swaps", "*.json"))


def test_lifetime_exceeds_in_window_floor():
    lf = read_json(os.path.join(ROOT, "lifetime.json"))
    t = read_json(os.path.join(ROOT, "temporal.json"))
    assert lf["n_bots"] == 14
    assert lf["total_swaps"] > 2000
    assert lf["total_matched_usd"] > t["matched_in_window_floor"]   # lifetime dwarfs the in-window floor


def test_lifetime_recomputes_from_committed_swaps():
    lf = read_json(os.path.join(ROOT, "lifetime.json"))
    rec_m = rec_n = 0
    for wf in _swap_files():
        sw = read_json(wf).get("swaps", [])
        bu = sum(x["usd"] for x in sw if x["side"] == "buy")
        su = sum(x["usd"] for x in sw if x["side"] == "sell")
        rec_m += round(2 * min(bu, su)); rec_n += len(sw)
    assert rec_m == lf["total_matched_usd"]
    assert rec_n == lf["total_swaps"]


def test_every_named_bot_is_lifetime_balanced():
    # each named bot is a wash bot over its FULL history too, not only in the snapshot window
    assert len(_swap_files()) == 14
    for wf in _swap_files():
        sw = read_json(wf).get("swaps", [])
        bu = sum(x["usd"] for x in sw if x["side"] == "buy")
        su = sum(x["usd"] for x in sw if x["side"] == "sell")
        assert min(bu, su) / max(bu, su) >= 0.90, wf
