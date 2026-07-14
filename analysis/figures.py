"""Publication-quality figures for the post, from the committed data + JSON outputs.

  signature.png     buy$ vs sell$ per wallet: wash bots sit on the diagonal, organic off
  cadence.png       a named bot's perfect buy/sell alternation and flat net position
  funding.png       the TSLAX creation/peel chain with stablecoin seeds
  manufactured.png  reported vs manufactured 24h volume per flagged pool
"""
import os
import glob
from datetime import datetime
from collections import defaultdict
import matplotlib
from io_util import read_json
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# matplotlib stamps a Software tag and a date into the PNG, so a rerun writes byte-different
# files with identical pixels. Strip both, so rerunning the pipeline leaves the tree clean.
PNG_META = {"Software": None, "Creation Time": None}

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAWT = os.path.join(ROOT, "data", "raw", "trades")
RAWW = os.path.join(ROOT, "data", "raw", "wallets")
POST = os.path.join(ROOT, "post")
os.makedirs(POST, exist_ok=True)
FLAGGED = ["TSLAX__orca__9p7abUFv", "QQQX__raydium__EibwWLHy", "SPYX__raydium__4pCZCVEi",
           "SPYX__orca__gef4pD5g", "SPYX__orca__6m6UoVxn"]
ORANGE, GREEN, GRAY, BLUE = "#d9480f", "#2f9e44", "#adb5bd", "#1c7ed6"


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


def is_bot(b, s, bu, su):
    return min(b, s) >= 5 and (min(bu, su) / max(bu, su) if max(bu, su) else 0) >= 0.90


# ---- 1. signature scatter: buy$ vs sell$ per wallet ----
def fig_signature():
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 5.2))
    for ax, title, pools in [(a1, "Flagged xStock pools", FLAGGED),
                             (a2, "Organic control (WIF / JUP)", sorted(glob.glob(os.path.join(RAWT, "CTRL_*.json"))))]:
        bx, by, ox, oy = [], [], [], []
        for p in pools:
            fn = p if p.endswith(".json") else os.path.join(RAWT, p + ".json")
            for w, (b, s, bu, su) in ledger(read_json(fn)["trades"]).items():
                if bu <= 0 and su <= 0:
                    continue
                if is_bot(b, s, bu, su):
                    bx.append(bu); by.append(su)
                else:
                    ox.append(max(bu, 1)); oy.append(max(su, 1))
        lim = max(bx + by + ox + oy + [100])
        ax.plot([1, lim], [1, lim], "--", color="#868e96", lw=1, label="buy \\$ = sell \\$ (round-trip)")
        ax.scatter(ox, oy, s=14, color=GRAY, alpha=0.6, label="other wallets")
        if bx:
            ax.scatter(bx, by, s=40, color=ORANGE, edgecolor="k", lw=0.4, zorder=3, label="wash bots (balanced)")
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_xlabel("USD bought"); ax.set_ylabel("USD sold")
        ax.set_title(title, fontsize=11); ax.legend(fontsize=8, loc="upper left")
    fig.suptitle("Wash bots buy and sell in matched size (on the diagonal); organic wallets do not", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "signature.png"), dpi=120, metadata=PNG_META); plt.close()


# ---- 2. cadence: perfect alternation + flat net position ----
def fig_cadence():
    d = read_json(os.path.join(RAWT, "QQQX__raydium__EibwWLHy.json"))
    W = "C6FyA84D6JLtkSSyq45gcLFi67P3q61FhGohEFYd9rvF"
    seq = sorted((datetime.fromisoformat(t["block_timestamp"].replace("Z", "+00:00")).timestamp(),
                  t["kind"], f(t["volume_in_usd"])) for t in d["trades"] if t.get("tx_from_address") == W)
    t0 = seq[0][0]
    mins = [(t - t0) / 60 for t, _, _ in seq]
    net = np.cumsum([u if k == "buy" else -u for _, k, u in seq])
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(11, 5.6), sharex=True)
    for (_, k, _u), m in zip(seq, mins):
        a1.vlines(m, 0, 1 if k == "buy" else -1, color=(GREEN if k == "buy" else ORANGE), lw=1.4)
    a1.axhline(0, color="k", lw=0.6)
    a1.set_yticks([1, -1]); a1.set_yticklabels(["buy", "sell"])
    a1.set_title(f"Wallet {W[:8]}.. on QQQX/Raydium: {len(seq)} swaps, perfect buy/sell alternation", fontsize=11)
    a2.plot(mins, net, color=BLUE, lw=1.5)
    a2.axhline(0, color="#868e96", lw=0.8, ls="--")
    a2.fill_between(mins, net, 0, color=BLUE, alpha=0.12)
    a2.set_ylabel("cumulative net position (USD)"); a2.set_xlabel("minutes from first swap")
    a2.set_title("Net position never departs from flat: volume is manufactured, no position is taken", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "cadence.png"), dpi=120, metadata=PNG_META); plt.close()


