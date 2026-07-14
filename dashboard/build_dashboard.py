"""Build a self-contained dark dashboard (index.html) for GitHub Pages.

Reads the committed JSON outputs and embeds the figures as base64 so the page is
a single file with no external assets.
"""
import os
import base64

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
import sys as _sys
_sys.path.insert(0, os.path.join(ROOT, "analysis"))
from io_util import read_json, write_text
S = read_json(os.path.join(ROOT, "screen.json"))
C = read_json(os.path.join(ROOT, "cluster.json"))
T = read_json(os.path.join(ROOT, "temporal.json"))
N = read_json(os.path.join(ROOT, "data", "named_wallets.json"))
P = read_json(os.path.join(ROOT, "persistence.json"))
L = read_json(os.path.join(ROOT, "lifetime.json"))
R = read_json(os.path.join(ROOT, "routing.json"))


def b64(name):
    with open(os.path.join(ROOT, "post", name), "rb") as fh:
        return base64.b64encode(fh.read()).decode()


fig = {n: b64(n) for n in ["screen.png", "signature.png", "cadence.png", "funding.png", "manufactured.png", "balance.png", "lifetime.png"]}

flagged = [m for m in S["markets"] if m["flag"]]
controls = [m for m in S["markets"] if m["calib_control"]]
srows = "".join(
    '<tr%s><td class="num">%d</td><td class="txt">%s/%s</td><td class="num">%s</td><td class="num">%s</td><td class="num">%d</td>'
    '<td class="num">%.0f%%</td><td class="num">%s</td><td>%s</td></tr>'
    % (' class="flag"' if m["flag"] else "", m["rank"], m["symbol"], m["dex"], f'{m["n_trades"]:,}',
       f'{m["window_h"]:.1f}h' if m.get("window_h") is not None else "-",
       m["n_wash_bots"], m["wash_share"] * 100,
       f'{m["turnover"]:.0f}x' if m["turnover"] is not None else "-",
       "WASH" if m["flag"] else ("calib" if m["calib_control"] else "clean"))
    for m in S["markets"])

# named_wallets.json has one row per (wallet, pool); collapse to one row per wallet (its
# largest-volume pool) so a multi-pool wallet is not listed twice, then order by volume.
_best = {}
for w in N:
    k = w["wallet"]
    if k not in _best or (w["buy_usd"] + w["sell_usd"]) > (_best[k]["buy_usd"] + _best[k]["sell_usd"]):
        _best[k] = w
# the display string "SPYX/orca" is the same for two DIFFERENT Orca pools, so show the pool id too
wrows = "".join(
    '<tr><td class="txt">%s <span class="mono" style="color:var(--muted)">%s</span></td>'
    '<td class="mono">%s</td><td class="num">%d / %d</td><td class="num">$%s / $%s</td></tr>'
    % (w["pool"], w["pool_id"][:8], w["wallet"], w["buys"], w["sells"],
       f'{w["buy_usd"]:,}', f'{w["sell_usd"]:,}')
    for w in sorted(_best.values(), key=lambda r: -(r["buy_usd"] + r["sell_usd"])))

