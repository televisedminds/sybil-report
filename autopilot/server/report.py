"""Self-contained HTML reports for backtest results.

One file, zero external assets: open it anywhere, share it, archive it.
The comparison chart indexes every strategy to 100 at the start so different
cash levels compare fairly, with buy & hold as the dashed benchmark.
"""

from __future__ import annotations

import html as html_mod
import json
from datetime import datetime, timezone

from autopilot.server.page import html_page, safe_json


def _esc(text) -> str:
    return html_mod.escape(str(text), quote=True)

SERIES_VARS = ["--series-1", "--series-2", "--series-3", "--series-4"]

REPORT_SCRIPT = r"""
'use strict';
const DATA = window.__DATA__;
function el(id){ return document.getElementById(id); }

(function comparison() {
  const ts = DATA.ts;
  const series = DATA.strategies.map((s, i) => ({
    name: s.label, colorVar: DATA.colors[i % DATA.colors.length],
    values: s.index }));
  series.push({name: 'Buy & hold', colorVar: '--bench', dash: true,
    values: DATA.benchmark_index});
  lineChart(el('cmp-chart'), {ts, series, money: false, logToggle: true, height: 320});
})();

DATA.strategies.forEach((s, i) => {
  const box = el('detail-' + i);
  if (!box) return;
  lineChart(box, {ts: DATA.ts, money: true, height: 220, logToggle: false,
    series: [
      {name: s.label + ' equity', colorVar: DATA.colors[i % DATA.colors.length],
       wash: true, values: s.equity},
      {name: 'Buy & hold', colorVar: '--bench', dash: true, values: s.bench_equity},
    ]});
});
"""


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _cell(v, suffix="", cls="num", prefix="") -> str:
    if v is None:
        return f'<td class="{cls}">–</td>'
    if isinstance(v, float) and v == float("inf"):
        return f'<td class="{cls}">∞</td>'
    return f'<td class="{cls}">{prefix}{v:,}{suffix}</td>' if isinstance(v, int) \
        else f'<td class="{cls}">{prefix}{v:,.2f}{suffix}</td>'


def render_report(results: list[dict], title: str = "Autopilot backtest report") -> str:
    """results: list of BacktestResult.to_dict() run on the SAME candle set."""
    if not results:
        raise ValueError("no results to report")
    first = results[0]
    ts = [row[0] for row in first["equity_curve"]]
    closes = {row[0]: row[1] for row in first.get("closes", [])}
    close_list = [closes.get(t) for t in ts]
    first_close = next((c for c in close_list if c), 1.0)

    strategies = []
    for r in results:
        eq_map = {row[0]: row[1] for row in r["equity_curve"]}
        equity = [eq_map.get(t) for t in ts]
        start = r["start_cash"]
        strategies.append({
            "label": r["strategy"],
            "equity": equity,
            "index": [round(e / start * 100, 3) if e else None for e in equity],
            "bench_equity": [round(start * c / first_close, 2) if c else None
                             for c in close_list],
        })
    benchmark_index = [round(c / first_close * 100, 3) if c else None for c in close_list]

    data = {
        "ts": ts, "strategies": strategies, "benchmark_index": benchmark_index,
        "colors": SERIES_VARS,
    }

    period = f"{_fmt_ts(ts[0])} → {_fmt_ts(ts[-1])}"
    m0 = first["metrics"]

    header_cols = (
        "<th>strategy</th><th class='num'>total return</th><th class='num'>CAGR</th>"
        "<th class='num'>Sharpe</th><th class='num'>Sortino</th>"
        "<th class='num'>max drawdown</th><th class='num'>volatility</th>"
        "<th class='num'>exposure</th><th class='num'>fills</th>"
        "<th class='num'>win rate</th><th class='num'>profit factor</th>"
        "<th class='num'>fees</th><th class='num'>final equity</th>")

    rows = []
    for r in results:
        m = r["metrics"]
        rows.append(
            "<tr><td>" + _esc(r["strategy"]) + "</td>"
            + _cell(m["total_return_pct"], "%") + _cell(m["cagr_pct"], "%")
            + _cell(m["sharpe"]) + _cell(m["sortino"])
            + _cell(m["max_drawdown_pct"], "%") + _cell(m["volatility_pct"], "%")
            + _cell(m["exposure_pct"], "%") + _cell(m["n_fills"])
            + _cell(m["win_rate_pct"], "%") + _cell(m["profit_factor"])
            + _cell(m["fees_paid"], prefix="$") + _cell(m["final_equity"], prefix="$")
            + "</tr>")
    rows.append(
        "<tr><td>buy &amp; hold (benchmark)</td>"
        + _cell(m0["benchmark_return_pct"], "%") + "<td class='num'>–</td>"
        + "<td class='num'>–</td><td class='num'>–</td>"
        + _cell(m0["benchmark_max_drawdown_pct"], "%")
        + "<td class='num'>–</td><td class='num'>100.0%</td><td class='num'>1</td>"
        + "<td class='num'>–</td><td class='num'>–</td><td class='num'>–</td>"
        + "<td class='num'>–</td></tr>")

    details = []
    for i, (r, s) in enumerate(zip(results, strategies)):
        params = _esc(json.dumps(r["params"], sort_keys=True))
        details.append(f"""
<div class="card">
  <h2>{_esc(r["strategy"])} <span class="note">{params}</span></h2>
  <div id="detail-{i}"></div>
</div>""")

    body = f"""
<header class="top">
  <h1>{_esc(title)}</h1>
  <span class="badge">BACKTEST</span>
  <span class="sub">{_esc(first["symbol"])} · {_esc(first["timeframe"])} · {period}
   · fees {first["fee_bps"]:.0f} bps · slippage {first["slippage_bps"]:.0f} bps
   · start ${first["start_cash"]:,.0f}</span>
</header>
<div class="disclaimer"><strong>Read this first.</strong> These are historical
simulations, not forecasts. They include fees and slippage but not taxes,
outages, or your own behavior. A strategy that beat the market in this window
can lose money in the next one. Never deploy capital you cannot afford to
lose.</div>
<div class="card">
  <h2>Growth of 100 (all strategies vs buy &amp; hold)</h2>
  <div id="cmp-chart"></div>
</div>
<div class="card">
  <h2>Metrics</h2>
  <div class="scroll"><table>
    <thead><tr>{header_cols}</tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table></div>
  <p class="note" style="margin-top:6px">Sharpe/Sortino annualized (rf = 0,
  365-day year). Win rate = sell fills with positive net realized PnL.
  Exposure = share of candles holding a position.</p>
</div>
{''.join(details)}
<footer>Generated by Autopilot · data: public exchange APIs · this document is
self-contained and offline-safe.</footer>
"""
    script = f"window.__DATA__ = {safe_json(json.dumps(data))};\n" + REPORT_SCRIPT
    return html_page(title, body, script)


def write_report(results: list[dict], out_path: str,
                 title: str = "Autopilot backtest report") -> str:
    html = render_report(results, title=title)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
