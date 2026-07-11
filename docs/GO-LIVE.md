# Go-live checklist — from paper to real money

Live mode is intentionally annoying to enable. Every step below exists
because skipping it has cost someone real money.

## 0. Decide if you should
- [ ] You have read [RISKS.md](RISKS.md) and nothing in it surprised you.
- [ ] The money you'll allocate could go to zero without changing your life.
- [ ] You ran the exact config in **paper mode for 2–4+ weeks** and compared
      it to a backtest over the same dates (`autopilot report`). You
      understand every divergence.

## 1. Exchange account
- [ ] Choose a ccxt-supported venue with local legality and decent fees
      (the default config assumes Kraken; any ccxt id works: `binance`,
      `coinbase`, `bybit`, ...).
- [ ] Complete KYC; enable 2FA on the account.
- [ ] Deposit only your working capital (= your intended `capital_cap`, plus
      fee headroom).

## 2. API key (the part people get wrong)
- [ ] Create a key with **trade + read balance permissions only**.
- [ ] **Withdrawals: OFF.** Non-negotiable.
- [ ] IP-allowlist the key to the machine that runs the bot, if the venue
      supports it.
- [ ] Store the key only in environment variables:

```bash
export AUTOPILOT_API_KEY="..."
export AUTOPILOT_API_SECRET="..."
```

## 3. Config
- [ ] Copy `configs/live-template.json`; set `symbol`, `strategy` — the SAME
      ones you paper-traded — and `live.exchange`.
- [ ] Set `live.capital_cap` to your real number. The bot's cash mirror is
      seeded with `min(exchange balance, capital_cap)` and can never spend
      beyond it.
- [ ] Set risk limits you actually mean. Defaults: 5% daily-loss halt, 25%
      drawdown kill switch.
- [ ] Optional but recommended: a Discord/Slack webhook in `notify` so fills
      and kill-switch events reach your phone.

## 4. Software
- [ ] `pip install ccxt` (the only dependency, and only for live).
- [ ] `python3 -m unittest discover -s tests` passes on the machine that will
      run the bot.
- [ ] The machine stays on 24/7 (a $5 VPS is fine; the bot is a single
      process + SQLite file). Use systemd/supervisor to restart on reboot:

```ini
# /etc/systemd/system/autopilot.service
[Unit]
Description=Autopilot live session
After=network-online.target
[Service]
WorkingDirectory=/opt/autopilot
Environment=AUTOPILOT_API_KEY=...
Environment=AUTOPILOT_API_SECRET=...
Environment=AUTOPILOT_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY-CAN-BE-LOST
ExecStart=/usr/bin/python3 -m autopilot live --config configs/my-live.json
Restart=on-failure
RestartSec=30
[Install]
WantedBy=multi-user.target
```

## 5. Preflight, arm and launch
- [ ] `export AUTOPILOT_LIVE_CONFIRM=I-UNDERSTAND-REAL-MONEY-CAN-BE-LOST`
      (typing that sentence is the point).
- [ ] `python3 -m autopilot live-check --config configs/my-live.json` —
      a read-only preflight that verifies the config, interlocks, ccxt, the
      exchange connection, your API key, the symbol listing, your balance vs
      the cap, and market data **without placing any order**. Repeat until
      every line is ✅. (`autopilot live` runs the same preflight and refuses
      to start if anything fails.)
- [ ] `python3 -m autopilot live --config configs/my-live.json`
- [ ] Confirm the startup banner shows the right venue and cap; confirm the
      dashboard loads; confirm the first `heartbeat` event.

## 6. Operate
- [ ] Check the dashboard/status daily for the first two weeks.
- [ ] If the kill switch fires: **investigate before `autopilot resume`.**
      It fired because your configured worst case happened.
- [ ] Sweep profits (and export the `fills` table for taxes) on a schedule —
      withdrawals are manual by design.
- [ ] Re-backtest quarterly with fresh data (`autopilot fetch` + `backtest`);
      retire the strategy when its live results diverge badly from its
      paper/backtest envelope.

## Aborting
`Ctrl-C` (or `systemctl stop autopilot`) stops trading; open positions
REMAIN OPEN on the exchange. To go fully flat: stop the bot, then sell the
position manually on the exchange UI, or restart in paper... there is no
"close everything" button here on purpose — that's a human decision.
