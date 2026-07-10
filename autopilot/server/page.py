"""Shared HTML chrome: design tokens, layout CSS and the SVG line chart.

Both the live dashboard and the offline backtest report embed these strings,
so every page in the platform looks and behaves identically. Zero external
assets — pages work offline and inside strict CSPs.
"""

BASE_CSS = """
:root {
  --surface-1:#fcfcfb; --page:#f9f9f7; --ink-1:#0b0b0b; --ink-2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --baseline:#c3c2b7;
  --border:rgba(11,11,11,0.10);
  --series-1:#2a78d6; --series-2:#1baf7a; --series-3:#eda100; --series-4:#008300;
  --bench:#898781; --wash:rgba(42,120,214,0.10);
  --good:#0ca30c; --good-text:#006300; --warning:#fab219; --serious:#ec835a;
  --critical:#d03b3b;
}
@media (prefers-color-scheme: dark) { :root {
  --surface-1:#1a1a19; --page:#0d0d0d; --ink-1:#ffffff; --ink-2:#c3c2b7;
  --muted:#898781; --grid:#2c2c2a; --baseline:#383835;
  --border:rgba(255,255,255,0.10);
  --series-1:#3987e5; --series-2:#199e70; --series-3:#c98500; --series-4:#008300;
  --bench:#898781; --wash:rgba(57,135,229,0.10);
  --good:#0ca30c; --good-text:#0ca30c;
}}
:root[data-theme="light"] {
  --surface-1:#fcfcfb; --page:#f9f9f7; --ink-1:#0b0b0b; --ink-2:#52514e;
  --grid:#e1e0d9; --baseline:#c3c2b7; --border:rgba(11,11,11,0.10);
  --series-1:#2a78d6; --series-2:#1baf7a; --series-3:#eda100; --series-4:#008300;
  --wash:rgba(42,120,214,0.10); --good-text:#006300;
}
:root[data-theme="dark"] {
  --surface-1:#1a1a19; --page:#0d0d0d; --ink-1:#ffffff; --ink-2:#c3c2b7;
  --grid:#2c2c2a; --baseline:#383835; --border:rgba(255,255,255,0.10);
  --series-1:#3987e5; --series-2:#199e70; --series-3:#c98500; --series-4:#008300;
  --wash:rgba(57,135,229,0.10); --good-text:#0ca30c;
}
* { box-sizing:border-box; margin:0; }
body { background:var(--page); color:var(--ink-1);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; padding:20px; }
.wrap { max-width:1080px; margin:0 auto; }
header.top { display:flex; flex-wrap:wrap; align-items:baseline; gap:10px 14px;
  margin-bottom:16px; }
header.top h1 { font-size:20px; font-weight:650; }
.sub { color:var(--ink-2); font-size:13px; }
.badge { font-size:11px; font-weight:650; letter-spacing:.06em; padding:2px 8px;
  border-radius:999px; border:1px solid var(--border); color:var(--ink-2); }
.badge.live { color:var(--critical); border-color:var(--critical); }
.pill { font-size:12px; font-weight:600; padding:2px 10px; border-radius:999px; }
.pill.ok { color:var(--good-text); background:rgba(12,163,12,.12); }
.pill.warn { color:var(--serious); background:rgba(236,131,90,.14); }
.pill.bad { color:var(--critical); background:rgba(208,59,59,.14); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
  gap:10px; margin-bottom:14px; }
.tile { background:var(--surface-1); border:1px solid var(--border);
  border-radius:10px; padding:10px 12px; }
.tile .lbl { font-size:12px; color:var(--ink-2); }
.tile .val { font-size:20px; font-weight:600; margin-top:2px; }
.tile .delta { font-size:12px; margin-top:2px; color:var(--ink-2); }
.delta.up { color:var(--good-text); } .delta.down { color:var(--critical); }
.card { background:var(--surface-1); border:1px solid var(--border);
  border-radius:10px; padding:14px 16px; margin-bottom:14px; }
.card h2 { font-size:14px; font-weight:650; margin-bottom:8px; }
.card .note { color:var(--ink-2); font-size:12px; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:12px;
  color:var(--ink-2); margin:2px 0 6px; }
.legend .key { display:inline-flex; align-items:center; gap:6px; }
.key svg { flex:none; }
.chart-box { position:relative; }
.chart-box svg.plot { display:block; width:100%; }
.tooltip { position:absolute; pointer-events:none; background:var(--surface-1);
  border:1px solid var(--border); border-radius:8px; padding:8px 10px;
  box-shadow:0 2px 10px rgba(0,0,0,.18); font-size:12px; display:none;
  min-width:150px; z-index:5; }
.tooltip .tt-date { color:var(--ink-2); margin-bottom:4px; }
.tooltip .tt-row { display:flex; align-items:center; gap:6px; margin-top:2px; }
.tooltip .tt-val { font-weight:650; color:var(--ink-1); }
.tooltip .tt-name { color:var(--ink-2); }
.controls { display:flex; gap:14px; align-items:center; font-size:12px;
  color:var(--ink-2); margin-bottom:4px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; color:var(--ink-2); font-weight:600; font-size:12px;
  border-bottom:1px solid var(--grid); padding:5px 8px; }
td { padding:5px 8px; border-bottom:1px solid var(--grid);
  font-variant-numeric:tabular-nums; }
tr:last-child td { border-bottom:none; }
td.num, th.num { text-align:right; }
.side { display:inline-flex; align-items:center; gap:6px; }
.side .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
.side.buy .dot { background:var(--good); } .side.sell .dot { background:var(--critical); }
.scroll { overflow-x:auto; }
.disclaimer { border-left:3px solid var(--warning); padding:10px 12px;
  font-size:12.5px; color:var(--ink-2); background:var(--surface-1);
  border-radius:0 8px 8px 0; margin-bottom:14px; }
details { margin-top:8px; } summary { cursor:pointer; color:var(--ink-2); font-size:12px; }
footer { color:var(--muted); font-size:12px; margin-top:18px; }
a { color:var(--series-1); }
.loading { opacity:.55; transition:opacity .2s; }
"""

