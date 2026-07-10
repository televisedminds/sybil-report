---
name: verify
description: Verify Autopilot platform changes by driving the real CLI surfaces — offline demo, live-data paper session, dashboard HTTP, report rendering. Use after changing anything under autopilot/.
---

# Verifying Autopilot changes

Zero-dependency Python 3.11+ project; nothing to build or install.

## Surfaces and the commands that drive them

1. **Offline end-to-end (always start here, needs no network):**
   ```bash
   python3 -m autopilot demo          # backtests bundled real data, writes reports/demo-report.html
   ```
   Expect a 4-row metrics table + benchmark line + report path.

2. **Live-data paper loop (needs outbound HTTPS to coinbase/kraken):**
   ```bash
   # 1m timeframe + every=1 DCA gives observable fills within ~2 minutes
   python3 -m autopilot paper --config <cfg.json> --iterations 30
   python3 -m autopilot status --state <state.db>
   ```
   Use a scratch config: `timeframe 1m`, `poll_seconds 4`,
   `strategy dca {every:1, trend_sma:0}`, `dashboard.enabled false`.
   Expect: fills appear, equity ≈ start minus fees, `risk: active`.

3. **Dashboard:** `python3 -m autopilot dashboard --state <db> --port 0`-style
   (pick a free port), then `curl /api/summary /api/equity /api/trades /api/events`
   and screenshot `/` with:
   ```bash
   /opt/pw-browsers/chromium --headless --disable-gpu --no-sandbox \
     --window-size=1200,1100 --screenshot=out.png http://127.0.0.1:<port>/
   ```

4. **Reports (charts):** regenerate with `--report out.html`, screenshot the
   file:// URL. For dark mode, inject
   `<script>document.documentElement.setAttribute('data-theme','dark')</script>`
   after `<body>` in a copy and screenshot that.

## Probes that have caught real bugs

- `python3 -m autopilot live --config configs/live-template.json` with NO env
  vars set → must fail listing the missing interlocks (this once caught the
  template itself being unparseable).
- Typo'd `--strategy`, typo'd config keys, `--start 2030-01-01` (empty
  window), missing `--state` paths → all must produce one-line `error: ...`
  with exit 2, never a traceback.
- SIGINT a running paper session → `loop exited: stopped`, exit 0, and a
  restart resumes from the same state db without double-processing (fill
  timestamps stay unique).

## Gotchas

- `reports/` and `state/` are gitignored runtime artifacts.
- Binance is geo-blocked (451) here; coinbase→kraken fallback is the tested path.
- The unit suite (`python3 -m unittest discover -s tests`) is CI's job — run
  the surfaces above instead when verifying.
