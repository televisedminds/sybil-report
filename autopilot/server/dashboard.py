"""Read-only local web dashboard for a running (or finished) session.

Serves the session's SQLite state over plain stdlib HTTP. Binds to
127.0.0.1 by default — expose it beyond localhost only behind your own
reverse proxy/auth.
"""

from __future__ import annotations

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from autopilot.runner.state import StateStore
from autopilot.server.page import html_page, safe_json

DASH_SCRIPT = r"""
'use strict';
const REFRESH_MS = 10000;
const TOKEN = new URLSearchParams(location.search).get('token');
function apiUrl(path) {
  if (!TOKEN) return path;
  return path + (path.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN);
}
let chart = null, lastPayload = null;

function el(id) { return document.getElementById(id); }
function setText(id, txt) { el(id).textContent = txt; }

function tile(id, txt, deltaId, delta) {
  setText(id, txt);
  if (deltaId && delta != null) {
    const d = el(deltaId);
    d.textContent = (delta >= 0 ? '+' : '') + delta.toFixed(2) + '%';
    d.className = 'delta ' + (delta >= 0 ? 'up' : 'down');
  }
}

function renderSummary(s) {
  setText('h-symbol', s.symbol + ' · ' + s.timeframe);
  setText('h-strategy', s.strategy || '');
  const mode = el('h-mode');
  mode.textContent = (s.mode || 'paper').toUpperCase();
  mode.className = 'badge' + (s.mode === 'live' ? ' live' : '');
  const risk = el('h-risk');
  const st = s.risk || 'active';
  risk.textContent = (st === 'active' ? '✓ risk: active' : '⚠ risk: ' + st);
  risk.className = 'pill ' + (st === 'active' ? 'ok' : (st.startsWith('KILLED') ? 'bad' : 'warn'));
  const ret = s.start_cash ? (s.equity / s.start_cash - 1) * 100 : null;
  tile('t-equity', fmtMoney(s.equity), 't-equity-d', ret);
  tile('t-cash', fmtMoney(s.cash));
  setText('t-pos', fmtNum(s.qty, 6));
  setText('t-pos-d', s.qty > 0 ? '@ ' + fmtMoney(s.avg_cost) + ' avg' : 'flat');
  tile('t-real', fmtMoney(s.realized_pnl));
  tile('t-unreal', fmtMoney(s.unrealized_pnl));
  tile('t-fees', fmtMoney(s.fees_paid));
  setText('t-price', fmtMoney(s.price));
  setText('t-orders', String(s.open_orders || 0));
  setText('updated', 'updated ' + fmtTs(s.updated_at) + ' UTC');
}

function renderEquity(rows) {
  if (!rows.length) return;
  const ts = rows.map(r => r[0]);
  const eq = rows.map(r => r[1]);
  const px = rows.map(r => r[4]);
  const startEq = eq[0], startPx = px.find(p => p > 0) || 1;
  const bench = px.map(p => p > 0 ? startEq * p / startPx : null);
  lineChart(el('equity-chart'), {
    ts, money: true, logToggle: false, height: 280,
    series: [
      {name: 'Strategy equity', colorVar: '--series-1', wash: true, values: eq},
      {name: 'Buy & hold', colorVar: '--bench', dash: true, values: bench},
    ]});
  const tbl = el('equity-table-body');
  tbl.textContent = '';
  rows.slice(-40).reverse().forEach(r => {
    const tr = document.createElement('tr');
    [fmtTs(r[0]), fmtMoney(r[1]), fmtMoney(r[2]), fmtNum(r[3], 6), fmtMoney(r[4])]
      .forEach((v, i) => { const td = document.createElement('td');
        if (i) td.className = 'num'; td.textContent = v; tr.appendChild(td); });
    tbl.appendChild(tr);
  });
}

function renderTrades(fills) {
  const tb = el('trades-body');
  tb.textContent = '';
  fills.slice().reverse().slice(0, 30).forEach(f => {
    const tr = document.createElement('tr');
    const side = document.createElement('td');
    const wrap = document.createElement('span');
    wrap.className = 'side ' + f.side;
    const dot = document.createElement('span'); dot.className = 'dot';
    wrap.appendChild(dot);
    wrap.appendChild(document.createTextNode(f.side));
    side.appendChild(wrap); tr.appendChild(side);
    [fmtTs(f.ts), fmtNum(f.qty, 8), fmtMoney(f.price), fmtMoney(f.fee),
     f.side === 'sell' ? fmtMoney(f.realized_pnl) : '–', f.tag]
      .forEach((v, i) => { const td = document.createElement('td');
        if (i >= 1 && i <= 4) td.className = 'num';
        td.textContent = v; tr.appendChild(td); });
    tb.appendChild(tr);
  });
  setText('trades-count', fills.length + ' total');
}

function renderEvents(evts) {
  const tb = el('events-body');
  tb.textContent = '';
  evts.slice(0, 30).forEach(e => {
    const tr = document.createElement('tr');
    [fmtTs(e.ts), e.kind, e.message].forEach(v => {
      const td = document.createElement('td'); td.textContent = v; tr.appendChild(td); });
    if (e.level === 'error') tr.style.color = 'var(--critical)';
    else if (e.level === 'warn') tr.style.color = 'var(--serious)';
    tb.appendChild(tr);
  });
}

async function refresh() {
  const main = el('main');
  try {
    main.classList.add('loading');
    const [s, eq, tr, ev] = await Promise.all([
      fetch(apiUrl('/api/summary')).then(r => r.json()),
      fetch(apiUrl('/api/equity?n=1500')).then(r => r.json()),
      fetch(apiUrl('/api/trades?n=500')).then(r => r.json()),
      fetch(apiUrl('/api/events?n=50')).then(r => r.json()),
    ]);
    renderSummary(s); renderEquity(eq); renderTrades(tr); renderEvents(ev);
  } catch (e) {
    setText('updated', 'refresh failed: ' + e);
  } finally {
    main.classList.remove('loading');
  }
}
refresh();
setInterval(refresh, REFRESH_MS);
"""