CHART_JS = r"""
'use strict';
function fmtMoney(v, dp) {
  if (v == null || !isFinite(v)) return '–';
  const sign = v < 0 ? '-' : '';
  const a = Math.abs(v);
  if (a >= 1e6) return sign + '$' + (a / 1e6).toFixed(Math.max(2, dp||0)) + 'M';
  if (a >= 1e4) return sign + '$' + (a / 1e3).toFixed(Math.max(1, dp||0)) + 'K';
  return sign + '$' + a.toLocaleString('en-US',
    {minimumFractionDigits: dp==null?2:dp, maximumFractionDigits: dp==null?2:dp});
}
function fmtNum(v, dp) {
  if (v == null || !isFinite(v)) return '–';
  if (Math.abs(v) < 1e-9) v = 0;  // never render "-0"
  return v.toLocaleString('en-US', {maximumFractionDigits: dp==null?1:dp});
}
function fmtTs(ms) {
  const d = new Date(ms);
  const p = n => String(n).padStart(2, '0');
  return d.getUTCFullYear() + '-' + p(d.getUTCMonth()+1) + '-' + p(d.getUTCDate())
    + ' ' + p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
}
function tickDate(ms, spanMs) {
  const d = new Date(ms);
  const p = n => String(n).padStart(2, '0');
  const mo = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  if (spanMs > 400 * 864e5) return mo[d.getUTCMonth()] + " '" + String(d.getUTCFullYear()).slice(2);
  if (spanMs > 15 * 864e5) return mo[d.getUTCMonth()] + ' ' + d.getUTCDate();
  if (spanMs > 864e5) return mo[d.getUTCMonth()] + ' ' + d.getUTCDate() + ' ' + p(d.getUTCHours()) + ':00';
  return p(d.getUTCHours()) + ':' + p(d.getUTCMinutes());
}
function niceTicks(lo, hi, n) {
  if (!(hi > lo)) { hi = lo + 1; }
  const span = hi - lo, step0 = Math.pow(10, Math.floor(Math.log10(span / n)));
  let step = step0;
  for (const m of [1, 2, 2.5, 5, 10]) { if (span / (step0 * m) <= n) { step = step0 * m; break; } }
  const ticks = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
  return ticks;
}
function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888';
}
const SVGNS = 'http://www.w3.org/2000/svg';
function svgEl(tag, attrs) {
  const el = document.createElementNS(SVGNS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}
// lineChart(container, spec)
// spec = { ts:[...ms], series:[{name,colorVar,dash,wash,values:[...]}],
//          money:bool, logToggle:bool, height }
function lineChart(box, spec) {
  box.classList.add('chart-box');
  box.textContent = '';
  const legend = document.createElement('div');
  if (spec.series.length >= 2) {
    legend.className = 'legend';
    for (const s of spec.series) {
      const key = document.createElement('span'); key.className = 'key';
      const sw = svgEl('svg', {width: 18, height: 6});
      const ln = svgEl('line', {x1: 1, y1: 3, x2: 17, y2: 3,
        stroke: cssVar(s.colorVar), 'stroke-width': 2,
        'stroke-linecap': 'round'});
      if (s.dash) ln.setAttribute('stroke-dasharray', '4 3');
      sw.appendChild(ln); key.appendChild(sw);
      key.appendChild(document.createTextNode(s.name));
      legend.appendChild(key);
    }
    box.appendChild(legend);
  }
  let useLog = false;
  if (spec.logToggle) {
    const ctl = document.createElement('label'); ctl.className = 'controls';
    const cb = document.createElement('input'); cb.type = 'checkbox';
    cb.addEventListener('change', () => { useLog = cb.checked; render(); });
    ctl.appendChild(cb); ctl.appendChild(document.createTextNode(' log scale'));
    box.appendChild(ctl);
  }
  const holder = document.createElement('div');
  box.appendChild(holder);
  const tooltip = document.createElement('div');
  tooltip.className = 'tooltip';
  box.appendChild(tooltip);
  const fmt = spec.money ? fmtMoney : (v) => fmtNum(v, 1);

  function render() {
    holder.textContent = '';
    const W = Math.max(box.clientWidth - 2, 320), H = spec.height || 300;
    const M = {l: 58, r: 84, t: 12, b: 26};
    const ts = spec.ts, n = ts.length;
    if (!n) { holder.textContent = 'no data yet'; return; }
    const all = [];
    for (const s of spec.series) for (const v of s.values) if (v != null && isFinite(v)) all.push(v);
    let lo = Math.min(...all), hi = Math.max(...all);
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    const pad = (hi - lo) * 0.06 || Math.abs(hi) * 0.05 || 1;
    lo -= pad; hi += pad;
    if (useLog) lo = Math.max(lo, Math.min(...all.filter(v => v > 0)) * 0.95 || 1e-6);
    const x0 = ts[0], x1 = ts[n-1] || x0 + 1;
    const X = t => M.l + (W - M.l - M.r) * (t - x0) / Math.max(x1 - x0, 1);
    const yv = v => useLog ? Math.log(Math.max(v, lo)) : v;
    const ylo = yv(lo), yhi = yv(hi);
    const Y = v => M.t + (H - M.t - M.b) * (1 - (yv(v) - ylo) / Math.max(yhi - ylo, 1e-12));
    const svg = svgEl('svg', {class: 'plot', viewBox: `0 0 ${W} ${H}`,
      width: W, height: H, role: 'img'});

    const yticks = useLog
      ? niceTicks(lo, hi, 4).filter(v => v > 0)
      : niceTicks(lo, hi, 4);
    for (const v of yticks) {
      if (v < lo || v > hi) continue;
      svg.appendChild(svgEl('line', {x1: M.l, x2: W - M.r, y1: Y(v), y2: Y(v),
        stroke: cssVar('--grid'), 'stroke-width': 1}));
      const t = svgEl('text', {x: M.l - 8, y: Y(v) + 4, 'text-anchor': 'end',
        'font-size': 11, fill: cssVar('--muted'),
        style: 'font-variant-numeric:tabular-nums'});
      const tight = (hi - lo) < Math.abs(hi) * 0.05;
      t.textContent = spec.money ? fmtMoney(v, tight ? 2 : 0)
                                 : fmtNum(v, hi < 10 || tight ? 1 : 0);
      svg.appendChild(t);
    }
    svg.appendChild(svgEl('line', {x1: M.l, x2: W - M.r, y1: H - M.b, y2: H - M.b,
      stroke: cssVar('--baseline'), 'stroke-width': 1}));
    const nx = Math.min(6, n);
    for (let i = 0; i < nx; i++) {
      const idx = Math.round(i * (n - 1) / Math.max(nx - 1, 1));
      const t = svgEl('text', {x: X(ts[idx]), y: H - 8, 'text-anchor': 'middle',
        'font-size': 11, fill: cssVar('--muted')});
      t.textContent = tickDate(ts[idx], x1 - x0);
      svg.appendChild(t);
    }
    for (const s of spec.series) {
      const col = cssVar(s.colorVar);
      let d = '', started = false;
      for (let i = 0; i < n; i++) {
        const v = s.values[i];
        if (v == null || !isFinite(v)) { continue; }
        d += (started ? 'L' : 'M') + X(ts[i]).toFixed(1) + ' ' + Y(v).toFixed(1);
        started = true;
      }
      if (!started) continue;
      if (s.wash) {
        const dv = s.values.filter(v => v != null && isFinite(v));
        const areaD = d + `L${X(ts[n-1]).toFixed(1)} ${H-M.b}L${X(ts[0]).toFixed(1)} ${H-M.b}Z`;
        svg.appendChild(svgEl('path', {d: areaD, fill: col, 'fill-opacity': 0.1,
          stroke: 'none'}));
      }
      const path = svgEl('path', {d, fill: 'none', stroke: col, 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round'});
      if (s.dash) path.setAttribute('stroke-dasharray', '5 4');
      svg.appendChild(path);
    }
    // Direct end labels (skip when they would collide; legend+tooltip carry those).
    const ends = spec.series
      .map(s => ({s, v: s.values[n-1]}))
      .filter(e => e.v != null && isFinite(e.v))
      .sort((a, b) => Y(a.v) - Y(b.v));
    let lastY = -99;
    for (const e of ends) {
      const y = Y(e.v);
      if (y - lastY < 13) continue;
      lastY = y;
      const t = svgEl('text', {x: W - M.r + 6, y: y + 4, 'font-size': 11,
        fill: cssVar('--ink-2'), style: 'font-variant-numeric:tabular-nums'});
      t.textContent = fmt(e.v);
      svg.appendChild(t);
    }
    // Hover layer: crosshair + one tooltip listing every series at that X.
    const cross = svgEl('line', {y1: M.t, y2: H - M.b, stroke: cssVar('--baseline'),
      'stroke-width': 1, visibility: 'hidden'});
    svg.appendChild(cross);
    const dots = spec.series.map(s => {
      const c = svgEl('circle', {r: 4, fill: cssVar(s.colorVar),
        stroke: cssVar('--surface-1'), 'stroke-width': 2, visibility: 'hidden'});
      svg.appendChild(c); return c;
    });
    const hit = svgEl('rect', {x: M.l, y: M.t, width: W - M.l - M.r,
      height: H - M.t - M.b, fill: 'transparent', tabindex: 0});
    svg.appendChild(hit);
    let focusIdx = null;
    function showAt(idx, px, py) {
      const t = ts[idx];
      cross.setAttribute('x1', X(t)); cross.setAttribute('x2', X(t));
      cross.setAttribute('visibility', 'visible');
      tooltip.textContent = '';
      const dt = document.createElement('div'); dt.className = 'tt-date';
      dt.textContent = fmtTs(t); tooltip.appendChild(dt);
      spec.series.forEach((s, k) => {
        const v = s.values[idx];
        if (v == null || !isFinite(v)) { dots[k].setAttribute('visibility','hidden'); return; }
        dots[k].setAttribute('cx', X(t)); dots[k].setAttribute('cy', Y(v));
        dots[k].setAttribute('visibility', 'visible');
        const row = document.createElement('div'); row.className = 'tt-row';
        const sw = svgEl('svg', {width: 14, height: 4});
        const ln = svgEl('line', {x1: 1, y1: 2, x2: 13, y2: 2,
          stroke: cssVar(s.colorVar), 'stroke-width': 2});
        if (s.dash) ln.setAttribute('stroke-dasharray', '3 2');
        sw.appendChild(ln); row.appendChild(sw);
        const val = document.createElement('span'); val.className = 'tt-val';
        val.textContent = fmt(v); row.appendChild(val);
        const nm = document.createElement('span'); nm.className = 'tt-name';
        nm.textContent = s.name; row.appendChild(nm);
        tooltip.appendChild(row);
      });
      tooltip.style.display = 'block';
      const bw = box.clientWidth, tw = tooltip.offsetWidth;
      let left = px + 14;
      if (left + tw > bw - 4) left = px - tw - 14;
      tooltip.style.left = Math.max(0, left) + 'px';
      tooltip.style.top = Math.max(0, py - 10) + 'px';
    }
    function hide() {
      cross.setAttribute('visibility', 'hidden');
      dots.forEach(d => d.setAttribute('visibility', 'hidden'));
      tooltip.style.display = 'none'; focusIdx = null;
    }
    hit.addEventListener('pointermove', ev => {
      const r = svg.getBoundingClientRect();
      const fx = (ev.clientX - r.left) * (W / r.width);
      let best = 0, bd = Infinity;
      for (let i = 0; i < n; i++) {
        const d = Math.abs(X(ts[i]) - fx);
        if (d < bd) { bd = d; best = i; }
      }
      const boxR = box.getBoundingClientRect();
      showAt(best, ev.clientX - boxR.left, ev.clientY - boxR.top);
    });
    hit.addEventListener('pointerleave', hide);
    hit.addEventListener('focus', () => { focusIdx = n - 1;
      showAt(focusIdx, W / 2, M.t + 20); });
    hit.addEventListener('blur', hide);
    hit.addEventListener('keydown', ev => {
      if (focusIdx == null) return;
      if (ev.key === 'ArrowLeft') focusIdx = Math.max(0, focusIdx - 1);
      else if (ev.key === 'ArrowRight') focusIdx = Math.min(n - 1, focusIdx + 1);
      else if (ev.key === 'Escape') { hide(); return; }
      else return;
      ev.preventDefault();
      showAt(focusIdx, W / 2, M.t + 20);
    });
    holder.appendChild(svg);
  }
  render();
  let raf = null;
  window.addEventListener('resize', () => {
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(render);
  });
  return {render};
}
"""


def html_page(title: str, body: str, script: str = "") -> str:
    import html as _html
    title = _html.escape(title, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>{BASE_CSS}</style>
</head>
<body>
<div class="wrap">
{body}
</div>
<script>{CHART_JS}</script>
<script>{script}</script>
</body>
</html>
"""


def safe_json(payload: str) -> str:
    """Make a JSON string safe to inline inside a <script> block."""
    return payload.replace("</", "<\\/")
