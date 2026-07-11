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

STRATEGY_MENU = [
    ("sma_cross", "trend following: hold while the 50d average is above the 200d, "
                  "otherwise sit in cash (recommended first strategy)"),
    ("dca", "accumulation: buy a fixed amount on a schedule, only while the "
            "market is above its 200-period average"),
    ("rsi_revert", "dip buying: buy panic dips in uptrends, sell the bounce"),
    ("grid", "range harvesting: ladder of buy-low/sell-high orders; earns in "
             "sideways chop, LOSES in strong trends"),
]

DEFAULT_TF = {"sma_cross": "1d", "dca": "1h", "rsi_revert": "1d", "grid": "1h"}


def _suggest_params(strategy: str, timeframe: str, cash: float) -> dict:
    if strategy == "dca":
        per_buy = max(10.0, round(cash / 100))
        return {"every": 24 if timeframe in ("1m", "5m", "15m", "1h") else 7,
                "quote_per_buy": per_buy, "trend_sma": 200,
                "sell_on_trend_break": False}
    if strategy == "sma_cross":
        return {"fast": 50, "slow": 200, "target_frac": 0.95}
    if strategy == "rsi_revert":
        return {"period": 14, "buy_below": 30.0, "sell_above": 55.0,
                "target_frac": 0.5, "trend_sma": 200}
    if strategy == "grid":
        return {"levels_per_side": 6, "span_pct": 20.0,
                "quote_per_level": max(10.0, round(cash / 12)),
                "recenter_mult": 1.5}
    return {}


def _ask(prompt: str, default: str, assume_yes: bool, validate=None) -> str:
    if assume_yes:
        return default
    while True:
        try:
            raw = input(f"{prompt} [{default}]: ").strip()
        except EOFError:
            return default
        value = raw or default
        if validate is None:
            return value
        try:
            validate(value)
            return value
        except Exception as e:
            print(f"  -> {e}")


def cmd_init(args) -> int:
    yes = args.yes
    if not yes:
        print("Autopilot setup — press Enter to accept the [default].\n")

    symbol = _ask("Market to trade (BTC-USD, ETH-USD, SOL-USD, ...)",
                  (args.symbol or "BTC-USD"), yes).upper().replace("/", "-")
    if "-" not in symbol:
        return _err(f"symbol must look like 'BTC-USD', got {symbol!r}")

    strategy = args.strategy
    if not strategy and not yes:
        print("\nStrategies:")
        for i, (name, blurb) in enumerate(STRATEGY_MENU, 1):
            print(f"  {i}) {name:<11}— {blurb}")
        names = [n for n, _ in STRATEGY_MENU]

        def _valid_strat(v):
            if v.isdigit() and 1 <= int(v) <= len(names):
                return
            if v in names:
                return
            raise ValueError(f"pick 1-{len(names)} or one of: {', '.join(names)}")
        picked = _ask("Strategy", "1", False, _valid_strat)
        strategy = names[int(picked) - 1] if picked.isdigit() else picked
    strategy = strategy or "sma_cross"
    if strategy not in REGISTRY:
        return _err(f"unknown strategy {strategy!r}; available: {', '.join(sorted(REGISTRY))}")

    def _valid_tf(v):
        from autopilot.data.candles import tf_seconds
        tf_seconds(v)
    timeframe = _ask("Candle timeframe", args.timeframe or DEFAULT_TF[strategy],
                     yes, _valid_tf)

    def _valid_cash(v):
        if float(v) <= 0:
            raise ValueError("must be a positive number")
    cash = float(_ask("Pretend starting cash (paper money, $)",
                      str(args.cash), yes, _valid_cash))

    def _valid_port(v):
        p = int(v)
        if not (1 <= p <= 65535):
            raise ValueError("must be a port number 1-65535")
    port = int(_ask("Dashboard port", str(args.port), yes, _valid_port))

    webhook = args.webhook if args.webhook is not None else _ask(
        "Discord/Slack webhook URL for alerts (Enter to skip)", "", yes)

    out = args.out or f"configs/{strategy}-{symbol.lower()}-paper.json"
    if os.path.exists(out) and not args.force:
        return _err(f"{out} already exists (use --force to overwrite, "
                    "or --out for a different name)")

    stem = os.path.splitext(os.path.basename(out))[0]
    raw = {
        "_generated_by": "autopilot init — safe to edit by hand",
        "mode": "paper",
        "symbol": symbol,
        "timeframe": timeframe,
        "source": "auto",
        "start_cash": cash,
        "strategy": {"name": strategy,
                     "params": _suggest_params(strategy, timeframe, cash)},
        "risk": {"max_position_pct": 95, "max_order_pct": 25,
                 "daily_loss_limit_pct": 5, "max_drawdown_pct": 30,
                 "max_orders_per_day": 60},
        "paper": {"poll_seconds": 60, "state_db": f"state/{stem}.db"},
        "dashboard": {"enabled": True, "host": "127.0.0.1", "port": port},
        "notify": {"webhook_url": webhook or None},
    }
    Config.from_dict(json.loads(json.dumps(raw)))  # validate before writing

    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
        f.write("\n")

    print(f"\nwrote {out}")
    print(f"  market    : {symbol} ({timeframe} candles)")
    print(f"  strategy  : {strategy} {json.dumps(raw['strategy']['params'])}")
    print(f"  paper cash: ${cash:,.0f} (no real money involved)")
    print(f"  dashboard : http://127.0.0.1:{port}")
    print(f"  state file: state/{stem}.db (delete it to start the session over)")
    print("\nStart it with:\n")
    print(f"  python3 -m autopilot paper --config {out}\n")
    print("Stop any time with Ctrl-C — progress is saved and the same command resumes.")
    return 0


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