# ---- 3. funding peel chain ----
def fig_funding():
    edges = {w: dict(parent=ff, seed=sd) for ff, w, sd, n in
             read_json(os.path.join(ROOT, "data", "funding_edges.json"))["edges"]}
    # the full chain in the committed data, which is also the longest one cluster.json finds
    # for this pool. The trace stops at H9c7D19P: it has no incoming edge in funding_edges.
    chain = ["H9c7D19P", "85zuUQ5w", "8gw6JyEW", "FMMs8SGx", "AtzmNv2w", "vwbEYDGU", "2eTkWQyt"]
    full = {}
    for k in list(edges) + [e["parent"] for e in edges.values()]:
        full[k[:8]] = k
    nodes = [full.get(c[:8], c) for c in chain]
    seeds = [edges.get(n, {}).get("seed") for n in nodes]
    # sanity: every drawn arrow must correspond to a real edge in the committed data
    for child, parent in zip(nodes[1:], nodes[:-1]):
        assert edges.get(child, {}).get("parent") == parent, ("funding chain edge missing", child, parent)
    # colour by role, read from the data rather than by position: the wallets that actually
    # trade the pool are orange, the ones that only funded them are grey.
    bots = {r["wallet"] for r in read_json(os.path.join(ROOT, "data", "named_wallets.json"))
            if r["pool"] == "TSLAX/orca"}
    colors = [ORANGE if n in bots else GRAY for n in nodes]
    fig, ax = plt.subplots(figsize=(11, 3.2))
    x = list(range(len(nodes)))
    ax.scatter(x, [0] * len(nodes), s=520, color=colors, edgecolor="k", zorder=3)
    for i in range(len(nodes) - 1):
        ax.annotate("", xy=(i + 1, 0), xytext=(i, 0),
                    arrowprops=dict(arrowstyle="-|>", color="#495057", lw=1.6))
        s = seeds[i + 1]
        if s:
            ax.text(i + 0.5, 0.12, f"{s:.2f}\nUSDT", ha="center", va="bottom", fontsize=8, color="#495057")
    for i, n in enumerate(nodes):
        ax.text(i, -0.18, n[:6] + "..", ha="center", va="top", fontsize=8, family="monospace")
    ax.text(0, 0.30, "top of traced chain", ha="center", fontsize=8, color="#495057")
    ax.text(len(nodes) - 1, 0.30, "trades TSLAX", ha="center", fontsize=8, color="#495057")
    ax.text(-0.45, -0.45, "grey: funded the fleet but does not trade the pool     "
                          "orange: wash bot in TSLAX/Orca", fontsize=8, color="#495057")
    ax.set_ylim(-0.6, 0.6); ax.set_xlim(-0.5, len(nodes) - 0.5); ax.axis("off")
    ax.set_title("TSLAX/Orca wash fleet: a peel chain, every wallet after the first created and seeded by the one before it\n"
                 "(seeds fall in steps of 4.3 to 4.6 USDT - automated sequential deployment)", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "funding.png"), dpi=120, metadata=PNG_META); plt.close()


# ---- 4. measured wash share per pool (the robust quantity) + matched-USD floor ----
def fig_manufactured():
    T = read_json(os.path.join(ROOT, "temporal.json"))
    items = sorted(T["pools"].items(), key=lambda kv: -kv[1]["wash_share"])
    labels = [k.split(" ")[0].replace("/", "/\n") for k, _ in items]
    share = [p["wash_share"] * 100 for _, p in items]
    matched = [p["matched_in_window"] for _, p in items]
    win = [p["window_h"] for _, p in items]
    x = np.arange(len(items))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x, share, color=ORANGE, width=0.7)
    for i, (s, m, w) in enumerate(zip(share, matched, win)):
        ax.text(i, s + 1.5, f"{s:.0f}%", ha="center", fontsize=9, fontweight="bold")
        ax.text(i, s / 2, f"${m/1e3:.0f}k\nmatched\n({w:.1f}h win)", ha="center", va="center", fontsize=7.5, color="white")
    ax.set_xticks(x); ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("self-cancelling share of volume, in-window (%)"); ax.set_ylim(0, 95)
    ax.set_title("Measured wash share per flagged pool (in the snapshot window), with the matched-USD floor.\n"
                 f"Hard floor across all five: ${T['matched_in_window_floor']/1e3:.0f}k matched; "
                 f"24h extrapolation is a wide range (${T['manufactured_24h_rate']/1e6:.0f}M-${T['manufactured_24h_share']/1e6:.0f}M), see text", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "manufactured.png"), dpi=120, metadata=PNG_META); plt.close()


