"""Autopilot command line.

    autopilot demo                          # offline: backtest bundled data, write report
    autopilot fetch --symbol BTC-USD ...    # download history to CSV
    autopilot backtest --config cfg.json    # simulate strategies, print/report metrics
    autopilot paper --config cfg.json       # trade fake money on live prices (24/7)
    autopilot live --config cfg.json        # REAL MONEY (gated by interlocks)
    autopilot dashboard --state db          # view any session in the browser
    autopilot status --state db             # one-line session summary
    autopilot resume --state db             # re-arm after a kill switch
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading

from autopilot import __version__
from autopilot.config import Config, ConfigError
from autopilot.data.candles import candles_to_csv, fmt_ts, parse_date_ms
from autopilot.data.sources import DataSourceError, make_source
from autopilot.engine.backtest import Backtester
from autopilot.engine.metrics import compute_metrics
from autopilot.engine.portfolio import Fill
from autopilot.execution.broker import BrokerError
from autopilot.execution.paper import PaperBroker
from autopilot.execution.risk import RiskEngine
from autopilot.runner.loop import TradingLoop
from autopilot.runner.notify import Notifier
from autopilot.runner.state import StateStore
from autopilot.server.report import write_report
from autopilot.strategies import REGISTRY, StrategyError, make_strategy

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "sample_data")


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _metrics_table(rows: list[tuple[str, dict]]) -> str:
    cols = [("strategy", 22), ("return%", 9), ("cagr%", 8), ("sharpe", 7),
            ("maxDD%", 8), ("expo%", 7), ("fills", 6), ("win%", 6),
            ("fees$", 9), ("final$", 12)]
    out = ["  ".join(name.rjust(w) if i else name.ljust(w)
                     for i, (name, w) in enumerate(cols))]
    out.append("  ".join("-" * w for _, w in cols))
    for label, m in rows:
        vals = [label[:22].ljust(22),
                f"{m['total_return_pct']:.1f}".rjust(9),
                f"{m['cagr_pct']:.1f}".rjust(8),
                f"{m['sharpe']:.2f}".rjust(7),
                f"{m['max_drawdown_pct']:.1f}".rjust(8),
                f"{m['exposure_pct']:.0f}".rjust(7),
                f"{m['n_fills']}".rjust(6),
                f"{m['win_rate_pct']:.0f}".rjust(6),
                f"{m['fees_paid']:.0f}".rjust(9),
                f"{m['final_equity']:,.0f}".rjust(12)]
        out.append("  ".join(vals))
    return "\n".join(out)


def _load_backtest_candles(cfg: Config):
    source = make_source(cfg.source, cfg.timeframe, cfg.csv_path)
    start_ms = parse_date_ms(cfg.backtest_start) if cfg.backtest_start else None
    end_ms = parse_date_ms(cfg.backtest_end) if cfg.backtest_end else None
    candles = source.fetch(cfg.symbol, cfg.timeframe, start_ms=start_ms, end_ms=end_ms)
    if len(candles) < 10:
        raise DataSourceError(
            f"only {len(candles)} candles available for {cfg.symbol} {cfg.timeframe} "
            "— widen the window or change source")
    return candles


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_fetch(args) -> int:
    source = make_source(args.source, args.timeframe)
    start_ms = parse_date_ms(args.start) if args.start else None
    end_ms = parse_date_ms(args.end) if args.end else None
    candles = source.fetch(args.symbol.upper(), args.timeframe,
                           start_ms=start_ms, end_ms=end_ms)
    if not candles:
        return _err("no candles returned")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(candles_to_csv(candles))
    print(f"wrote {len(candles)} candles ({fmt_ts(candles[0].ts)} → "
          f"{fmt_ts(candles[-1].ts)} UTC) to {args.out}")
    return 0


def cmd_backtest(args) -> int:
    cfg = Config.load(args.config) if args.config else Config.from_dict({
        "mode": "backtest",
        "symbol": args.symbol, "timeframe": args.timeframe, "source": args.source,
        "csv_path": args.csv, "start_cash": args.cash,
        "strategy": {"name": args.strategy, "params": json.loads(args.params)},
        "backtest": {"start": args.start, "end": args.end},
    })
    if args.csv:
        cfg.source, cfg.csv_path = "csv", args.csv
    candles = _load_backtest_candles(cfg)
    names = ([s.strip() for s in args.strategies.split(",") if s.strip()]
             if args.strategies else [cfg.strategy_name])

    results = []
    for name in names:
        params = cfg.strategy_params if name == cfg.strategy_name else {}
        strat = make_strategy(name, params)
        res = Backtester(candles, strat, symbol=cfg.symbol, timeframe=cfg.timeframe,
                         start_cash=cfg.start_cash, fee_bps=cfg.fee_bps,
                         slippage_bps=cfg.slippage_bps).run()
        results.append(res)

    print(f"\n{cfg.symbol} {cfg.timeframe} · {len(candles)} candles "
          f"({fmt_ts(candles[0].ts)} → {fmt_ts(candles[-1].ts)} UTC) · "
          f"fees {cfg.fee_bps}bps · slippage {cfg.slippage_bps}bps\n")
    print(_metrics_table([(r.strategy, r.metrics.to_dict()) for r in results]))
    bench = results[0].metrics
    print(f"\nbuy & hold benchmark: {bench.benchmark_return_pct:+.1f}% "
          f"(max drawdown {bench.benchmark_max_drawdown_pct:.1f}%)")
    print("reminder: backtests are hypotheses about the past, not promises about the future.")

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)) or ".", exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in results], f)
        print(f"json → {args.json}")
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        write_report([r.to_dict() for r in results], args.report,
                     title=f"Autopilot backtest — {cfg.symbol} {cfg.timeframe}")
        print(f"report → {args.report}")
    return 0


def cmd_demo(args) -> int:
    csv = os.path.join(SAMPLE_DIR, "BTC-USD-1d.csv")
    if not os.path.exists(csv):
        return _err(f"bundled sample data missing at {csv}; run scripts/refresh_sample_data.sh")
    ns = argparse.Namespace(
        config=None, symbol="BTC-USD", timeframe="1d", source="csv", csv=csv,
        cash=10_000.0, strategy="dca", params="{}", start=None, end=None,
        strategies="dca,sma_cross,rsi_revert,grid",
        json=None, report=args.report or "reports/demo-report.html")
    return cmd_backtest(ns)


def _build_session(cfg: Config):
    store = StateStore(cfg.state_db)
    source = make_source(cfg.source, cfg.timeframe, cfg.csv_path)
    strategy = make_strategy(cfg.strategy_name, cfg.strategy_params)
    risk = RiskEngine(cfg.risk, state=store.kv_get("risk_state"))
    notifier = Notifier(cfg.webhook_url, store=store)
    return store, source, strategy, risk, notifier


def _run_loop(cfg: Config, broker, store, source, strategy, risk, notifier,
              iterations: int | None) -> int:
    loop = TradingLoop(cfg, store, source, strategy, broker, risk, notifier)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, lambda *_: loop.stop())
        signal.signal(signal.SIGTERM, lambda *_: loop.stop())

    dash = None
    if cfg.dashboard_enabled:
        from autopilot.server.dashboard import DashboardServer
        try:
            dash = DashboardServer(cfg.state_db, cfg.dashboard_host, cfg.dashboard_port)
            dash.start()
            print(f"dashboard: {dash.url}")
        except OSError as e:
            print(f"dashboard disabled ({e})", file=sys.stderr)

    print(f"{cfg.mode} session: {cfg.symbol} {cfg.timeframe} "
          f"{strategy.describe()} · state: {cfg.state_db}")
    print("Ctrl-C to stop; state persists and the session resumes where it left off.")
    try:
        reason = loop.run(max_iterations=iterations)
    finally:
        if dash:
            dash.stop()
    summary = store.kv_get("summary", {})
    print(f"\nloop exited: {reason}")
    if summary:
        print(f"equity {summary.get('equity')} · cash {summary.get('cash')} · "
              f"qty {summary.get('qty')} · risk: {summary.get('risk')}")
    return 0 if reason != "kill_switch" else 1


def cmd_paper(args) -> int:
    cfg = Config.load(args.config)
    if cfg.mode not in ("paper", "backtest"):
        return _err("config mode must be 'paper' for `autopilot paper`")
    cfg.mode = "paper"
    store, source, strategy, risk, notifier = _build_session(cfg)
    broker = PaperBroker(store, cfg.start_cash, cfg.fee_bps, cfg.slippage_bps)
    return _run_loop(cfg, broker, store, source, strategy, risk, notifier,
                     args.iterations)


def cmd_live(args) -> int:
    cfg = Config.load(args.config)
    if cfg.mode != "live":
        return _err("config mode must be 'live' for `autopilot live`")
    from autopilot.execution.live_ccxt import LiveBroker, assert_live_interlocks
    assert_live_interlocks(cfg)
    print("=" * 70)
    print("LIVE TRADING — REAL MONEY. The bot will place real orders on "
          f"{cfg.live_exchange} up to a hard cap of {cfg.live_capital_cap:,.2f}.")
    print("Kill it any time with Ctrl-C; `autopilot status` shows the state.")
    print("=" * 70)
    store, source, strategy, risk, notifier = _build_session(cfg)
    broker = LiveBroker(cfg, store)
    return _run_loop(cfg, broker, store, source, strategy, risk, notifier,
                     args.iterations)


def cmd_dashboard(args) -> int:
    from autopilot.server.dashboard import DashboardServer
    if not os.path.exists(args.state):
        return _err(f"state db not found: {args.state}")
    dash = DashboardServer(args.state, args.host, args.port)
    print(f"dashboard: {dash.url}  (Ctrl-C to stop)")
    try:
        dash.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        dash.httpd.server_close()
    return 0


def cmd_status(args) -> int:
    if not os.path.exists(args.state):
        return _err(f"state db not found: {args.state}")
    store = StateStore(args.state)
    summary = store.kv_get("summary")
    if not summary:
        print("no summary yet (session has not completed a step)")
        return 0
    for k in ("mode", "symbol", "timeframe", "strategy", "equity", "cash", "qty",
              "avg_cost", "price", "realized_pnl", "unrealized_pnl", "fees_paid",
              "open_orders", "risk"):
        print(f"{k:>15}: {summary.get(k)}")
    print(f"{'updated':>15}: {fmt_ts(summary['updated_at'])} UTC")
    return 0


def cmd_resume(args) -> int:
    if not os.path.exists(args.state):
        return _err(f"state db not found: {args.state}")
    store = StateStore(args.state)
    from autopilot.config import RiskConfig
    risk = RiskEngine(RiskConfig(), state=store.kv_get("risk_state"))
    if not risk.killed and not risk.halted_day:
        print("risk engine is already active; nothing to resume")
        return 0
    risk.resume()
    store.kv_set("risk_state", risk.to_state())
    store.add_event("resume", "human re-armed the risk engine", level="warn")
    print("risk engine re-armed. Restart the paper/live session to continue trading.")
    return 0


def cmd_report(args) -> int:
    if not os.path.exists(args.state):
        return _err(f"state db not found: {args.state}")
    store = StateStore(args.state)
    rows = store.load_equity_full()
    if len(rows) < 2:
        return _err("not enough equity history in this session yet")
    summary = store.kv_get("summary", {}) or {}
    fills = store.load_fills()
    tf = summary.get("timeframe", "1h")
    start_cash = float(summary.get("start_cash") or rows[0][1])
    closes = [[r[0], r[4]] for r in rows]
    metrics = compute_metrics([(r[0], r[1]) for r in rows], fills, tf, start_cash,
                              [r[4] for r in rows],
                              [r[3] > 0 for r in rows])
    result = {
        "symbol": summary.get("symbol", "?"), "timeframe": tf,
        "strategy": summary.get("strategy", "session"),
        "params": {}, "start_cash": start_cash,
        "fee_bps": 0.0, "slippage_bps": 0.0, "metrics": metrics.to_dict(),
        "equity_curve": [[r[0], r[1]] for r in rows],
        "closes": closes,
        "fills": [{"ts": f.ts, "side": f.side, "qty": f.qty, "price": f.price,
                   "fee": f.fee, "tag": f.tag, "realized_pnl": f.realized_pnl}
                  for f in fills],
    }
    out = args.out or "reports/session-report.html"
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    write_report([result], out,
                 title=f"Autopilot session — {result['symbol']} ({summary.get('mode', '?')})")
    print(f"report → {out}")
    return 0


# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autopilot",
        description="Self-hosted systematic trading platform. Paper first; "
                    "live only behind explicit interlocks.")
    p.add_argument("--version", action="version", version=f"autopilot {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="download candle history to CSV")
    f.add_argument("--symbol", required=True)
    f.add_argument("--timeframe", default="1d")
    f.add_argument("--source", default="auto")
    f.add_argument("--start")
    f.add_argument("--end")
    f.add_argument("--out", required=True)
    f.set_defaults(fn=cmd_fetch)

    b = sub.add_parser("backtest", help="simulate strategies on history")
    b.add_argument("--config")
    b.add_argument("--symbol", default="BTC-USD")
    b.add_argument("--timeframe", default="1d")
    b.add_argument("--source", default="auto")
    b.add_argument("--csv", help="use a CSV file as the data source")
    b.add_argument("--cash", type=float, default=10_000.0)
    b.add_argument("--strategy", default="dca",
                   help=f"one of: {', '.join(sorted(REGISTRY))}")
    b.add_argument("--params", default="{}", help="strategy params as JSON")
    b.add_argument("--strategies", help="comma list to compare (default params)")
    b.add_argument("--start")
    b.add_argument("--end")
    b.add_argument("--json", help="write results JSON here")
    b.add_argument("--report", help="write self-contained HTML report here")
    b.set_defaults(fn=cmd_backtest)

    d = sub.add_parser("demo", help="offline demo: bundled data, all strategies, report")
    d.add_argument("--report")
    d.set_defaults(fn=cmd_demo)

    pa = sub.add_parser("paper", help="paper-trade live prices, 24/7, no keys needed")
    pa.add_argument("--config", required=True)
    pa.add_argument("--iterations", type=int, help=argparse.SUPPRESS)
    pa.set_defaults(fn=cmd_paper)

    li = sub.add_parser("live", help="REAL-MONEY trading (read docs/GO-LIVE.md first)")
    li.add_argument("--config", required=True)
    li.add_argument("--iterations", type=int, help=argparse.SUPPRESS)
    li.set_defaults(fn=cmd_live)

    da = sub.add_parser("dashboard", help="serve the web dashboard for a session db")
    da.add_argument("--state", required=True)
    da.add_argument("--host", default="127.0.0.1")
    da.add_argument("--port", type=int, default=8899)
    da.set_defaults(fn=cmd_dashboard)

    st = sub.add_parser("status", help="print a session summary")
    st.add_argument("--state", required=True)
    st.set_defaults(fn=cmd_status)

    re = sub.add_parser("resume", help="re-arm the risk engine after a kill switch")
    re.add_argument("--state", required=True)
    re.set_defaults(fn=cmd_resume)

    rp = sub.add_parser("report", help="write an HTML report for a paper/live session")
    rp.add_argument("--state", required=True)
    rp.add_argument("--out")
    rp.set_defaults(fn=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ConfigError, DataSourceError, StrategyError, BrokerError) as e:
        return _err(str(e))
    except json.JSONDecodeError as e:
        return _err(f"bad JSON: {e}")
    except OSError as e:
        return _err(f"file error: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