DASH_BODY = """
<header class="top">
  <h1>Autopilot</h1>
  <span id="h-mode" class="badge">–</span>
  <span id="h-symbol" class="sub">–</span>
  <span id="h-strategy" class="sub">–</span>
  <span id="h-risk" class="pill ok">–</span>
</header>
<div id="main">
<div class="tiles">
  <div class="tile"><div class="lbl">Equity</div><div class="val" id="t-equity">–</div>
    <div class="delta" id="t-equity-d"></div></div>
  <div class="tile"><div class="lbl">Cash</div><div class="val" id="t-cash">–</div></div>
  <div class="tile"><div class="lbl">Position</div><div class="val" id="t-pos">–</div>
    <div class="delta" id="t-pos-d"></div></div>
  <div class="tile"><div class="lbl">Realized PnL</div><div class="val" id="t-real">–</div></div>
  <div class="tile"><div class="lbl">Unrealized PnL</div><div class="val" id="t-unreal">–</div></div>
  <div class="tile"><div class="lbl">Fees paid</div><div class="val" id="t-fees">–</div></div>
  <div class="tile"><div class="lbl">Last price</div><div class="val" id="t-price">–</div></div>
  <div class="tile"><div class="lbl">Open orders</div><div class="val" id="t-orders">–</div></div>
</div>
<div class="card">
  <h2>Equity curve</h2>
  <div id="equity-chart"></div>
  <details><summary>data table</summary>
    <div class="scroll"><table>
      <thead><tr><th>time (UTC)</th><th class="num">equity</th><th class="num">cash</th>
        <th class="num">qty</th><th class="num">price</th></tr></thead>
      <tbody id="equity-table-body"></tbody>
    </table></div>
  </details>
</div>
<div class="card">
  <h2>Trades <span class="note" id="trades-count"></span></h2>
  <div class="scroll"><table>
    <thead><tr><th>side</th><th>time (UTC)</th><th class="num">qty</th>
      <th class="num">price</th><th class="num">fee</th><th class="num">realized</th>
      <th>tag</th></tr></thead>
    <tbody id="trades-body"></tbody>
  </table></div>
</div>
<div class="card">
  <h2>Events</h2>
  <div class="scroll"><table>
    <thead><tr><th>time (UTC)</th><th>kind</th><th>message</th></tr></thead>
    <tbody id="events-body"></tbody>
  </table></div>
</div>
</div>
<footer>
  <span id="updated">–</span> · read-only view · paper results are simulations,
  live results are real — neither guarantees future returns.
</footer>
"""


class _Handler(BaseHTTPRequestHandler):
    store: StateStore  # set on the server instance

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload) -> None:
        self._send(200, json.dumps(payload).encode(), "application/json")

    def do_GET(self):  # noqa: N802 (stdlib naming)
        store: StateStore = self.server.store  # type: ignore[attr-defined]
        url = urlparse(self.path)
        q = parse_qs(url.query)
        token: str | None = getattr(self.server, "token", None)
        if token:
            supplied = q.get("token", [""])[0]
            if not hmac.compare_digest(supplied, token):
                self._send(401, b"missing or wrong token - open the dashboard as "
                                b"http://HOST:PORT/?token=YOUR_SECRET", "text/plain")
                return
        n = int(q.get("n", ["500"])[0])
        try:
            if url.path == "/":
                page = html_page("Autopilot dashboard", DASH_BODY, DASH_SCRIPT)
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif url.path == "/api/summary":
                self._json(store.kv_get("summary", {}))
            elif url.path == "/api/equity":
                self._json(store.load_equity_full(limit=min(n, 5000)))
            elif url.path == "/api/trades":
                self._json([
                    {"ts": f.ts, "side": f.side, "qty": f.qty, "price": f.price,
                     "fee": f.fee, "tag": f.tag, "realized_pnl": f.realized_pnl}
                    for f in store.load_fills(limit=min(n, 2000))])
            elif url.path == "/api/events":
                self._json(store.load_events(limit=min(n, 500)))
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:  # keep the dashboard alive no matter what
            self._send(500, str(e).encode(), "text/plain")

    def log_message(self, *_args):  # silence request logging
        pass


class DashboardServer:
    def __init__(self, state_db: str, host: str = "127.0.0.1", port: int = 8899,
                 token: str | None = None):
        if host not in ("127.0.0.1", "localhost", "::1") and not token:
            raise ValueError(
                f"refusing to serve the dashboard on {host!r} without a token — "
                "pass a secret token so only people with the link can view it")
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.store = StateStore(state_db)  # type: ignore[attr-defined]
        self.httpd.token = token  # type: ignore[attr-defined]
        self.host, self.port = host, self.httpd.server_address[1]
        self.token = token
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="dashboard", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