# ---- 5. balance distribution of heavy round-trippers: the bimodality that justifies the 0.90 cut ----
def fig_balance():
    flagged_b, control_b = [], []
    for fn in sorted(glob.glob(os.path.join(RAWT, "*.json"))):
        slug = os.path.basename(fn)[:-5]
        d = read_json(fn)
        for b, s, bu, su in ledger(d["trades"]).values():
            if min(b, s) >= 5 and max(bu, su) > 0:                  # heavy round-trippers only
                bal = min(bu, su) / max(bu, su)
                (flagged_b if slug in FLAGGED else control_b).append(bal)
    rng = np.random.default_rng(0)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    for ys, vals, col, lab in [(1, flagged_b, ORANGE, f"flagged pools (n={len(flagged_b)})"),
                               (0, control_b, GREEN, f"all other pools (n={len(control_b)})")]:
        jit = ys + rng.uniform(-0.16, 0.16, len(vals))
        ax.scatter(vals, jit, s=45, color=col, alpha=0.75, edgecolor="k", lw=0.3, label=lab)
    ax.axvline(0.90, ls="--", color="#495057", lw=1.2)
    ax.text(0.905, 1.45, "wash-bot cut (0.90)", fontsize=9, color="#495057")
    n_fl = sum(1 for b in flagged_b if b >= 0.90); n_ct = sum(1 for b in control_b if b >= 0.90)
    ax.text(0.955, 1.0, f"{n_fl}/{len(flagged_b)}", ha="center", fontsize=9, color=ORANGE, fontweight="bold")
    ax.text(0.955, 0.0, f"{n_ct}/{len(control_b)}", ha="center", fontsize=9, color=GREEN, fontweight="bold")
    ax.set_yticks([0, 1]); ax.set_yticklabels(["other pools", "flagged pools"])
    ax.set_xlabel("USD balance of each heavy round-tripper  (min(buy\\$, sell\\$) / max)")
    ax.set_xlim(-0.02, 1.05); ax.set_ylim(-0.5, 1.8)
    ax.set_title("Heavy round-trippers are bimodal: in flagged pools they sit at near-perfect balance;\n"
                 "in every other pool they are directional. The 0.90 cut falls in the empty gap.", fontsize=10.5)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "balance.png"), dpi=120, metadata=PNG_META); plt.close()


# ---- 6. lifetime vs in-window matched per wallet: the snapshot caught a sliver ----
def fig_lifetime():
    life = read_json(os.path.join(ROOT, "lifetime.json"))["bots"]
    clu = read_json(os.path.join(ROOT, "cluster.json"))["pools"]
    inwin = {}
    for p in clu.values():
        for b in p["bots"]:
            inwin[b["wallet"]] = inwin.get(b["wallet"], 0) + b["matched_usd"]
    rows = sorted(life, key=lambda r: -r["matched_usd"])
    labels = [r["wallet"][:6] + ".." for r in rows]
    life_v = [r["matched_usd"] for r in rows]
    win_v = [max(inwin.get(r["wallet"], 0), 1) for r in rows]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(y + 0.21, life_v, height=0.42, color=ORANGE, label="lifetime matched (full on-chain history)")
    ax.barh(y - 0.21, win_v, height=0.42, color="#f2c29b", label="in-window matched (snapshot)")
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8, family="monospace"); ax.invert_yaxis()
    ax.set_xscale("log"); ax.set_xlabel("matched USD, log scale")
    ax.legend(fontsize=9, loc="lower right")
    ax.set_title("Each named bot's wash: the snapshot window caught only a sliver of the lifetime total\n"
                 f"14 wallets, \\${sum(life_v)/1e6:.1f}M matched lifetime against the \\$467k in-window floor", fontsize=10.5)
    fig.tight_layout()
    fig.savefig(os.path.join(POST, "lifetime.png"), dpi=120, metadata=PNG_META); plt.close()


if __name__ == "__main__":
    fig_signature(); fig_cadence(); fig_funding(); fig_manufactured(); fig_balance(); fig_lifetime()
    print("wrote post/signature.png, cadence.png, funding.png, manufactured.png, balance.png, lifetime.png")