CSS = """
:root{--bg:#0e1116;--panel:#161b22;--border:#2d333b;--text:#e6edf3;--muted:#8b949e;--accent:#58a6ff;--accent-2:#f0883e;--bad:#f85149;--good:#3fb950;
--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace;}
*,*::before,*::after{box-sizing:border-box;} body{background:var(--bg);color:var(--text);font-family:var(--sans);margin:0;line-height:1.55;}
a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
header{border-bottom:1px solid var(--border);padding:30px 44px;background:linear-gradient(180deg,#161b22,#0e1116);}
header h1{margin:0 0 8px;font-size:23px;} header .meta{color:var(--muted);font-size:14px;}
main{padding:26px 44px;max-width:1180px;margin:0 auto;} .lead{font-size:16px;margin:0 0 22px;} .lead strong{color:var(--accent-2);}
.grid{display:grid;gap:15px;grid-template-columns:repeat(4,1fr);} @media(max-width:980px){.grid{grid-template-columns:repeat(2,1fr);}} @media(max-width:560px){.grid{grid-template-columns:1fr;}main,header{padding:18px 16px;}}
.stat{background:var(--panel);border:1px solid var(--border);padding:17px 19px;border-radius:10px;}
.stat .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.4px;} .stat .value{font-size:25px;font-weight:700;margin-top:4px;font-family:var(--mono);}
.stat .sub{color:var(--muted);font-size:12px;margin-top:4px;} .stat.bad .value{color:var(--bad);} .stat.good .value{color:var(--good);} .stat.accent .value{color:var(--accent-2);}
section{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:20px 24px;margin:17px 0;}
section h2{margin:0 0 6px;font-size:18px;} section .sub{color:var(--muted);font-size:14px;margin-bottom:13px;}
.figure{background:#fff;border:1px solid var(--border);border-radius:8px;padding:8px;text-align:center;} .figure img{max-width:100%;height:auto;}
table{width:100%;border-collapse:collapse;margin:4px 0;font-size:13px;} th,td{border-bottom:1px solid var(--border);text-align:left;padding:6px 11px;}
th{color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:.4px;} td.num{font-family:var(--mono);text-align:right;} td.txt{font-family:var(--mono);} td.mono{font-family:var(--mono);font-size:11px;}
tr.flag td{background:rgba(248,81,73,.10);font-weight:600;} .tnote{color:var(--muted);font-size:12.5px;margin-top:10px;}
.keyfindings{background:linear-gradient(135deg,#1c232c,#161b22);border-left:3px solid var(--accent-2);} .keyfindings h2{color:var(--accent-2);}
footer{color:var(--muted);font-size:13px;padding:20px 44px;border-top:1px solid var(--border);margin-top:26px;}
"""

manu_floor = T["matched_in_window_floor"]
manu_lo, manu_hi = T["manufactured_24h_rate"], T["manufactured_24h_share"]
HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>On-chain wash trading in Solana's tokenized stocks | Market Health</title>
<meta name="viewport" content="width=device-width, initial-scale=1"><style>{CSS}</style></head><body>
<header><h1>A wash-trading signature in Solana's tokenized stocks: five xStock pools carrying matched-trade bot fleets</h1>
<div class="meta">DN Institute Market Health Wiki | <a href="https://github.com/mkzung/solana-xstocks-wash-analysis">github.com/mkzung/solana-xstocks-wash-analysis</a> | Max Gorbuk<br>
Free Dexscreener + GeckoTerminal + Solana RPC + Helius data | snapshot 2026-06-21 | {S['n_pools']} pools screened</div></header>
<main>
<p class="lead">A wallet-level detector scored the liquid xStock pools on Solana. <strong>{S['n_flagged']}</strong> exhibit a wash-trading signature: automated wallets that buy and sell in matched size, alternate buy and sell at a near-fixed cadence, and trace to coordinated funding. Every other pool, including the same xStocks in their other pools, scores at most {S['max_nonflagged_score']:.2f}. A flag on the on-chain pattern, not on any identified person; each claim is a named wallet and a transaction hash.</p>
<p class="lead" style="font-size:13px;color:var(--muted)">Scope: the flagged conduct is by pseudonymous automated wallets. Nothing here indicates Backed Finance, Kraken, the Solana Foundation, Raydium, or Orca operate, know of, or benefit from these wallets; xStock pools are permissionless. Whether the wallets acted with intent to mislead, the element wash trading requires in law, is not established here.</p>
<div class="grid">
  <div class="stat bad"><div class="label">Flagged pools</div><div class="value">{S['n_flagged']} / {S['n_pools']}</div><div class="sub">score 0.36-0.80, every other pool &le; {S['max_nonflagged_score']:.2f}</div></div>
  <div class="stat accent"><div class="label">Named wash bots</div><div class="value">{C['n_named_bots']}</div><div class="sub">balanced heavy round-trippers, all on-chain</div></div>
  <div class="stat accent"><div class="label">Self-cancelling volume</div><div class="value">${manu_floor/1e3:.0f}k</div><div class="sub">matched, in-window, hard floor; 24h extrapolation ${manu_lo/1e6:.0f}M-${manu_hi/1e6:.0f}M (see post)</div></div>
  <div class="stat bad"><div class="label">Lifetime matched</div><div class="value">${L['total_matched_usd']/1e6:.1f}M</div><div class="sub">{L['total_swaps']:,} swaps over the 14 wallets' full history; one wallet ${L['max_bot_matched_usd']/1e6:.1f}M</div></div>
