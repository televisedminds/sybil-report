# Quickstart — from zero to a running bot (no experience needed)

This guide assumes you've never used Python or a terminal. Follow it top to
bottom. At the end you'll have a bot trading a **pretend** $10,000 account
against **real live prices**, with a dashboard in your browser. No exchange
account, no API keys, no real money — that comes much later, if ever, via
[GO-LIVE.md](GO-LIVE.md).

---

## Step 1 — Install Python (one time)

Autopilot needs Python **3.11 or newer** and nothing else.

**Windows**
1. Go to <https://www.python.org/downloads/> and download the latest Python 3.
2. Run the installer. **Tick the checkbox "Add python.exe to PATH"** on the
   first screen (this matters), then Install.
3. Open a terminal: press `Win`, type `powershell`, Enter.
4. Check it worked: `py --version` → should print `Python 3.1x.x`.
5. Everywhere this guide says `python3`, type `py` instead.

**macOS**
1. Open Terminal (Cmd+Space, type "Terminal").
2. `python3 --version` — if it says 3.11+, you're done.
3. If not: install from <https://www.python.org/downloads/> (or
   `brew install python` if you use Homebrew).

**Linux (Debian/Ubuntu)**
```bash
sudo apt update && sudo apt install -y python3 git
python3 --version   # needs 3.11+
```

## Step 2 — Get the code

**With git** (Windows: install from <https://git-scm.com> first, or use the ZIP
option below):

```bash
git clone -b claude/passive-income-automation-1eukga https://github.com/televisedminds/sybil-report.git autopilot
cd autopilot
```

*(The `-b ...` part selects the branch the platform lives on. If you've merged
it into `main`, a plain `git clone` works.)*

**Without git:** on the GitHub page, switch the branch dropdown to
`claude/passive-income-automation-1eukga`, then Code → Download ZIP, unzip it,
and open a terminal in that folder (Windows: shift+right-click in the folder →
"Open PowerShell window here").

## Step 3 — Prove it works (offline, 10 seconds)

```bash
python3 -m autopilot demo
```

You should see a table of four strategies backtested on 10 years of real
Bitcoin data, and a file `reports/demo-report.html` — double-click it to open
a full visual report in your browser. If this works, everything works.

## Step 4 — Create your bot

```bash
python3 -m autopilot init
```

It asks five questions; pressing **Enter accepts the default** shown in
brackets. Defaults give you: BTC-USD, the `sma_cross` trend-following
strategy on daily candles, $10,000 pretend cash. It writes a config file and
prints the exact command to start the bot. (Later you can rerun `init` with
different answers to create more bots.)

## Step 5 — Start it

```bash
python3 -m autopilot paper --config configs/sma_cross-btc-usd-paper.json
```
*(use whatever filename `init` printed)*

Then open **<http://127.0.0.1:8899>** in your browser. You'll see equity
tiles, an equity chart, trades, and an events log.

