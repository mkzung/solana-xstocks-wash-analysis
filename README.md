# Wash trading in Solana's tokenized stocks (xStocks)

A wallet-level forensic analysis of wash trading in on-chain [xStocks](https://xstocks.com)
pools on Solana, for the [DN Institute](https://github.com/1712n/dn-institute) market-health
wiki. Companion to the centralized-exchange study
[gate-xstocks-wash-analysis](https://github.com/mkzung/gate-xstocks-wash-analysis).

[![test](https://github.com/mkzung/solana-xstocks-wash-analysis/actions/workflows/test.yml/badge.svg)](https://github.com/mkzung/solana-xstocks-wash-analysis/actions/workflows/test.yml)

**Live dashboard:** [mkzung.github.io/solana-xstocks-wash-analysis](https://mkzung.github.io/solana-xstocks-wash-analysis/)

## Finding

A detector scored the liquid xStock pools on Solana. **Five pools exhibit a wash-trading
signature** (score 0.36 to 0.80); the a-priori organic controls (WIF, JUP) score zero, and
every other pool, including the same xStocks in their other pools, scores at most **0.06**.

This is a flag on an on-chain trading **pattern**, not a finding that any person acted with the
intent to mislead that wash trading requires in law, and not a claim about the issuer or venues.

The flag is wallet-level: a **balanced heavy round-tripper** is a wallet that buys *and*
sells the same pool at least five times each and lands within 10% of flat. Organic pools
contain none; the flagged pools are dominated by them. The bots:

- **buy and sell in matched size** (QQQX's busiest wallet: bought $10,657, sold $10,695),
- **alternate buy/sell perfectly** over dozens of swaps, net position never leaving flat,
- are a **coordinated fleet**: in TSLAX/Orca seven wallets form a creation chain - every wallet
  after the first created and seeded, ~500 USDT, by the one before it, the six seeds falling in
  steps of 4.3 to 4.6 USDT; three SPYX wallets run identical parameters; two wallets work SPYX in
  both its pools,
- **predate the pools** - a mix of aged wallets (some on-chain since 2025-10, with no xStock activity until recently) and same-day creations; funding wallets back to 2024-12,
- **recur with full rotation**: re-sampled six hours later, three of the five pools are again washed and not one bot reappears (`persistence.py`) - bursts by a rotating wallet fleet.

Every named wallet, transaction, funding seed, and pool identity in this analysis was verified
**live against Solana RPC** (all 14 wallets exist and are keypairs, not routers; every funding
seed matches on-chain to the cent). The account-owner snapshot is committed in
`data/raw/wallet_owners.json`, so `analysis/verify.py` re-asserts it offline with every other claim.

It is the **pool, not the token**: QQQX is flagged in one Raydium pool and clean in another;
TSLAX is flagged on Orca and clean on Raydium. In the measured windows the bots round-tripped
**$467k** of self-cancelling buy-and-sell (a hard, directly-observed floor). A 24h figure is an
extrapolation and the two natural methods disagree by about threefold in aggregate (**$32M-$102M/day**
across the five pools), and by far more on an individual pool - widest on QQQX, where the share method
implies **$26M** against **under $1M** from that pool's own observed bot rate. Both assume the snapshot
behaviour persists, which the six-hour re-sample contradicts; the floor and the per-pool shares are the
claims to rely on. Following the fourteen named wallets through their **full
on-chain history** lifts the directly-observed matched total to **$5.6M** in 2,836 swaps (one
wallet alone $2.9M) - more than ten times the in-window floor - with each wallet's washing
concentrated in a burst of days, the rotating-fleet pattern again.

The matched buy/sell capture no spread - both legs are in one pool, and the sells return about
**99.3%** of what the buys cost, a sub-1% loss to fees. An offsetting leg on a venue this data does
not cover cannot be excluded, but nothing in the pool pays for the round trip. It is not aggregator
routing either: each address is a plain keypair, each trade its own transaction.
Every claim is a named wallet and a transaction hash, checkable on [solscan.io](https://solscan.io).

## Reproduce

```bash
pip install -r requirements.txt
python analysis/screen.py        # venue screen + controls        -> screen.json
python analysis/cluster.py       # named bots, creation chains     -> cluster.json
python analysis/temporal.py      # cadence, onset, manufactured    -> temporal.json
python analysis/persistence.py   # primary vs +6h re-sample        -> persistence.json
python analysis/lifetime.py      # lifetime washing totals         -> lifetime.json
python analysis/named_wallets.py # flagged-wallet table            -> data/named_wallets.json
python analysis/figures.py       # the figures                     -> post/*.png
python analysis/verify.py        # independent re-check (asserts)
python -m pytest tests/ -q
```

All of the above runs over the **committed snapshot** in `data/raw/` (no network, deterministic);
CI reruns it on every push. To refresh the snapshot from live data:

```bash
python analysis/fetch_raw.py     # Dexscreener + GeckoTerminal (trades + OHLCV)
python analysis/fund_trace.py    # Solana RPC: wallet funding origins
python analysis/trace_tree.py    # Solana RPC: walk the funding tree
WH_HELIUS_KEY=...  python analysis/wallet_history.py   # Helius enhanced API: each bot's full swap history
python analysis/owner_check.py   # Solana RPC: confirm each bot is a System-Program keypair (not a router)
```

## Data sources (all free)

- **Dexscreener API** - pool universe, 24h volume, liquidity, turnover. *(no key)*
- **GeckoTerminal API** - tx-level swaps (wallet, hash, side, USD) and OHLCV history. *(no key)*
- **Solana JSON-RPC** (public endpoints) - wallet funding traces and account-owner checks (each bot is a System-Program keypair, not a router). *(no key)*
- **Helius enhanced-transactions API** (free tier) - each named bot's full lifetime swap history, used only for the lifetime totals in "The scale". The collected swaps are committed, so the totals recompute deterministically without a key.

## Layout

```
analysis/     metrics_lib.py (detector) + screen / cluster / temporal / persistence / lifetime / named_wallets / verify / figures
              collectors (run once, network): fetch_raw / fund_trace / trace_tree / wallet_history / owner_check
data/raw/     committed snapshot: trades/, ohlcv/, wallets/ (funding traces), wallet_swaps/ (histories), wallet_owners.json
data/         universe.json, screen.csv, funding_edges.json, named_wallets.json
*.json        screen / cluster / temporal / persistence / lifetime outputs
post/         index.md (the wiki post) + figures
dashboard/    build_dashboard.py -> index.html (GitHub Pages)
tests/        pytest invariants
```

## Scope and ethics

This characterises a **pattern of automated, self-cancelling trading** and its on-chain funding
structure. Solana addresses are pseudonymous; the wallets are demonstrably coordinated with each
other, but the analysis does not identify who controls them or why, and the funding trace is
depth-capped (it does not claim a single named operator or exchange of origin). It is a flag on
behaviour, not a legal verdict. Motive is left open: documented incentives include DEX-aggregator
volume rankings and Solana liquidity-mining programs, but no issuer rebate-per-volume is assumed.