</div>
<section class="keyfindings"><h2>What the data says</h2><ol>
<li><b>Five pools flagged, a clean gap.</b> The wash score (USD share from balanced heavy round-trippers) is 0.36 to 0.80 on the five flagged pools; the two a-priori organic controls (WIF, JUP) score zero, and every other pool - including the same xStocks in their other pools - scores at most {S['max_nonflagged_score']:.2f}.</li>
<li><b>The signature is matched buys and sells.</b> Organic pools contain zero balanced heavy round-trippers; the flagged pools are dominated by them. On QQQX the busiest wallet bought $10,657 and sold $10,695 across 36 buys and 36 sells. The tokens come back too: netting each bot's xStock units leaves a median {R['token_flatness']['median_abs_net_over_gross']:.2%} of the units it turned over.</li>
<li><b>Not cross-pool arbitrage, though the swaps are routed.</b> No bot transaction buys in one pool and sells in another, while {R['mixed_side_tx_in_snapshot']} transactions in the snapshot do exactly that, by other wallets - and no bot is buy-heavy in one pool while sell-heavy in another, which is what arbitraging two pools minutes apart would leave behind. The bots' swaps are often split by an aggregator across pools inside one transaction ({R['bot_routed_usd_share']:.0%} of their volume), so a pool tape shows a leg, not a whole swap - the wallet still signs and pays for its own trade.</li>
<li><b>The bots run on a robot's clock.</b> That wallet's 72 swaps alternate buy/sell with no exception; its net position sawtooths and never leaves flat. Three TSLAX wallets run the same 4-5 second cadence back-to-back.</li>
<li><b>A coordinated fleet.</b> Seven TSLAX wallets form a creation chain - the five wash bots and the two that funded them. Every wallet after the first was created and seeded, ~500 USDT, by the one before it; the six seeds fall in steps of 4.3 to 4.6 USDT. Three SPYX wallets run identical parameters; counting only its own transactions, not the legs of routed swaps, one wallet round-trips SPYX in all three of its pools.</li>
<li><b>It is the pool, not the token.</b> QQQX is flagged in one Raydium pool and clean in another; TSLAX is flagged on Orca and clean on Raydium. The bots predate the pools (earliest {T['earliest_bot']}).</li>
<li><b>It recurs, the wallets do not.</b> Re-sampled six hours later, {P['still_flagged']} of {P['n_pools']} pools are again actively washed and not one bot reappears ({P['total_wallet_overlap']} wallet overlap) - bursts of matched round-tripping by a rotating wallet fleet.</li>
<li><b>The snapshot caught a sliver.</b> Across the fourteen wallets' full on-chain history the directly-observed matched total is ${L['total_matched_usd']/1e6:.1f}M in {L['total_swaps']:,} swaps (one wallet alone ${L['max_bot_matched_usd']/1e6:.1f}M), each wallet's washing concentrated in a multi-day burst - more than ten times the in-window floor.</li>
</ol></section>
<section><h2>The screen: the liquid Solana xStock pools</h2><div class="sub">Wash score = USD share transacted by wallets that buy and sell the pool &ge;5x each within 10% of flat. Five flagged, calibrated above every organic control.</div><div class="figure"><img src="data:image/png;base64,{fig['screen.png']}" alt="venue screen"></div>
<table><thead><tr><th>#</th><th>pool</th><th>swaps</th><th>window</th><th>bots</th><th>wash%</th><th>turnover</th><th>tag</th></tr></thead><tbody>{srows}</tbody></table>
<div class="tnote">window = time span of the most-recent-300-swap snapshot; wash% is measured within it. turnover = 24h volume / pool liquidity (an independent signal the detector does not use).</div>
<div class="tnote">turnover = 24h volume / pool liquidity, an independent signal the detector does not use; it corroborates every flag (34x-1624x vs &le;5x for controls).</div>
<div class="tnote">Window confound: wash share is window-sensitive - sliced to the shortest flagged window (~{S['subwindow_robustness']['equal_window_h']}h), {S['subwindow_robustness']['n_nonflagged_subwindow_above_flag']} non-flagged pools show a lone round-tripper above the flag. The robust discriminator is the full-window fleet: no non-flagged pool carries more than {S['subwindow_robustness']['max_nonflagged_fullwindow_wash_bots']} balanced bot over its snapshot, while every flagged pool carries &ge; {S['subwindow_robustness']['min_flagged_n_bots']} and those fleets persist, share funding, and cycle millions lifetime.</div></section>
<section><h2>Why the 0.90 cut is not arbitrary</h2><div class="sub">USD balance of every heavy round-tripper. Flagged-pool wallets (orange) form a distinct mode at near-perfect balance; in every other pool (green) they are directional. 18 of 33 clear the cut against 1 of 22, medians 0.94 vs 0.66, and the two distributions barely overlap. No p-value is quoted: the pools are flagged on the volume share of these same balanced wallets, so a test of flagged against non-flagged on that count would only measure the selection. The clean comparison is the a-priori controls, WIF and JUP, which carry three heavy round-trippers and not one at this balance.</div><div class="figure"><img src="data:image/png;base64,{fig['balance.png']}" alt="balance bimodality"></div></section>
<section><h2>The signature: matched buys and sells</h2><div class="sub">USD bought vs USD sold per wallet. Wash bots sit on the diagonal; organic wallets are directional or one-sided.</div><div class="figure"><img src="data:image/png;base64,{fig['signature.png']}" alt="signature scatter"></div></section>
<section><h2>The mechanism: a robot that never takes a position</h2><div class="sub">Wallet C6FyA84D on QQQX: 72 swaps in perfect buy/sell alternation; cumulative net position never leaves flat.</div><div class="figure"><img src="data:image/png;base64,{fig['cadence.png']}" alt="cadence"></div></section>
<section><h2>The coordination: a fleet built from one funding chain</h2><div class="sub">The TSLAX fleet as a creation chain: seven wallets, every one after the first created and seeded by the wallet before it, the six seeds falling in steps of 4.3 to 4.6 USDT. Grey funded the fleet; orange trades the pool.</div><div class="figure"><img src="data:image/png;base64,{fig['funding.png']}" alt="funding chain"></div></section>
<section><h2>The scale</h2><div class="sub">Measured self-cancelling share per pool with the matched-USD floor; the 24h dollar figure is a wide extrapolation (${manu_lo/1e6:.0f}M-${manu_hi/1e6:.0f}M), see the post.</div><div class="figure"><img src="data:image/png;base64,{fig['manufactured.png']}" alt="wash share per pool"></div></section>
<section><h2>The snapshot caught a sliver</h2><div class="sub">Each named bot's matched USD: the snapshot window against its full on-chain history (log scale). The 14 wallets cycled ${L['total_matched_usd']/1e6:.1f}M lifetime, more than ten times the in-window floor.</div><div class="figure"><img src="data:image/png;base64,{fig['lifetime.png']}" alt="lifetime vs in-window matched per wallet"></div></section>
<section><h2>The flagged wallets</h2><div class="sub">Every wallet buys and sells the same pool in matched size. Paste any into solscan.io to verify.</div>
<table><thead><tr><th>pool</th><th>wallet</th><th>buys / sells</th><th>bought / sold</th></tr></thead><tbody>{wrows}</tbody></table></section>
<footer>Data: Dexscreener + GeckoTerminal APIs + public Solana RPC (key-less) + Helius enhanced API (free tier, lifetime totals only), snapshot 2026-06-21. Reproducible: screen.py, cluster.py, temporal.py, persistence.py, lifetime.py, verify.py over committed data. A flag on automated, self-cancelling trading and its on-chain funding structure, not an identification of who controls the wallets or why.</footer>
</main></body></html>"""

for name in ("index.html", "dashboard.html"):
    write_text(HTML, os.path.join(ROOT, name))
print("wrote index.html + dashboard.html (%d bytes)" % len(HTML))