def _print_preflight(checks) -> bool:
    print("\nLive preflight (read-only, places no orders):")
    for c in checks:
        line = f"  {c.icon} {c.name}"
        if c.detail:
            line += f"  — {c.detail}"
        print(line)
    failures = [c for c in checks if c.ok is False]
    skipped = [c for c in checks if c.ok is None]
    if failures:
        print(f"\n{len(failures)} check(s) FAILED — fix them and rerun "
              "`autopilot live-check`.")
    elif skipped:
        print("\nno failures, but some checks were skipped.")
    else:
        print("\nall checks passed.")
    return not failures


def cmd_live_check(args) -> int:
    cfg = Config.load(args.config)
    from autopilot.execution.live_ccxt import run_live_preflight
    return 0 if _print_preflight(run_live_preflight(cfg)) else 1


def cmd_live(args) -> int:
    cfg = Config.load(args.config)
    if cfg.mode != "live":
        return _err("config mode must be 'live' for `autopilot live`")
    from autopilot.execution.live_ccxt import (LiveBroker, assert_live_interlocks,
                                               run_live_preflight)
    if not _print_preflight(run_live_preflight(cfg)):
        return _err("live preflight failed — nothing was traded")
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

    ini = sub.add_parser("init", help="interactive setup: creates a paper-trading config")
    ini.add_argument("--symbol")
    ini.add_argument("--strategy", help=f"one of: {', '.join(sorted(REGISTRY))}")
    ini.add_argument("--timeframe")
    ini.add_argument("--cash", type=float, default=10_000.0)
    ini.add_argument("--port", type=int, default=8899)
    ini.add_argument("--webhook")
    ini.add_argument("--out")
    ini.add_argument("--yes", action="store_true",
                     help="accept all defaults, no prompts")
    ini.add_argument("--force", action="store_true",
                     help="overwrite an existing config file")
    ini.set_defaults(fn=cmd_init)

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

    lc = sub.add_parser("live-check",
                        help="verify a live setup end-to-end WITHOUT trading")
    lc.add_argument("--config", required=True)
    lc.set_defaults(fn=cmd_live_check)

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
