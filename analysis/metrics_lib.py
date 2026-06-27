"""On-chain wash-trading detector (venue-agnostic, deterministic).

Operates on a list of DEX swaps, each a dict with at least:
    tx_from_address  (str)   the trader wallet
    kind             (str)   'buy' or 'sell'
    volume_in_usd    (float) USD size
    block_timestamp  (str)   ISO8601

THE DISCRIMINATOR (validated empirically against organic controls).

Pool-level "is the volume circular" does NOT separate wash from organic: over any
short window most active wallets in any liquid pool both buy and sell, so circular
share is high everywhere (WIF/JUP organic controls land at 70%+ too). The signal
that cleanly separates is at the WALLET level:

    a "wash bot" is a wallet that round-trips many times and lands ~flat:
        min(buys, sells) >= MIN_RT   and   min(buy_usd, sell_usd)/max(...) >= BAL

Such wallets buy and sell in matched size for no net position and no captured
spread - economically pointless unless volume itself is the goal. Organic pools
(WIF, JUP, and the real-trading xStock pools) contain ZERO of them; their busiest
wallets are directional arb (net buyer/seller, balance ~0.8) or one-sided real
flow. Washed pools are dominated by a handful of perfectly-balanced bots.

The pool score is the share of USD transacted by wash-bot wallets (0 for organic).
Concentration / circular / turnover are reported as corroborating context.
"""
from collections import defaultdict

MIN_RT = 5        # at least this many buys AND sells to qualify as a heavy round-tripper
BAL = 0.90        # USD balance (min/max of buy$ vs sell$) at or above this = lands ~flat


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def wallet_ledger(trades):
    """wallet -> [buys, sells, buy_usd, sell_usd]."""
    w = defaultdict(lambda: [0, 0, 0.0, 0.0])
    for t in trades:
        a = t.get("tx_from_address") or "?"
        u = _f(t.get("volume_in_usd"))
        if t.get("kind") == "buy":
            w[a][0] += 1; w[a][2] += u
        else:
            w[a][1] += 1; w[a][3] += u
    return w


def _balance(bu, su):
    return (min(bu, su) / max(bu, su)) if max(bu, su) else 0.0


def is_wash_bot(b, s, bu, su, min_rt=MIN_RT, bal=BAL):
    return min(b, s) >= min_rt and _balance(bu, su) >= bal


def metrics(trades, min_rt=MIN_RT, bal=BAL):
    n = len(trades)
    if n == 0:
        return dict(n_trades=0)
    led = wallet_ledger(trades)
    nw = len(led)
    by_count = sorted(led.values(), key=lambda v: -(v[0] + v[1]))
    top5 = sum(v[0] + v[1] for v in by_count[:5]) / n
    total_usd = sum(v[2] + v[3] for v in led.values())

    # the discriminator: USD share transacted by heavy, balanced round-trippers
    bot_usd = 0.0
    bot_trades = 0
    n_bots = 0
    for b, s, bu, su in led.values():
        if is_wash_bot(b, s, bu, su, min_rt, bal):
            n_bots += 1
            bot_usd += bu + su
            bot_trades += b + s
    wash_share = bot_usd / total_usd if total_usd else 0.0

    # corroborating context (not the score)
    matched = sum(2 * min(v[2], v[3]) for v in led.values())
    circular = matched / total_usd if total_usd else 0.0

    return dict(n_trades=n, n_wallets=nw, top5_share=round(top5, 4),
                n_wash_bots=n_bots, wash_bot_trade_share=round(bot_trades / n, 4),
                wash_share=round(wash_share, 4), circular_share=round(circular, 4),
                total_usd=round(total_usd, 0), wash_bot_usd=round(bot_usd, 0),
                score=round(wash_share, 4))


def top_roundtrippers(trades, k=12, min_rt=MIN_RT, bal=BAL):
    """The k wallets with the most matched (buy+sell) USD; flag which qualify as wash bots."""
    led = wallet_ledger(trades)
    rows = []
    for w, (b, s, bu, su) in led.items():
        if b > 0 and s > 0:
            rows.append(dict(wallet=w, buys=b, sells=s, buy_usd=round(bu, 0), sell_usd=round(su, 0),
                             matched_usd=round(2 * min(bu, su), 0), balance=round(_balance(bu, su), 3),
                             wash_bot=is_wash_bot(b, s, bu, su, min_rt, bal)))
    rows.sort(key=lambda r: -r["matched_usd"])
    return rows[:k]