**What to expect in the first minutes:** a `bootstrap` event (history
loaded), then a heartbeat every hour. **"No trades yet" is normal and
correct** — strategies act when their rules trigger, not when you're
watching. On daily candles, `sma_cross` might not trade for days or weeks
(it's waiting for a trend signal); the `dca` strategy on 1-hour candles
makes its first buy within a day. The bot decides once per candle, so a
quiet log means "no signal", not "broken".

**Stop it** any time with `Ctrl-C`. Progress is saved in `state/…​.db`;
running the same command later resumes exactly where it stopped (it will
deliberately skip signals it missed while off, rather than trade stale ones).

## Step 6 — Keep it running 24/7

The bot only trades while the program is running. Three options, easiest
first:

**A. Your own computer** — leave the terminal window open and stop the
machine from sleeping (Windows: Settings → Power → Sleep: Never; macOS:
System Settings → Displays → Advanced, or run the bot under
`caffeinate -i python3 -m autopilot paper ...`). Fine for paper trading;
downtime just means skipped candles, never corrupted state.

**B. tmux on Mac/Linux** — survives closing the terminal window:
```bash
tmux new -s bot
python3 -m autopilot paper --config configs/your-config.json
# detach: press Ctrl-B then D   ·   reattach later: tmux attach -t bot
```

**C. A $5/month VPS (the proper way)** — any tiny cloud Linux box
(Hetzner/DigitalOcean/Lightsail). Do steps 1–4 on the box, then make it a
service that starts on boot and restarts on crash:

```bash
sudo tee /etc/systemd/system/autopilot.service > /dev/null <<'EOF'
[Unit]
Description=Autopilot paper session
After=network-online.target

[Service]
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/autopilot
ExecStart=/usr/bin/python3 -m autopilot paper --config configs/YOUR_CONFIG.json
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now autopilot
systemctl status autopilot          # should say "active (running)"
```

To see the dashboard of a bot running on a VPS from your own computer:
```bash
ssh -L 8899:127.0.0.1:8899 YOUR_USERNAME@YOUR_SERVER_IP
```
then open <http://127.0.0.1:8899> locally. (The dashboard deliberately only
listens on the machine it runs on — don't expose it to the internet.)

## Step 7 — Your routine while it runs

- **Glance at the dashboard**, or from a terminal:
  `python3 -m autopilot status --state state/YOUR_STATE.db`
- **Weekly:** `python3 -m autopilot report --state state/YOUR_STATE.db --out weekly.html`
  and compare against a backtest of the same weeks.
- **Events worth reading:** `risk_block` (an order was capped — usually fine),
  `daily_loss_halt` (down ≥5% today; bot pauses buying until tomorrow, by
  design), `kill_switch` (down ≥30% from peak; bot sold everything and
  stopped). After a kill switch, figure out *why* before re-arming with
  `python3 -m autopilot resume --state state/YOUR_STATE.db` and restarting.
- **Phone alerts (optional):** in Discord: Server Settings → Integrations →
  Webhooks → New Webhook → Copy URL, then put that URL in your config's
  `"notify": {"webhook_url": "..."}` and restart the bot. Fills and risk
  events now ping your phone.

## Managing bots

| I want to… | Do this |
|---|---|
| Stop the bot | `Ctrl-C` in its terminal (or `systemctl stop autopilot`) |
| Resume it | run the same `paper` command again |
| Start the session over from $10k | stop it, delete its `state/…​.db` file, start it |
| Change strategy settings | edit the config JSON, save, restart the bot |
| Run a second bot (other coin/strategy) | `python3 -m autopilot init` again → new config with its own state file and port, run it in a second terminal |
| Try ideas against history first | `python3 -m autopilot backtest --csv sample_data/BTC-USD-1d.csv --strategy grid --params '{"span_pct": 15}'` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python3: command not found` | Windows: use `py`. macOS/Linux: install Python 3.11+ (Step 1) |
| `No module named autopilot` | You're not in the project folder — `cd` into it first |
| Dashboard page won't load | Bot not running, or different port — check the startup line it printed |
| `dashboard disabled (…address in use)` | Another bot uses that port; set a different `"port"` in the config |
| `error: only 0 candles available…` | Symbol/timeframe combo has no data — try `BTC-USD`/`ETH-USD` with `1h` or `1d` |
| Windows firewall pops up | Allow it — the dashboard is a local-only web page |
| `risk: HALTED for the day` | Working as designed (daily loss limit). It resumes at midnight UTC |
| `risk: KILLED (…)` | The max-drawdown brake fired. Read Step 7, then `resume` deliberately |
| Bot was off for a while | Fine. It resumes and logs `catchup_skip` instead of trading stale signals |

## Set your expectations (the honest part)

Paper mode exists because **most strategy/market combinations lose money in
some regimes** — see the real numbers in [RESEARCH.md](RESEARCH.md). Run
paper for at least 2–4 weeks. Expect quiet days, losing weeks, and drawdowns;
that's what the risk limits are for. If, after weeks of paper results you
understand and trust, you consider real money: read [RISKS.md](RISKS.md) and
[GO-LIVE.md](GO-LIVE.md) first, start with an amount whose total loss you can
shrug off, and know that no backtest — including ours — promises the future.
