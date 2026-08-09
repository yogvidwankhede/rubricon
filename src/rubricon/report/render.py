"""Static HTML dashboard renderer for a Rubricon portfolio.

Produces one self-contained ``dashboard.html``: all CSS, JavaScript and data are
inlined, so the file works offline and opens by double-click. No network
requests, no chart library, no web storage.

Public API
----------
render_dashboard(data, out_path) -> Path
render_all(data, results_dir)    -> list[Path]
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = ["render_dashboard", "render_all"]

# --------------------------------------------------------------------------
# small formatting helpers
# --------------------------------------------------------------------------

_MISSING = "n/a"


def e(value: Any) -> str:
    """HTML-escape any value."""
    return html.escape("" if value is None else str(value), quote=True)


def num(value: Any, nd: int = 3, dash: str = _MISSING) -> str:
    if value is None or value == "":
        return dash
    try:
        return f"{float(value):.{nd}f}"
    except (TypeError, ValueError):
        return e(value)


def pct(value: Any, nd: int = 0, dash: str = _MISSING) -> str:
    if value is None or value == "":
        return dash
    try:
        return f"{float(value) * 100:.{nd}f}%"
    except (TypeError, ValueError):
        return e(value)


def intg(value: Any, dash: str = _MISSING) -> str:
    if value is None:
        return dash
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return e(value)


def slug(value: Any) -> str:
    out = []
    for ch in str(value):
        out.append(ch if (ch.isalnum() or ch in "-_") else "-")
    return "".join(out)


def get(obj: Any, *path: str, default: Any = None) -> Any:
    """Defensive nested lookup: portfolio.json may legitimately omit blocks."""
    cur = obj
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


# semantic vocabularies ------------------------------------------------------

VERDICT_LABEL = {"pass": "pass", "warn": "warn", "block": "block"}
REC_LABEL = {
    "invest": "invest",
    "iterate": "iterate",
    "hold": "hold",
    "stop": "stop",
}
DEPTH_ORDER = ["exploratory", "pilot", "production"]


def verdict_pill(verdict: str) -> str:
    v = str(verdict or "").lower()
    cls = v if v in VERDICT_LABEL else "neutral"
    return f'<span class="pill pill-{cls}">{e(VERDICT_LABEL.get(v, verdict or _MISSING))}</span>'


def rec_pill(rec: str, large: bool = False) -> str:
    r = str(rec or "").lower()
    cls = r if r in REC_LABEL else "neutral"
    size = " pill-lg" if large else ""
    return f'<span class="pill pill-rec-{cls}{size}">{e(REC_LABEL.get(r, rec or _MISSING))}</span>'


def yesno_pill(flag: Any, yes: str = "yes", no: str = "no", good: str = "yes") -> str:
    truthy = bool(flag)
    label = yes if truthy else no
    cls = "pass" if (label == good) else "block"
    return f'<span class="pill pill-{cls}">{e(label)}</span>'


def alpha_band(alpha: float) -> tuple[str, str]:
    """Return (css-suffix, short text label) for a Krippendorff alpha."""
    if alpha is None:
        return "neutral", _MISSING
    if alpha < 0.50:
        return "block", "block"
    if alpha < 0.667:
        return "warn", "warn"
    if alpha < 0.80:
        return "tent", "tentative"
    return "firm", "firm"


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#0d1117; --bg-2:#11161e; --surface:#151b24; --surface-2:#1a212b;
  --surface-3:#202834; --line:#28313f; --line-2:#343f50;
  --ink:#e9eef6; --ink-2:#b3c0d1; --ink-3:#8593a8;
  --accent:#7aa2f7; --accent-dim:#3d5a94;
  --pass:#59c08a; --warn:#e0ab48; --block:#e56a76; --tent:#7aa2f7;
  --pass-bg:rgba(89,192,138,.13); --warn-bg:rgba(224,171,72,.13);
  --block-bg:rgba(229,106,118,.13); --tent-bg:rgba(122,162,247,.13);
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,"Liberation Mono",monospace;
  --radius:10px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font-family:var(--sans); font-size:15px; line-height:1.6;
  letter-spacing:.005em;
}
.wrap{max-width:1180px; margin:0 auto; padding:0 28px}
h1,h2,h3,h4{line-height:1.25; margin:0; font-weight:620; letter-spacing:-.01em}
h2{font-size:1.32rem}
h3{font-size:1.05rem}
h4{font-size:.92rem; color:var(--ink-2); font-weight:600}
p{margin:0 0 .85em}
a{color:var(--accent)}
code,.mono{font-family:var(--mono); font-variant-numeric:tabular-nums}
.muted{color:var(--ink-3)}
.dim{color:var(--ink-2)}
.small{font-size:.82rem}
.tiny{font-size:.74rem}
.upper{text-transform:uppercase; letter-spacing:.12em; font-size:.7rem; font-weight:700}
.stack>*+*{margin-top:14px}

/* ---------- header ---------- */
header.masthead{
  border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,#131a24 0%,var(--bg) 100%);
  padding:38px 0 26px;
}
.brandrow{display:flex; align-items:baseline; gap:16px; flex-wrap:wrap}
.brand{font-size:2.1rem; font-weight:680; letter-spacing:-.025em}
.brand .dotmark{color:var(--accent)}
.tagline{color:var(--ink-2); font-size:.98rem; max-width:62ch}
.metastrip{
  display:flex; flex-wrap:wrap; gap:10px 26px; margin-top:18px;
  font-family:var(--mono); font-size:.78rem; color:var(--ink-3);
}
.metastrip b{color:var(--ink); font-weight:600}

/* ---------- simulation banner ---------- */
.simbanner{
  margin:24px 0 4px; border:2px solid var(--warn); border-radius:var(--radius);
  background:
    repeating-linear-gradient(135deg,rgba(224,171,72,.11) 0 12px,rgba(224,171,72,.045) 12px 24px);
  overflow:hidden;
}
.simbanner .simhead{
  background:var(--warn); color:#1a1204; padding:9px 18px;
  font-weight:800; letter-spacing:.14em; text-transform:uppercase; font-size:.76rem;
  display:flex; gap:12px; align-items:center;
}
.simbanner .simhead .mark{
  font-family:var(--mono); border:2px solid #1a1204; border-radius:4px;
  padding:0 6px; font-size:.72rem; letter-spacing:.05em;
}
.simbanner .simbody{padding:16px 18px; color:#f6e9cd; font-size:.95rem; max-width:96ch}
.simbanner .simbody strong{color:#fff}

/* ---------- tabs ---------- */
.tabbar{
  position:sticky; top:0; z-index:30; background:rgba(13,17,23,.94);
  backdrop-filter:blur(8px); border-bottom:1px solid var(--line);
}
.tablist{display:flex; gap:2px; overflow-x:auto; scrollbar-width:thin; padding:0}
.tablist button{
  appearance:none; background:none; border:none; border-bottom:2px solid transparent;
  color:var(--ink-3); font:inherit; font-size:.86rem; font-weight:600;
  padding:14px 15px; cursor:pointer; white-space:nowrap; letter-spacing:.01em;
}
.tablist button:hover{color:var(--ink); background:var(--surface)}
.tablist button[aria-selected="true"]{color:var(--ink); border-bottom-color:var(--accent)}
.tablist button:focus-visible,
button:focus-visible,select:focus-visible,input:focus-visible,[tabindex]:focus-visible{
  outline:2px solid var(--accent); outline-offset:2px; border-radius:3px;
}
.panel{padding:34px 0 10px}
.panel[hidden]{display:none}
section.block{margin:0 0 38px}
.block>h2{margin-bottom:6px}
.block>.lede{color:var(--ink-2); max-width:78ch; margin-bottom:18px}

/* ---------- cards ---------- */
.cards{display:grid; grid-template-columns:repeat(auto-fit,minmax(min(268px,100%),1fr)); gap:16px}
.trackcard{
  display:block; width:100%; text-align:left; cursor:pointer; font:inherit; color:inherit;
  background:var(--surface); border:1px solid var(--line); border-radius:var(--radius);
  padding:18px; transition:border-color .12s ease, transform .12s ease, background .12s ease;
}
.trackcard:hover{border-color:var(--line-2); background:var(--surface-2); transform:translateY(-1px)}
.trackcard .cardtop{display:flex; justify-content:space-between; align-items:flex-start; gap:10px}
.trackcard .tname{font-weight:640; font-size:1.02rem}
.trackcard .tkey{font-family:var(--mono); font-size:.72rem; color:var(--ink-3); margin-top:2px}
.kvgrid{display:grid; grid-template-columns:1fr 1fr; gap:12px 14px; margin-top:16px}
.kv .k{font-size:.7rem; text-transform:uppercase; letter-spacing:.1em; color:var(--ink-3)}
.kv .v{font-family:var(--mono); font-size:1.02rem; font-weight:600; margin-top:1px}
.verdictbar{display:flex; gap:6px; margin-top:14px; flex-wrap:wrap}
.cardcta{margin-top:14px; font-size:.78rem; color:var(--accent)}

/* ---------- pills / badges ---------- */
.pill{
  display:inline-flex; align-items:center; gap:6px; border-radius:999px;
  padding:2px 10px; font-size:.74rem; font-weight:650; letter-spacing:.03em;
  border:1px solid transparent; white-space:nowrap;
}
.pill-lg{font-size:.88rem; padding:4px 14px}
.pill::before{content:""; width:7px; height:7px; border-radius:2px; background:currentColor; flex:none}
.pill-pass,.pill-rec-invest{color:var(--pass); background:var(--pass-bg); border-color:rgba(89,192,138,.4)}
.pill-warn,.pill-rec-iterate{color:var(--warn); background:var(--warn-bg); border-color:rgba(224,171,72,.4)}
.pill-block,.pill-rec-stop{color:var(--block); background:var(--block-bg); border-color:rgba(229,106,118,.42)}
.pill-rec-hold,.pill-tent{color:var(--tent); background:var(--tent-bg); border-color:rgba(122,162,247,.4)}
.pill-neutral{color:var(--ink-2); background:var(--surface-3); border-color:var(--line-2)}
.pill-rec-invest::before,.pill-pass::before{border-radius:999px}
.pill-rec-stop::before,.pill-block::before{border-radius:1px}
.badge{
  display:inline-block; font-family:var(--mono); font-size:.68rem; letter-spacing:.06em;
  text-transform:uppercase; padding:1px 7px; border-radius:4px;
  border:1px solid var(--line-2); color:var(--ink-2); background:var(--surface-3);
}
.badge-depth-production{color:var(--pass); border-color:rgba(89,192,138,.45); background:var(--pass-bg)}
.badge-depth-pilot{color:var(--tent); border-color:rgba(122,162,247,.45); background:var(--tent-bg)}
.badge-depth-exploratory{color:var(--warn); border-color:rgba(224,171,72,.45); background:var(--warn-bg)}
.badge-contested{color:var(--warn); border-color:rgba(224,171,72,.45); background:var(--warn-bg)}
.badge-blind{color:var(--block); border-color:rgba(229,106,118,.45); background:var(--block-bg)}

/* ---------- stats ---------- */
.statrow{display:grid; grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr)); gap:14px}
.stat{background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px}
.stat .k{font-size:.68rem; text-transform:uppercase; letter-spacing:.11em; color:var(--ink-3)}
.stat .v{font-family:var(--mono); font-size:1.5rem; font-weight:620; margin-top:4px; line-height:1.1}
.stat .sub{font-size:.76rem; color:var(--ink-3); margin-top:4px}
.stat.huge .v{font-size:2.9rem; letter-spacing:-.03em}
.stat.accentborder{border-left:3px solid var(--accent)}
.stat.blockborder{border-left:3px solid var(--block)}

/* ---------- tables ---------- */
.tablewrap{overflow-x:auto; border:1px solid var(--line); border-radius:var(--radius); background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:.86rem}
caption{caption-side:top; text-align:left; padding:12px 16px 0; color:var(--ink-3); font-size:.78rem}
th,td{padding:9px 14px; text-align:left; border-bottom:1px solid var(--line); vertical-align:top}
thead th{
  position:sticky; top:0; background:var(--surface-2); color:var(--ink-2);
  font-size:.7rem; text-transform:uppercase; letter-spacing:.09em; font-weight:700;
  border-bottom:1px solid var(--line-2); z-index:1;
}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--surface-2)}
td.n,th.n{font-family:var(--mono); font-variant-numeric:tabular-nums; text-align:right; white-space:nowrap}
th.n{text-align:right}
td.code{font-family:var(--mono); font-size:.8rem; white-space:nowrap}
.rowflag-blind{box-shadow:inset 3px 0 0 var(--block)}
.rowflag-blind td:first-child{padding-left:14px}

/* MDE emphasis */
th.mde,td.mde{background:var(--surface-3); border-left:1px solid var(--line-2); border-right:1px solid var(--line-2)}
td.mde{font-family:var(--mono); font-size:1rem; font-weight:640; color:var(--ink)}
th.mde{color:var(--ink)}

/* ---------- ledger ---------- */
.filters{display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; margin:18px 0 14px}
.field{display:flex; flex-direction:column; gap:5px}
.field label{font-size:.68rem; text-transform:uppercase; letter-spacing:.1em; color:var(--ink-3)}
select,input[type=search]{
  background:var(--surface-2); color:var(--ink); border:1px solid var(--line-2);
  border-radius:6px; padding:7px 10px; font:inherit; font-size:.84rem; min-width:170px;
}
.filtercount{margin-left:auto; font-family:var(--mono); font-size:.8rem; color:var(--ink-3)}
.claimtext{max-width:62ch}
.claim-struck{color:var(--ink-3); text-decoration:line-through; text-decoration-color:var(--block); opacity:.72}
.blockreason{
  margin-top:6px; color:var(--block); font-size:.82rem;
  border-left:2px solid var(--block); padding-left:10px;
}
.warnreason{margin-top:6px; color:var(--warn); font-size:.8rem; border-left:2px solid var(--warn); padding-left:10px}
.checklist{margin:8px 0 2px; padding:0; list-style:none; display:grid; gap:6px}
.checklist li{display:grid; grid-template-columns:78px 1fr; gap:10px; align-items:start; font-size:.82rem}
.checklist .cmsg{color:var(--ink-2)}
.checklist .cname{font-family:var(--mono); font-size:.74rem; color:var(--ink-3)}
.checklist .cremedy{color:var(--warn); font-size:.78rem; margin-top:2px}
.detailrow td{background:var(--bg-2)}
.linkbtn{
  appearance:none; background:none; border:1px solid var(--line-2); color:var(--ink-2);
  border-radius:6px; padding:3px 9px; font:inherit; font-size:.74rem; cursor:pointer;
}
.linkbtn:hover{color:var(--ink); border-color:var(--accent-dim); background:var(--surface-2)}

/* ---------- charts ---------- */
figure.chart{margin:0; background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:16px 18px; overflow-x:auto}
figure.chart figcaption{color:var(--ink-3); font-size:.78rem; margin-bottom:10px}
svg.viz{display:block; width:100%; height:auto; max-width:100%}
figure.chart>svg.viz{min-width:540px; max-width:none}
.grid2>*,.grid3>*,.cards>*,.statrow>*{min-width:0}
svg.viz text{font-family:var(--sans); fill:var(--ink-2)}
svg.viz text.lbl{font-size:11.5px; fill:var(--ink)}
svg.viz text.sub{font-size:9.5px; fill:var(--warn)}
svg.viz text.val{font-family:var(--mono); font-size:11px; fill:var(--ink); font-weight:600}
svg.viz text.band{font-size:10px; fill:var(--ink-3)}
svg.viz text.tick{font-family:var(--mono); font-size:10px; fill:var(--ink-3)}
svg.viz text.thr{font-family:var(--mono); font-size:9.5px}
svg.viz .axis{stroke:var(--line-2); stroke-width:1}
svg.viz .grid{stroke:var(--line); stroke-width:1}
svg.viz .track{fill:var(--surface-3)}
svg.viz .thrline{stroke-width:1; stroke-dasharray:4 3}
svg.viz .thr-block,svg.viz .b-block{stroke:var(--block); fill:var(--block)}
svg.viz .thr-warn{stroke:var(--warn); fill:var(--warn)}
svg.viz .b-warn{fill:var(--warn)}
svg.viz .thr-firm{stroke:var(--pass); fill:var(--pass)}
svg.viz .b-firm{fill:var(--pass)}
svg.viz .b-tent{fill:var(--tent)}
svg.viz .b-neutral{fill:var(--ink-3)}
svg.viz .bar-score{fill:var(--accent-dim)}
svg.viz .bar-count{fill:var(--accent-dim)}
svg.viz .err{stroke:var(--ink); stroke-width:1.6; fill:none}
svg.viz .zero{stroke:var(--line-2); stroke-width:1}

/* ---------- callouts ---------- */
.callout{
  border:1px solid var(--line-2); border-left:3px solid var(--accent); border-radius:8px;
  background:var(--surface); padding:13px 16px; font-size:.88rem; color:var(--ink-2);
}
.callout.warn{border-left-color:var(--warn)}
.callout.block{border-left-color:var(--block)}
.callout.pass{border-left-color:var(--pass)}
.callout .ctitle{color:var(--ink); font-weight:650; font-size:.86rem; margin-bottom:4px; display:block}
.grid2{display:grid; grid-template-columns:repeat(auto-fit,minmax(min(330px,100%),1fr)); gap:18px}
.covergrid{display:grid; grid-template-columns:repeat(auto-fit,minmax(min(440px,100%),1fr)); gap:18px}
.covergrid>*{min-width:0}
.covergrid .panelbox{overflow-x:auto}
.grid3{display:grid; grid-template-columns:repeat(auto-fit,minmax(min(250px,100%),1fr)); gap:16px}
.deflist{display:grid; grid-template-columns:auto 1fr; gap:8px 18px; font-size:.88rem; margin:0}
.deflist dt{color:var(--ink-3); font-size:.7rem; text-transform:uppercase; letter-spacing:.1em; padding-top:3px}
.deflist dd{margin:0; color:var(--ink)}
ul.tight{margin:.2em 0; padding-left:1.15em}
ul.tight li{margin:.3em 0; color:var(--ink-2)}
ul.tight li::marker{color:var(--ink-3)}
ol.tight{margin:.2em 0; padding-left:1.3em}
ol.tight li{margin:.35em 0; color:var(--ink-2)}
.panelbox{background:var(--surface); border:1px solid var(--line); border-radius:var(--radius); padding:18px}
.panelbox>h3{margin-bottom:10px}
.hr{height:1px; background:var(--line); margin:30px 0; border:none}
.collapsed [data-collapsible-item]{display:none}
.togglewrap{margin-top:10px}
footer.methods{border-top:1px solid var(--line); margin-top:44px; padding:34px 0 60px; background:var(--bg-2)}
.probe{display:grid; grid-template-columns:auto 1fr; gap:12px; align-items:start; padding:12px 0; border-bottom:1px solid var(--line)}
.probe:last-child{border-bottom:none}
.probe .pname{font-family:var(--mono); font-size:.82rem; color:var(--ink)}
.probe .pinterp{color:var(--ink-2); font-size:.85rem; margin-top:3px}
.probe .pstat{font-family:var(--mono); font-size:.74rem; color:var(--ink-3); margin-top:3px}
.noscript{border:1px solid var(--warn); border-radius:8px; padding:12px 16px; color:var(--warn); margin:16px 0}
.skiplink{position:absolute; left:-9999px; top:0; z-index:100}
.skiplink:focus{
  left:12px; top:12px; background:var(--surface-3); color:var(--ink);
  border:1px solid var(--accent); border-radius:6px; padding:8px 14px; text-decoration:none;
}
@media (max-width:720px){
  .wrap{padding:0 16px}
  .brand{font-size:1.65rem}
  .stat.huge .v{font-size:2.1rem}
  .kvgrid{grid-template-columns:1fr 1fr}
  .checklist li{grid-template-columns:1fr}
}
@media print{
  body{background:#fff; color:#000}
  .tabbar{display:none}
  .panel[hidden]{display:block}
}
"""

# --------------------------------------------------------------------------
# behaviour
# --------------------------------------------------------------------------

JS = """
(function () {
  "use strict";

  var dataEl = document.getElementById("portfolio-data");
  var DATA = {};
  try { DATA = JSON.parse(dataEl.textContent); } catch (err) { DATA = { tracks: {} }; }
  window.RUBRICON = DATA;

  /* ---------------- tabs ---------------- */
  var tablist = document.getElementById("tablist");
  var tabs = tablist ? Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"]')) : [];

  function selectTab(id, moveFocus) {
    tabs.forEach(function (tab) {
      var on = tab.id === id;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      var panel = document.getElementById(tab.getAttribute("aria-controls"));
      if (panel) { if (on) { panel.removeAttribute("hidden"); } else { panel.setAttribute("hidden", ""); } }
      if (on && moveFocus) { tab.focus(); }
    });
    if (moveFocus !== "nofocus") { window.scrollTo({ top: 0, behavior: "auto" }); }
  }

  tabs.forEach(function (tab, i) {
    tab.addEventListener("click", function () { selectTab(tab.id, false); });
    tab.addEventListener("keydown", function (ev) {
      var next = null;
      if (ev.key === "ArrowRight") { next = tabs[(i + 1) % tabs.length]; }
      else if (ev.key === "ArrowLeft") { next = tabs[(i - 1 + tabs.length) % tabs.length]; }
      else if (ev.key === "Home") { next = tabs[0]; }
      else if (ev.key === "End") { next = tabs[tabs.length - 1]; }
      if (next) { ev.preventDefault(); selectTab(next.id, true); }
    });
  });

  document.addEventListener("click", function (ev) {
    var jump = ev.target.closest ? ev.target.closest("[data-goto-tab]") : null;
    if (jump) { selectTab(jump.getAttribute("data-goto-tab"), false); }
  });

  /* ---------------- disclosure toggles ---------------- */
  Array.prototype.forEach.call(document.querySelectorAll("[data-toggle]"), function (btn) {
    btn.addEventListener("click", function () {
      var target = document.getElementById(btn.getAttribute("data-toggle"));
      if (!target) { return; }
      var collapsed = target.classList.toggle("collapsed");
      btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      btn.textContent = collapsed ? btn.getAttribute("data-label-more")
                                  : btn.getAttribute("data-label-less");
    });
  });

  /* ---------------- signal-gate ledger ---------------- */
  var tbody = document.getElementById("ledger-body");
  if (!tbody) { return; }

  var trackNames = {};
  var rows = [];
  Object.keys(DATA.tracks || {}).forEach(function (key) {
    var track = DATA.tracks[key] || {};
    trackNames[key] = track.name || key;
    var claims = (track.gate && track.gate.claims) || [];
    claims.forEach(function (claim) {
      rows.push({ trackKey: key, claim: claim });
    });
  });

  var ORDER = { block: 0, warn: 1, pass: 2 };
  rows.sort(function (a, b) {
    var d = (ORDER[a.claim.verdict] === undefined ? 3 : ORDER[a.claim.verdict])
          - (ORDER[b.claim.verdict] === undefined ? 3 : ORDER[b.claim.verdict]);
    if (d !== 0) { return d; }
    if (a.trackKey !== b.trackKey) { return a.trackKey < b.trackKey ? -1 : 1; }
    return String(a.claim.claim_id) < String(b.claim.claim_id) ? -1 : 1;
  });

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) { node.className = cls; }
    if (text !== undefined && text !== null) { node.textContent = String(text); }
    return node;
  }

  function pill(kind, label) {
    var p = el("span", "pill pill-" + kind, label);
    return p;
  }

  function buildDetail(claim, colspan) {
    var tr = el("tr", "detailrow");
    tr.hidden = true;
    var td = el("td");
    td.colSpan = colspan;
    var head = el("div", "upper muted", "gate checks");
    td.appendChild(head);
    var ul = el("ul", "checklist");
    (claim.checks || []).forEach(function (check) {
      var li = document.createElement("li");
      var left = el("div");
      left.appendChild(pill(check.verdict, check.verdict));
      var right = el("div");
      right.appendChild(el("div", "cname", check.name));
      right.appendChild(el("div", "cmsg", check.message || ""));
      if (check.remedy) { right.appendChild(el("div", "cremedy", "Remedy: " + check.remedy)); }
      li.appendChild(left);
      li.appendChild(right);
      ul.appendChild(li);
    });
    if (!ul.childNodes.length) { ul.appendChild(el("li", "muted", "No checks recorded.")); }
    td.appendChild(ul);
    tr.appendChild(td);
    return tr;
  }

  var COLS = 5;

  function buildRow(entry) {
    var claim = entry.claim;
    var verdict = String(claim.verdict || "");
    var tr = el("tr");
    tr.setAttribute("data-verdict", verdict);
    tr.setAttribute("data-track", entry.trackKey);
    tr.setAttribute("data-text", ((claim.text || "") + " " + (claim.claim_id || "")).toLowerCase());

    var tdTrack = el("td");
    tdTrack.appendChild(el("div", null, trackNames[entry.trackKey] || entry.trackKey));
    tdTrack.appendChild(el("div", "tiny muted mono", claim.claim_id || ""));
    tr.appendChild(tdTrack);

    var tdKind = el("td", "small dim", claim.kind || "");
    tr.appendChild(tdKind);

    var tdVerdict = el("td");
    tdVerdict.appendChild(pill(verdict, verdict || "unknown"));
    tr.appendChild(tdVerdict);

    var tdClaim = el("td", "claimtext");
    if (verdict === "block") {
      var s = el("s", "claim-struck", claim.text || "");
      tdClaim.appendChild(s);
      var reasons = claim.blocking_reasons || [];
      if (!reasons.length) { reasons = ["Blocked by the signal gate; no reason recorded."]; }
      reasons.forEach(function (reason) {
        tdClaim.appendChild(el("div", "blockreason", "WITHHELD - " + reason));
      });
    } else {
      tdClaim.appendChild(el("span", null, claim.text || ""));
      (claim.warnings || []).forEach(function (warning) {
        tdClaim.appendChild(el("div", "warnreason", "Caveat - " + warning));
      });
    }
    tr.appendChild(tdClaim);

    var tdBtn = el("td");
    var nChecks = (claim.checks || []).length;
    var btn = el("button", "linkbtn", "checks (" + nChecks + ")");
    btn.type = "button";
    btn.setAttribute("aria-expanded", "false");
    tdBtn.appendChild(btn);
    tr.appendChild(tdBtn);

    var detail = buildDetail(claim, COLS);
    btn.addEventListener("click", function () {
      var open = detail.hidden;
      detail.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    return [tr, detail];
  }

  var pairs = rows.map(buildRow);
  pairs.forEach(function (pair) { tbody.appendChild(pair[0]); tbody.appendChild(pair[1]); });

  var fVerdict = document.getElementById("f-verdict");
  var fTrack = document.getElementById("f-track");
  var fText = document.getElementById("f-text");
  var counter = document.getElementById("ledger-count");
  var reset = document.getElementById("f-reset");

  function applyFilters() {
    var v = fVerdict.value, t = fTrack.value, q = (fText.value || "").trim().toLowerCase();
    var shown = 0;
    pairs.forEach(function (pair) {
      var tr = pair[0], detail = pair[1];
      var ok = (v === "all" || tr.getAttribute("data-verdict") === v)
            && (t === "all" || tr.getAttribute("data-track") === t)
            && (q === "" || tr.getAttribute("data-text").indexOf(q) !== -1);
      tr.hidden = !ok;
      if (!ok) {
        detail.hidden = true;
        var b = tr.querySelector(".linkbtn");
        if (b) { b.setAttribute("aria-expanded", "false"); }
      }
      if (ok) { shown += 1; }
    });
    counter.textContent = shown + " of " + pairs.length + " claims shown";
  }

  [fVerdict, fTrack].forEach(function (sel) { sel.addEventListener("change", applyFilters); });
  fText.addEventListener("input", applyFilters);
  reset.addEventListener("click", function () {
    fVerdict.value = "all"; fTrack.value = "all"; fText.value = ""; applyFilters();
  });
  applyFilters();
})();
"""


# --------------------------------------------------------------------------
# SVG chart primitives (hand-rolled; no chart library)
# --------------------------------------------------------------------------


def _svg_open(width: int, height: int, title: str, desc: str = "") -> list[str]:
    out = [
        f'<svg class="viz" viewBox="0 0 {width} {height}" role="img" '
        f'preserveAspectRatio="xMinYMin meet" aria-label="{e(title)}">',
        f"<title>{e(title)}</title>",
    ]
    if desc:
        out.append(f"<desc>{e(desc)}</desc>")
    return out


def svg_alpha_chart(agreement: dict, contested: Sequence[str]) -> str:
    """Horizontal Krippendorff alpha bars with 0.50 / 0.667 / 0.80 thresholds."""
    dims = sorted(
        agreement.items(),
        key=lambda kv: get(kv[1], "krippendorff_alpha", "value", default=-9),
        reverse=True,
    )
    if not dims:
        return '<p class="muted small">No agreement statistics recorded for this track.</p>'

    width, left, right = 760, 208, 118
    top, row_h, bottom = 46, 32, 48
    plot_w = width - left - right
    height = top + row_h * len(dims) + bottom

    values = [float(get(kv[1], "krippendorff_alpha", "value", default=0.0)) for kv in dims]
    lo = min(0.0, math.floor(min(values) * 10) / 10)
    hi = 1.0
    span = hi - lo

    def X(v: float) -> float:
        return left + (v - lo) / span * plot_w

    out = _svg_open(
        width,
        height,
        "Krippendorff's alpha by rubric dimension",
        "Horizontal bars with reference thresholds at 0.50, 0.667 and 0.80.",
    )

    # threshold guides (staggered labels so they never collide)
    thresholds = [
        (0.50, "thr-block", "0.50 block", 15),
        (0.667, "thr-warn", "0.667 tentative", 30),
        (0.80, "thr-firm", "0.80 firm", 15),
    ]
    baseline_y = top + row_h * len(dims)
    for value, cls, label, label_y in thresholds:
        x = X(value)
        out.append(
            f'<line class="thrline {cls}" x1="{x:.1f}" y1="{top - 6}" '
            f'x2="{x:.1f}" y2="{baseline_y + 4}" />'
        )
        anchor = "end" if value >= 0.80 else "start"
        dx = -4 if anchor == "end" else 4
        out.append(
            f'<text class="thr {cls}" x="{x + dx:.1f}" y="{label_y}" '
            f'text-anchor="{anchor}">{e(label)}</text>'
        )

    if lo < 0:
        out.append(
            f'<line class="zero" x1="{X(0):.1f}" y1="{top - 6}" '
            f'x2="{X(0):.1f}" y2="{baseline_y + 4}" />'
        )

    contested_set = {str(c) for c in (contested or [])}
    for i, (dim, stats) in enumerate(dims):
        alpha = float(get(stats, "krippendorff_alpha", "value", default=0.0))
        cls, band_label = alpha_band(alpha)
        y = top + i * row_h
        # track
        out.append(
            f'<rect class="track" x="{left}" y="{y + 5}" width="{plot_w}" height="13" rx="2" />'
        )
        x0, xv = X(0.0), X(alpha)
        bx, bw = min(x0, xv), max(1.5, abs(xv - x0))
        out.append(
            f'<rect class="b-{cls}" x="{bx:.1f}" y="{y + 5}" width="{bw:.1f}" height="13" rx="2" />'
        )
        out.append(
            f'<text class="lbl" x="{left - 12}" y="{y + 15}" text-anchor="end">{e(dim)}</text>'
        )
        if dim in contested_set:
            out.append(
                f'<text class="sub" x="{left - 12}" y="{y + 27}" '
                f'text-anchor="end">contested dimension</text>'
            )
        out.append(
            f'<text class="val" x="{left + plot_w + 38}" y="{y + 16}" '
            f'text-anchor="end">{num(alpha)}</text>'
        )
        out.append(
            f'<text class="band" x="{left + plot_w + 46}" y="{y + 16}">{e(band_label)}</text>'
        )

    # x axis
    axis_y = baseline_y + 12
    out.append(
        f'<line class="axis" x1="{left}" y1="{axis_y}" x2="{left + plot_w}" y2="{axis_y}" />'
    )
    tick = lo
    while tick <= hi + 1e-9:
        x = X(tick)
        out.append(f'<line class="axis" x1="{x:.1f}" y1="{axis_y}" x2="{x:.1f}" y2="{axis_y + 4}" />')
        out.append(
            f'<text class="tick" x="{x:.1f}" y="{axis_y + 16}" '
            f'text-anchor="middle">{num(tick, 2)}</text>'
        )
        tick += 0.25
    out.append(
        f'<text class="tick" x="{left + plot_w / 2:.1f}" y="{axis_y + 32}" '
        f'text-anchor="middle">Krippendorff\'s alpha (ordinal)</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def svg_score_chart(scores: dict) -> str:
    """Mean composite per system with 95% CI error bars."""
    systems = list(scores.items())
    if not systems:
        return '<p class="muted small">No system scores recorded for this track.</p>'

    width, left, right = 760, 176, 190
    top, row_h, bottom = 22, 42, 46
    plot_w = width - left - right
    height = top + row_h * len(systems) + bottom

    highs = [get(s, "ci", "hi", default=get(s, "mean_composite", default=0.0)) for _, s in systems]
    hi = max(1.0, max(float(h) for h in highs))
    lo = 0.0

    def X(v: float) -> float:
        return left + (float(v) - lo) / (hi - lo) * plot_w

    out = _svg_open(
        width,
        height,
        "Mean composite score by system with 95% confidence intervals",
        "Bars show the point estimate; whiskers show the cluster-bootstrap interval.",
    )

    tick = 0.0
    while tick <= hi + 1e-9:
        x = X(tick)
        out.append(f'<line class="grid" x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{top + row_h * len(systems) + 4}" />')
        tick += 0.25

    for i, (system, stats) in enumerate(systems):
        point = float(get(stats, "mean_composite", default=0.0))
        ci_lo = get(stats, "ci", "lo")
        ci_hi = get(stats, "ci", "hi")
        y = top + i * row_h
        cy = y + 15
        out.append(
            f'<rect class="bar-score" x="{left}" y="{y + 7}" '
            f'width="{max(1.0, X(point) - left):.1f}" height="17" rx="2" />'
        )
        if ci_lo is not None and ci_hi is not None:
            xl, xh = X(ci_lo), X(ci_hi)
            out.append(f'<line class="err" x1="{xl:.1f}" y1="{cy:.1f}" x2="{xh:.1f}" y2="{cy:.1f}" />')
            out.append(f'<line class="err" x1="{xl:.1f}" y1="{cy - 6:.1f}" x2="{xl:.1f}" y2="{cy + 6:.1f}" />')
            out.append(f'<line class="err" x1="{xh:.1f}" y1="{cy - 6:.1f}" x2="{xh:.1f}" y2="{cy + 6:.1f}" />')
        out.append(
            f'<text class="lbl" x="{left - 12}" y="{cy + 4:.1f}" text-anchor="end">{e(system)}</text>'
        )
        out.append(
            f'<text class="val" x="{left + plot_w + 42}" y="{cy + 4:.1f}" '
            f'text-anchor="end">{num(point)}</text>'
        )
        ci_text = (
            f"95% CI [{num(ci_lo)}, {num(ci_hi)}]"
            if ci_lo is not None and ci_hi is not None
            else "no interval"
        )
        out.append(
            f'<text class="band" x="{left + plot_w + 50}" y="{cy + 4:.1f}">{e(ci_text)}</text>'
        )
        out.append(
            f'<text class="tick" x="{left - 12}" y="{cy + 16:.1f}" text-anchor="end">'
            f'n={e(intg(get(stats, "n_items")))} items</text>'
        )

    axis_y = top + row_h * len(systems) + 10
    out.append(f'<line class="axis" x1="{left}" y1="{axis_y}" x2="{left + plot_w}" y2="{axis_y}" />')
    tick = 0.0
    while tick <= hi + 1e-9:
        x = X(tick)
        out.append(f'<line class="axis" x1="{x:.1f}" y1="{axis_y}" x2="{x:.1f}" y2="{axis_y + 4}" />')
        out.append(
            f'<text class="tick" x="{x:.1f}" y="{axis_y + 16}" text-anchor="middle">{num(tick, 2)}</text>'
        )
        tick += 0.25
    out.append(
        f'<text class="tick" x="{left + plot_w / 2:.1f}" y="{axis_y + 32}" '
        f'text-anchor="middle">mean composite (0-1)</text>'
    )
    out.append("</svg>")
    return "\n".join(out)


def svg_marginal_bars(factor: str, levels: dict, thin_names: Sequence[str]) -> str:
    """Small bar rows: item count per level of one stratification factor."""
    items = sorted(levels.items(), key=lambda kv: -float(kv[1] or 0))
    if not items:
        return ""
    width, left, right = 520, 186, 66
    top, row_h, bottom = 6, 21, 6
    plot_w = width - left - right
    height = top + row_h * len(items) + bottom
    biggest = max(1.0, max(float(v or 0) for _, v in items))

    thin_set = {str(t) for t in (thin_names or [])}
    out = _svg_open(width, height, f"Item count by {factor} level")
    for i, (level, count) in enumerate(items):
        y = top + i * row_h
        w = max(1.0, float(count or 0) / biggest * plot_w)
        marker = f"{factor}={level}"
        flagged = any(marker in t or t == str(level) for t in thin_set)
        cls = "b-warn" if flagged else "bar-count"
        out.append(f'<rect class="track" x="{left}" y="{y + 4}" width="{plot_w}" height="12" rx="2" />')
        out.append(f'<rect class="{cls}" x="{left}" y="{y + 4}" width="{w:.1f}" height="12" rx="2" />')
        out.append(
            f'<text class="lbl" x="{left - 10}" y="{y + 14}" text-anchor="end">{e(level)}</text>'
        )
        suffix = " thin" if flagged else ""
        out.append(
            f'<text class="val" x="{width - 8}" y="{y + 14}" text-anchor="end">'
            f'{e(intg(count))}{e(suffix)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# HTML fragment builders
# --------------------------------------------------------------------------


def _collapsible(items: Iterable[str], dom_id: str, visible: int, noun: str) -> str:
    """Render <li> rows where anything past `visible` hides behind a toggle."""
    items = list(items)
    rows = []
    for i, markup in enumerate(items):
        attr = "" if i < visible else " data-collapsible-item"
        rows.append(f"<li{attr}>{markup}</li>")
    hidden = max(0, len(items) - visible)
    cls = " collapsed" if hidden else ""
    body = f'<ul class="tight{cls}" id="{e(dom_id)}">' + "".join(rows) + "</ul>"
    if hidden:
        body += (
            f'<div class="togglewrap"><button type="button" class="linkbtn" '
            f'data-toggle="{e(dom_id)}" aria-expanded="false" '
            f'data-label-more="Show all {len(items)} {e(noun)}" '
            f'data-label-less="Show fewer {e(noun)}">Show all {len(items)} {e(noun)}</button></div>'
        )
    return body


def _table(headers: Sequence[tuple[str, str]], rows: Sequence[str], caption: str = "") -> str:
    head = "".join(
        f'<th scope="col" class="{e(cls)}">{e(label)}</th>' for label, cls in headers
    )
    cap = f"<caption>{e(caption)}</caption>" if caption else ""
    return (
        '<div class="tablewrap"><table>'
        + cap
        + f"<thead><tr>{head}</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def build_overview(data: dict, track_keys: Sequence[str]) -> str:
    summary = data.get("summary", {}) or {}
    tracks = data.get("tracks", {}) or {}

    stats = [
        ("tracks", intg(summary.get("n_tracks", len(tracks))), "evaluation programmes"),
        ("items", intg(summary.get("n_items")), "distinct task items"),
        ("responses", intg(summary.get("n_responses")), "system outputs scored"),
        ("annotations", intg(summary.get("n_annotations")), "rubric judgements"),
        ("dimensions", intg(summary.get("n_dimensions")), "rubric dimensions"),
        ("failure codes", intg(summary.get("n_failure_codes")), "taxonomy entries"),
    ]
    stat_html = "".join(
        f'<div class="stat"><div class="k">{e(k)}</div><div class="v">{v}</div>'
        f'<div class="sub">{e(sub)}</div></div>'
        for k, v, sub in stats
    )

    cards = []
    for key in track_keys:
        track = tracks[key]
        gate_counts = get(track, "gate", "summary", "by_verdict", default={}) or {}
        depth = str(track.get("depth", "") or "")
        verdicts = "".join(
            f'<span class="pill pill-{v}">{e(v)} {intg(gate_counts.get(v, 0))}</span>'
            for v in ("pass", "warn", "block")
        )
        cards.append(
            f'<button type="button" class="trackcard" data-goto-tab="tab-{e(key)}">'
            f'<div class="cardtop"><div><div class="tname">{e(track.get("name", key))}</div>'
            f'<div class="tkey">{e(key)} &middot; {e(track.get("rubric_version", _MISSING))}</div></div>'
            f'<span class="badge badge-depth-{e(slug(depth))}">{e(depth or _MISSING)}</span></div>'
            f'<div class="kvgrid">'
            f'<div class="kv"><div class="k">mean alpha</div><div class="v">{num(track.get("alpha_mean"))}</div></div>'
            f'<div class="kv"><div class="k">worst alpha</div><div class="v">{num(track.get("alpha_min"))}</div></div>'
            f'<div class="kv"><div class="k">gold accuracy</div><div class="v">{pct(track.get("gold_accuracy"), 1)}</div></div>'
            f'<div class="kv"><div class="k">items / resp.</div><div class="v">{e(intg(track.get("n_items")))}/{e(intg(track.get("n_responses")))}</div></div>'
            f"</div>"
            f'<div class="verdictbar">{verdicts}</div>'
            f'<div class="verdictbar">{rec_pill(get(track, "decision", "recommendation", default=""), large=True)}</div>'
            f'<div class="cardcta">Open track detail &rarr;</div>'
            f"</button>"
        )

    alpha_rows = []
    for key in track_keys:
        track = tracks[key]
        alpha = track.get("alpha_mean")
        cls, band = alpha_band(alpha if alpha is None else float(alpha))
        blind = get(data, "summary", "blind_spots_by_track", default={}).get(key, []) or []
        alpha_rows.append(
            f"<tr><td>{e(track.get('name', key))}<div class='tiny muted mono'>{e(key)}</div></td>"
            f'<td><span class="badge badge-depth-{e(slug(track.get("depth", "")))}">{e(track.get("depth", _MISSING))}</span></td>'
            f'<td class="n">{num(alpha)}</td>'
            f'<td><span class="pill pill-{e(cls)}">{e(band)}</span></td>'
            f'<td class="n">{pct(track.get("gold_accuracy"), 1)}</td>'
            f'<td class="n">{num(track.get("mean_replication"), 2)}</td>'
            f'<td>{rec_pill(get(track, "decision", "recommendation", default=""))}</td>'
            f'<td class="small dim">{e(", ".join(blind)) if blind else "none"}</td></tr>'
        )

    table = _table(
        [
            ("track", ""),
            ("depth", ""),
            ("mean alpha", "n"),
            ("reliability band", ""),
            ("gold acc.", "n"),
            ("replication", "n"),
            ("recommendation", ""),
            ("detection blind spots", ""),
        ],
        alpha_rows,
        caption="One row per track. Reliability band is derived from mean alpha against the "
        "0.50 / 0.667 / 0.80 policy thresholds.",
    )

    return f"""
<section class="block">
  <h2>Portfolio overview</h2>
  <p class="lede">Four rubric-based evaluation tracks, each with its own depth contract. A track's
  depth contract fixes what may be claimed on it; the signal gate then decides, claim by claim,
  whether the measurement actually supports the claim.</p>
  <div class="statrow">{stat_html}</div>
</section>

<section class="block">
  <h3>Tracks</h3>
  <p class="lede small">Select a card to open the full track detail.</p>
  <div class="cards">{''.join(cards)}</div>
</section>

<section class="block">
  <h3>Side-by-side</h3>
  {table}
</section>
"""


def build_ledger(data: dict, track_keys: Sequence[str]) -> str:
    summary = data.get("summary", {}) or {}
    tracks = data.get("tracks", {}) or {}
    submitted = summary.get("claims_submitted")
    blocked = summary.get("claims_blocked")
    rate = summary.get("block_rate")

    per_track = []
    for key in track_keys:
        gate = get(tracks[key], "gate", "summary", default={}) or {}
        counts = gate.get("by_verdict", {}) or {}
        per_track.append(
            f"<tr><td>{e(tracks[key].get('name', key))}<div class='tiny muted mono'>{e(key)}</div></td>"
            f'<td class="n">{intg(gate.get("n_claims"))}</td>'
            f'<td class="n">{intg(counts.get("pass", 0))}</td>'
            f'<td class="n">{intg(counts.get("warn", 0))}</td>'
            f'<td class="n">{intg(counts.get("block", 0))}</td>'
            f'<td class="n">{pct(gate.get("block_rate"), 1)}</td></tr>'
        )
    per_track_table = _table(
        [("track", ""), ("claims", "n"), ("pass", "n"), ("warn", "n"), ("block", "n"), ("block rate", "n")],
        per_track,
    )

    track_options = "".join(
        f'<option value="{e(k)}">{e(tracks[k].get("name", k))}</option>' for k in track_keys
    )

    return f"""
<section class="block">
  <h2>Signal gate ledger</h2>
  <p class="lede">Every claim the pipeline wanted to make, and what the gate did with it. A blocked
  claim is struck through and replaced, in place, by the reason it cannot be said. Nothing is
  silently dropped: the withheld claims stay on the page.</p>

  <div class="statrow">
    <div class="stat huge blockborder">
      <div class="k">aggregate block rate</div>
      <div class="v">{pct(rate, 1)}</div>
      <div class="sub">{intg(blocked)} of {intg(submitted)} submitted claims withheld</div>
    </div>
    <div class="stat"><div class="k">claims submitted</div><div class="v">{intg(submitted)}</div>
      <div class="sub">across {intg(summary.get("n_tracks", len(tracks)))} tracks</div></div>
    <div class="stat"><div class="k">claims blocked</div><div class="v">{intg(blocked)}</div>
      <div class="sub">reported as withheld, with reason</div></div>
    <div class="stat"><div class="k">claims cleared</div>
      <div class="v">{intg((submitted or 0) - (blocked or 0)) if submitted is not None and blocked is not None else _MISSING}</div>
      <div class="sub">pass or pass-with-caveat</div></div>
  </div>

  <div class="filters">
    <div class="field"><label for="f-verdict">verdict</label>
      <select id="f-verdict">
        <option value="all">all verdicts</option>
        <option value="block">block</option>
        <option value="warn">warn</option>
        <option value="pass">pass</option>
      </select></div>
    <div class="field"><label for="f-track">track</label>
      <select id="f-track"><option value="all">all tracks</option>{track_options}</select></div>
    <div class="field"><label for="f-text">search claim text</label>
      <input type="search" id="f-text" placeholder="e.g. reliable, ranking, citation" /></div>
    <div class="field"><label for="f-reset">&nbsp;</label>
      <button type="button" class="linkbtn" id="f-reset">Reset filters</button></div>
    <div class="filtercount" id="ledger-count" role="status" aria-live="polite"></div>
  </div>

  <noscript><div class="noscript">The claim ledger is built from the embedded JSON payload and
  needs JavaScript. Per-track claim counts are still shown below.</div></noscript>

  <div class="tablewrap"><table>
    <caption>Sorted block &rarr; warn &rarr; pass. Expand a row for the individual gate checks.</caption>
    <thead><tr>
      <th scope="col">track / claim id</th>
      <th scope="col">kind</th>
      <th scope="col">verdict</th>
      <th scope="col">claim</th>
      <th scope="col">detail</th>
    </tr></thead>
    <tbody id="ledger-body"></tbody>
  </table></div>
</section>

<section class="block">
  <h3>Block rate by track</h3>
  {per_track_table}
</section>
"""


def build_reliability(track: dict, key: str) -> str:
    agreement = track.get("agreement", {}) or {}
    contested = track.get("contested_dimensions", []) or []
    chart = svg_alpha_chart(agreement, contested)

    rows = []
    paradox_notes = []
    for dim, stats in sorted(
        agreement.items(),
        key=lambda kv: get(kv[1], "krippendorff_alpha", "value", default=-9),
        reverse=True,
    ):
        alpha = get(stats, "krippendorff_alpha", "value")
        cls, band = alpha_band(None if alpha is None else float(alpha))
        ci = stats.get("ci")
        # A band label is a classification against a threshold. When the
        # interval does not exclude that threshold, the label is a point
        # estimate and the reader has to be able to see it.
        ci_cell = f"[{num(ci.get('lo'))}, {num(ci.get('hi'))}]" if ci else _MISSING
        if ci and any(ci["lo"] <= t <= ci["hi"] for t in (0.50, 0.667, 0.80)):
            straddled = [t for t in (0.50, 0.667, 0.80) if ci["lo"] <= t <= ci["hi"]]
            ci_cell += (
                '<div class="tiny muted">does not exclude '
                + ", ".join(f"{t:.3f}" for t in straddled)
                + "</div>"
            )
        badges = []
        if dim in contested:
            badges.append('<span class="badge badge-contested">contested</span>')
        if stats.get("kappa_paradox_detected"):
            badges.append('<span class="badge badge-blind">kappa paradox</span>')
            paradox_notes.append(
                (dim, stats.get("paradox_note") or "High percent agreement with a low kappa: the "
                 "chance-corrected coefficient is deflated by skewed marginals.")
            )
        rows.append(
            f"<tr><td>{e(dim)} {' '.join(badges)}"
            f'<div class="tiny muted">{e(stats.get("interpretation", ""))}</div></td>'
            f'<td class="n">{num(alpha)}</td>'
            f'<td class="n">{ci_cell}</td>'
            f'<td><span class="pill pill-{e(cls)}">{e(band)}</span></td>'
            f'<td class="n">{num(get(stats, "percent_agreement", "value"))}</td>'
            f'<td class="n">{num(get(stats, "fleiss_kappa", "value"))}</td>'
            f'<td class="n">{num(get(stats, "gwet_ac1", "value"))}</td>'
            f'<td class="n">{intg(get(stats, "krippendorff_alpha", "n_units"))}</td>'
            f'<td class="small dim">{e(stats.get("scale", ""))}</td></tr>'
        )

    table = _table(
        [
            ("dimension", ""),
            ("Krippendorff alpha", "n"),
            ("95% CI", "n"),
            ("band", ""),
            ("% agreement", "n"),
            ("Fleiss kappa", "n"),
            ("Gwet AC1", "n"),
            ("units", "n"),
            ("scale", ""),
        ],
        rows,
        caption="Four coefficients side by side, all four using the same unit-averaged marginal "
        "so the kappa/AC1 gap reflects a difference in chance MODEL rather than in prevalence "
        "estimation. Where percent agreement is high but Fleiss kappa is low, the marginals are "
        "skewed and kappa is deflated - Gwet AC1 is the fairer read. The CI is a cluster "
        "bootstrap over responses; where it does not exclude a threshold, the band beside it is "
        "a point estimate and not an established classification.",
    )

    callouts = []
    for dim, note in paradox_notes:
        callouts.append(
            f'<div class="callout warn"><span class="ctitle">Kappa paradox: {e(dim)}</span>{e(note)}</div>'
        )
    if contested:
        callouts.append(
            '<div class="callout warn"><span class="ctitle">Contested dimensions</span>'
            + e(", ".join(contested))
            + ". These carry a stable annotator value-position component. Replication does not "
            "shrink that variance: more labels buy precision on a quantity that annotators "
            "genuinely disagree about.</div>"
        )

    rel = track.get("composite_reliability") or {}
    if rel.get("rho_1") is not None:
        ci1 = rel.get("ci_rho_1") or {}
        cik = rel.get("ci_rho_k") or {}
        k = rel.get("k_raters")
        callouts.append(
            '<div class="callout"><span class="ctitle">Reliability of the compared quantity'
            "</span>Every between-system comparison is made on the per-item mean of the "
            f"weighted composite over {intg(k)} annotators. Neither a single dimension's alpha "
            "nor the mean of them is the reliability of that quantity. The composite's own "
            f"single-rater interval alpha is rho_1 = {num(rel.get('rho_1'))} "
            f"[{num(ci1.get('lo'))}, {num(ci1.get('hi'))}]; Spearman-Brown for the "
            f"{intg(k)}-rater mean gives rho_k = {num(rel.get('rho_k'))} "
            f"[{num(cik.get('lo'))}, {num(cik.get('hi'))}]. rho_k is what the power "
            "calculation consumes.</div>"
        )

    drift = track.get("drift", {}) or {}
    triage = get(track, "triage", "summary", default={}) or {}
    gaps = track.get("rubric_gaps", {}) or {}
    process = f"""
    <div class="statrow">
      <div class="stat"><div class="k">batch drift</div>
        <div class="v">{'detected' if drift.get('drift_detected') else 'none'}</div>
        <div class="sub">{e(drift.get('verdict', _MISSING))}</div></div>
      <div class="stat"><div class="k">adjudication queue</div>
        <div class="v">{pct(triage.get('queue_rate'), 1)}</div>
        <div class="sub">{intg(triage.get('n_queued'))} queued / {intg(triage.get('n_resolved'))} resolved</div></div>
      <div class="stat"><div class="k">rubric gap rate</div>
        <div class="v">{pct(gaps.get('rubric_gap_rate'), 1)}</div>
        <div class="sub">budget {pct(gaps.get('threshold'), 0)}; {intg(gaps.get('n_rubric_gaps'))} of {intg(gaps.get('n_adjudicated'))} adjudications</div></div>
      <div class="stat"><div class="k">mean replication</div>
        <div class="v">{num(track.get('mean_replication'), 2)}</div>
        <div class="sub">annotations per response</div></div>
    </div>"""

    return f"""
<section class="block">
  <h3>Reliability</h3>
  <p class="lede small">Krippendorff's alpha per dimension against the policy thresholds:
  below 0.50 blocks a claim, 0.667 is the floor for tentative conclusions, 0.80 supports firm ones.</p>
  <figure class="chart">
    <figcaption>Inter-annotator agreement by dimension, mean alpha {num(track.get('alpha_mean'))},
    worst dimension {num(track.get('alpha_min'))}.</figcaption>
    {chart}
  </figure>
  <div class="stack" style="margin-top:16px">
    {''.join(callouts)}
    {table}
  </div>
  <h4 style="margin-top:22px">Process integrity</h4>
  {process}
</section>
"""


def build_scores(track: dict) -> str:
    scores = track.get("scores", {}) or {}
    comparison = track.get("comparison", {}) or {}
    comparisons = comparison.get("comparisons", {}) or {}
    multiplicity = comparison.get("multiplicity", {}) or {}

    rows = []
    for name, cmp_ in sorted(comparisons.items()):
        power = cmp_.get("power", {}) or {}
        ci = cmp_.get("ci", {}) or {}
        perm = cmp_.get("permutation_test", {}) or {}
        exceeds = bool(cmp_.get("exceeds_mde"))
        verdict = (
            '<span class="pill pill-pass">yes - resolvable</span>'
            if exceeds
            else '<span class="pill pill-block">no - inside noise floor</span>'
        )
        notes = power.get("notes", []) or []
        note_html = (
            f'<div class="tiny muted">{e(" ".join(notes))}</div>' if notes else ""
        )
        rows.append(
            f"<tr><td><div class='mono small'>{e(cmp_.get('system', ''))}</div>"
            f"<div class='tiny muted'>vs {e(cmp_.get('reference', ''))}</div></td>"
            f'<td class="n">{num(cmp_.get("mean_difference"))}</td>'
            f'<td class="n">[{num(ci.get("lo"))}, {num(ci.get("hi"))}]</td>'
            f'<td class="mde n">{num(power.get("mde_observed_scale"))}</td>'
            f'<td class="n">{num(power.get("mde_true_scale"))}</td>'
            f"<td>{verdict}{note_html}</td>"
            f'<td class="n">{num(perm.get("p_value"), 4)}</td>'
            f'<td class="n">{num(power.get("n_effective"), 1)}</td>'
            f'<td class="n">{intg(power.get("n_required_for_target"))}</td></tr>'
        )

    cmp_table = _table(
        [
            ("contrast", ""),
            ("effect", "n"),
            ("95% CI", "n"),
            ("MDE (observed)", "mde n"),
            ("MDE (true-score)", "n"),
            ("exceeds MDE?", ""),
            ("perm. p", "n"),
            ("n effective", "n"),
            ("n for 0.05", "n"),
        ],
        rows,
        caption="MDE is the smallest OBSERVED difference this design can resolve at 80% power, "
        "computed at plain n against the observed SD of the paired differences -- the scale the "
        "effect column is on. The reliability correction is not applied here as well: the "
        "observed SD already contains the measurement error, so shrinking n to n_effective on "
        "top of it would charge for that error twice. n_effective is shown as an interpretive "
        "figure only. An effect below the MDE is inside the noise floor regardless of its "
        "p-value.",
    )

    mult = ""
    if multiplicity:
        mult = (
            '<div class="callout"><span class="ctitle">Multiplicity</span>'
            f'{intg(multiplicity.get("n_tests"))} pre-registered test(s); uncorrected alpha '
            f'{num(multiplicity.get("uncorrected"), 3)}, Bonferroni '
            f'{num(multiplicity.get("bonferroni"), 3)}, Benjamini-Hochberg thresholds '
            f'{num(multiplicity.get("bh_smallest_threshold"), 3)} to '
            f'{num(multiplicity.get("bh_largest_threshold"), 3)}. Expected false positives if '
            f'uncorrected: {num(multiplicity.get("expected_false_positives_uncorrected"), 2)}.</div>'
        )

    return f"""
<section class="block">
  <h3>Scores and system comparison</h3>
  <p class="lede small">Point estimates carry cluster-bootstrap intervals over items. The decisive
  column below is not the p-value but the MDE.</p>
  <figure class="chart">
    <figcaption>Mean composite by system, 95% cluster-bootstrap CI.</figcaption>
    {svg_score_chart(scores)}
  </figure>
  <div class="stack" style="margin-top:16px">
    {cmp_table}
    {mult}
  </div>
</section>
"""


def build_taxonomy(track: dict, key: str) -> str:
    sensitivity = track.get("sensitivity", {}) or {}
    codes = sensitivity.get("codes", []) or []
    blind = {str(c) for c in (sensitivity.get("blind_spot_codes", []) or [])}

    def sort_key(code: dict) -> tuple:
        return (0 if str(code.get("code")) in blind else 1, -float(code.get("n_planted") or 0))

    rows = []
    for code in sorted(codes, key=sort_key):
        cid = str(code.get("code", ""))
        is_blind = cid in blind
        detected = code.get("detected")
        detect_cell = (
            '<span class="pill pill-pass">yes</span>'
            if detected
            else (
                '<span class="pill pill-block">no - blind spot</span>'
                if is_blind
                else '<span class="pill pill-warn">not estimable</span>'
            )
        )
        badge = ' <span class="badge badge-blind">blind spot</span>' if is_blind else ""
        rows.append(
            f'<tr class="{"rowflag-blind" if is_blind else ""}">'
            f'<td class="code">{e(cid)}{badge}</td>'
            f'<td class="small dim">{e(code.get("description", ""))}'
            f'<div class="tiny muted">{e(code.get("diagnosis", ""))}</div></td>'
            f'<td class="n">{intg(code.get("n_planted"))}</td>'
            f'<td class="n">{num(code.get("best_delta"))}</td>'
            f'<td class="small dim">{e(code.get("best_dimension", ""))}</td>'
            f"<td>{detect_cell}</td>"
            f'<td class="n">{num(code.get("coder_recall"), 2)}</td>'
            f'<td class="n">{num(code.get("coder_precision"), 2)}</td></tr>'
        )

    body = "".join(rows)
    dom_id = f"codes-{slug(key)}"
    visible = 8
    hidden = max(0, len(rows) - visible)
    if hidden:
        shown = "".join(rows[:visible])
        rest = "".join(
            row.replace("<tr ", "<tr data-collapsible-item ", 1)
            if row.startswith("<tr ")
            else row.replace("<tr", "<tr data-collapsible-item", 1)
            for row in rows[visible:]
        )
        body = shown + rest

    table = (
        '<div class="tablewrap"><table'
        + (f' id="{e(dom_id)}" class="collapsed"' if hidden else "")
        + "><caption>Cliff's delta compares scores on responses carrying the planted code against "
        "clean responses. Codes with fewer than four planted instances are reported as "
        "underpowered, not undetected.</caption><thead><tr>"
        + "".join(
            f'<th scope="col" class="{cls}">{e(label)}</th>'
            for label, cls in [
                ("code", ""),
                ("failure mode", ""),
                ("planted", "n"),
                ("best delta", "n"),
                ("best dimension", ""),
                ("detected", ""),
                ("coder recall", "n"),
                ("coder precision", "n"),
            ]
        )
        + "</tr></thead><tbody>"
        + body
        + "</tbody></table></div>"
    )
    if hidden:
        table += (
            f'<div class="togglewrap"><button type="button" class="linkbtn" '
            f'data-toggle="{e(dom_id)}" aria-expanded="false" '
            f'data-label-more="Show all {len(rows)} failure codes" '
            f'data-label-less="Show fewer failure codes">Show all {len(rows)} failure codes</button></div>'
        )

    blind_callout = ""
    if blind:
        blind_callout = (
            '<div class="callout block"><span class="ctitle">Detection blind spots</span>'
            + e(", ".join(sorted(blind)))
            + ". These failure modes were planted in sufficient numbers and the rubric still did "
            "not move. Any claim of the form \"the systems do not exhibit this failure\" is "
            "unsupportable on this instrument.</div>"
        )
    else:
        blind_callout = (
            '<div class="callout pass"><span class="ctitle">No blind spots</span>'
            "Every estimable planted failure mode registered on at least one dimension.</div>"
        )

    return f"""
<section class="block">
  <h3>Failure taxonomy and detection sensitivity</h3>
  <div class="statrow">
    <div class="stat"><div class="k">codes in taxonomy</div><div class="v">{intg(sensitivity.get("n_codes"))}</div>
      <div class="sub">{intg(sensitivity.get("n_estimable"))} estimable at this n</div></div>
    <div class="stat"><div class="k">sensitivity rate</div><div class="v">{pct(sensitivity.get("sensitivity_rate"), 0)}</div>
      <div class="sub">{intg(sensitivity.get("n_detected"))} detected of {intg(sensitivity.get("n_estimable"))} estimable</div></div>
    <div class="stat"><div class="k">blind spots</div><div class="v">{intg(sensitivity.get("n_blind_spots"))}</div>
      <div class="sub">planted, powered, and missed</div></div>
    <div class="stat"><div class="k">mean coder recall</div><div class="v">{num(sensitivity.get("mean_coder_recall"), 2)}</div>
      <div class="sub">taxonomy coder vs planted ground truth</div></div>
  </div>
  <div class="stack" style="margin-top:16px">
    {blind_callout}
    {table}
  </div>
</section>
"""


def build_coverage(track: dict) -> str:
    coverage = track.get("coverage", {}) or {}
    marginals = coverage.get("marginals", {}) or {}
    thin = coverage.get("thin_levels", []) or []
    absent = coverage.get("absent_levels", []) or []
    failure_rates = coverage.get("failure_rate_by_stratum", {}) or {}
    balance = coverage.get("balance_ratio_by_factor", {}) or {}

    blocks = []
    for factor, levels in sorted(marginals.items()):
        rates = failure_rates.get(factor, {}) or {}
        rate_rows = "".join(
            f"<tr><td>{e(level)}</td><td class='n'>{intg(levels.get(level))}</td>"
            f"<td class='n'>{pct(rate, 1)}</td></tr>"
            for level, rate in sorted(rates.items(), key=lambda kv: -float(kv[1] or 0))
        )
        rate_table = (
            "<table class='small'><thead><tr><th scope='col'>level</th>"
            "<th scope='col' class='n'>items</th><th scope='col' class='n'>failure rate</th>"
            f"</tr></thead><tbody>{rate_rows}</tbody></table>"
            if rate_rows
            else ""
        )
        blocks.append(
            f'<div class="panelbox"><h3>{e(factor)}</h3>'
            f'<div class="tiny muted" style="margin-bottom:8px">balance ratio '
            f"{num(balance.get(factor), 2)} (1.00 is perfectly balanced)</div>"
            f"{svg_marginal_bars(factor, levels, thin)}"
            f'<div style="margin-top:10px">{rate_table}</div></div>'
        )

    notes = []
    if absent:
        notes.append(
            '<div class="callout block"><span class="ctitle">Absent levels</span>'
            + e(", ".join(str(a) for a in absent))
            + ". Absent levels are silently excluded from every aggregate, so they are named here "
            "rather than left to be inferred.</div>"
        )
    if thin:
        notes.append(
            '<div class="callout warn"><span class="ctitle">Thin levels</span>'
            + e("; ".join(str(t) for t in thin))
            + ". Below the minimum cell size; any subgroup statement resting on these is "
            "unsupported.</div>"
        )
    if not absent and not thin:
        notes.append(
            '<div class="callout pass"><span class="ctitle">Marginal coverage complete</span>'
            "Every declared stratum level is populated above the minimum cell size.</div>"
        )
    interpretation = coverage.get("interpretation")
    if interpretation:
        notes.append(
            f'<div class="callout"><span class="ctitle">Reading the coverage figure</span>{e(interpretation)}</div>'
        )

    return f"""
<section class="block">
  <h3>Coverage</h3>
  <div class="statrow">
    <div class="stat"><div class="k">marginal gap</div><div class="v">{pct(coverage.get("marginal_gap_fraction"), 1)}</div>
      <div class="sub">{intg(len(thin) + len(absent))} of {intg(coverage.get("total_declared_levels"))} declared levels thin or absent</div></div>
    <div class="stat"><div class="k">full-factorial cells</div>
      <div class="v">{intg(coverage.get("populated_cells"))}/{intg(coverage.get("designed_cells"))}</div>
      <div class="sub">{pct(coverage.get("empty_cell_fraction"), 0)} empty by construction</div></div>
    <div class="stat"><div class="k">worst balance ratio</div><div class="v">{num(coverage.get("worst_balance_ratio"), 2)}</div>
      <div class="sub">smallest / largest level within a factor</div></div>
    <div class="stat"><div class="k">items</div><div class="v">{intg(coverage.get("n_items"))}</div>
      <div class="sub">across {intg(len(coverage.get("factors", {}) or {}))} design factors</div></div>
  </div>
  <div class="stack" style="margin-top:16px">{''.join(notes)}</div>
  <div class="covergrid" style="margin-top:18px">{''.join(blocks)}</div>
</section>
"""


def build_annotators(track: dict) -> str:
    pool = track.get("annotator_pool", {}) or {}
    annotators = pool.get("annotators", []) or []
    rows = []
    for ann in annotators:
        flags = ann.get("flags", []) or []
        positions = ann.get("positions", []) or []
        bias = ann.get("bias_vs_pool", ann.get("bias"))
        gold = ann.get("gold_exact", ann.get("gold_accuracy"))
        flag_html = (
            " ".join(f'<span class="badge badge-blind">{e(f)}</span>' for f in flags)
            if flags
            else '<span class="pill pill-pass">clear</span>'
        )
        # Rendered alongside the flags but visually distinct, because a value
        # position on a contested dimension is not a quality defect.
        flag_html += "".join(
            f' <span class="pill pill-warn" title="Value position on contested '
            f'dimensions -- not a quality defect">{e(p)}</span>' for p in positions
        )
        gold_cls = "block" if (gold is not None and float(gold) < 0.70) else "pass"
        rows.append(
            f'<tr><td class="code">{e(ann.get("annotator_id", ""))}</td>'
            f'<td class="n">{num(bias, 3)}</td>'
            f'<td class="n"><span class="pill pill-{gold_cls}">{pct(gold, 1)}</span></td>'
            f'<td class="n">{pct(ann.get("gold_within_one"), 1)}</td>'
            f'<td class="n">{num(ann.get("mean_duration_s"), 1)}</td>'
            f'<td class="n">{num(ann.get("mean_score"), 2)}</td>'
            f'<td class="n">{intg(ann.get("n_annotations"))}</td>'
            f"<td>{flag_html}</td></tr>"
        )
    table = _table(
        [
            ("annotator", ""),
            ("bias vs pool", "n"),
            ("gold exact", "n"),
            ("gold within 1", "n"),
            ("mean duration (s)", "n"),
            ("mean score", "n"),
            ("labels", "n"),
            ("flags / positions", ""),
        ],
        rows,
        caption="Bias is the signed offset in rubric points relative to the pool mean over ALL "
        "dimensions. The systematic_bias flag is raised on the NON-contested dimensions only, so "
        "it measures leniency rather than value position; a contested_position badge is a stance "
        "on the contested dimensions and is not a quality defect. Gold exact is agreement with "
        "adjudicated anchor items.",
    )
    flagged = pool.get("flagged_annotators", []) or []
    callout = ""
    if flagged:
        callout = (
            '<div class="callout warn"><span class="ctitle">Flagged annotators</span>'
            + e(", ".join(flagged))
            + f" &mdash; {pct(pool.get('flagged_fraction'), 1)} of the pool. Flagged labels are "
            "retained in the headline figures; removing them post hoc would make the reliability "
            "estimate optimistic.</div>"
        )
    return f"""
<section class="block">
  <h3>Annotator pool</h3>
  <p class="lede small">Pool mean score {num(pool.get('pool_mean'), 3)} across
  {intg(pool.get('n_annotators'))} annotators.</p>
  <div class="stack">{callout}{table}</div>
</section>
"""


def build_redteam(track: dict) -> str:
    redteam = track.get("redteam", {}) or {}
    probes = redteam.get("probes", []) or []
    items = []
    for probe in probes:
        failed = bool(probe.get("failed"))
        pill = (
            '<span class="pill pill-block">fail</span>'
            if failed
            else '<span class="pill pill-pass">pass</span>'
        )
        items.append(
            f'<div class="probe"><div>{pill}</div><div>'
            f'<div class="pname">{e(probe.get("probe", ""))}</div>'
            f'<div class="pinterp">{e(probe.get("interpretation", ""))}</div>'
            f'<div class="pstat">statistic {num(probe.get("statistic"))} '
            f'&middot; tolerance {num(probe.get("threshold"))}</div></div></div>'
        )
    verdict = redteam.get("verdict", "")
    failed_probes = redteam.get("failed_probes", []) or []
    callout = (
        f'<div class="callout block"><span class="ctitle">Red-team verdict</span>{e(verdict)}</div>'
        if failed_probes
        else f'<div class="callout pass"><span class="ctitle">Red-team verdict</span>{e(verdict or "All probes within tolerance.")}</div>'
    )
    return f"""
<section class="block">
  <h3>Red-team probes</h3>
  <p class="lede small">Adversarial checks on the instrument itself: can the score be produced
  without reading the response, and does it survive perturbation?
  {intg(redteam.get("n_failed"))} of {intg(redteam.get("n_probes"))} probes failed.</p>
  <div class="stack">{callout}<div class="panelbox">{''.join(items)}</div></div>
</section>
"""


def build_decision(track: dict, key: str) -> str:
    decision = track.get("decision", {}) or {}
    rec = decision.get("recommendation", "")
    rationale = decision.get("rationale", []) or []
    actions = decision.get("next_actions", []) or []
    stop = decision.get("stop_criteria", []) or []
    investment = track.get("investment", []) or []
    cost = decision.get("projected_cost_to_fix_usd")

    invest_html = (
        _collapsible([e(i) for i in investment], f"invest-{slug(key)}", 5, "priorities")
        if investment
        else '<p class="muted small">No investment priorities recorded.</p>'
    )

    return f"""
<section class="block">
  <h3>Decision</h3>
  <div class="panelbox">
    <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap">
      {rec_pill(rec, large=True)}
      <div style="font-size:1.05rem; font-weight:620">{e(decision.get("headline", ""))}</div>
    </div>
    <dl class="deflist" style="margin-top:16px">
      <dt>irreducible share</dt>
      <dd>{pct(decision.get("irreducible_share"), 1)} of the disagreement is value-position variance
      that replication cannot reduce.</dd>
      <dt>cost to fix</dt>
      <dd>{('$' + num(cost, 2)) if cost is not None else 'not estimated'}</dd>
    </dl>
  </div>
  <div class="grid2" style="margin-top:18px">
    <div class="panelbox"><h3>Rationale</h3>
      <ul class="tight">{''.join(f'<li>{e(r)}</li>' for r in rationale) or '<li class="muted">none recorded</li>'}</ul>
    </div>
    <div class="panelbox"><h3>Next actions</h3>
      <ol class="tight">{''.join(f'<li>{e(a)}</li>' for a in actions) or '<li class="muted">none recorded</li>'}</ol>
    </div>
    <div class="panelbox"><h3>Stop criteria</h3>
      <ul class="tight">{''.join(f'<li>{e(s)}</li>' for s in stop) or '<li class="muted">none recorded</li>'}</ul>
    </div>
    <div class="panelbox"><h3>Investment priorities</h3>{invest_html}</div>
  </div>
</section>
"""


def build_track_panel(track: dict, key: str) -> str:
    depth = str(track.get("depth", "") or "")
    gate_summary = get(track, "gate", "summary", default={}) or {}
    counts = gate_summary.get("by_verdict", {}) or {}
    limitations = track.get("known_limitations", []) or []

    header = f"""
<section class="block">
  <div class="brandrow" style="gap:12px">
    <h2>{e(track.get('name', key))}</h2>
    <span class="badge badge-depth-{e(slug(depth))}">{e(depth or _MISSING)}</span>
    {rec_pill(get(track, 'decision', 'recommendation', default=''))}
  </div>
  <p class="lede" style="margin-top:10px">{e(track.get('research_question', ''))}</p>
  <dl class="deflist">
    <dt>depth contract</dt><dd>{e(track.get('depth_contract', _MISSING))}</dd>
    <dt>unit of analysis</dt><dd>{e(track.get('unit_of_analysis', _MISSING))}</dd>
    <dt>rubric version</dt><dd class="mono small">{e(track.get('rubric_version', _MISSING))}</dd>
  </dl>
  <div class="statrow" style="margin-top:18px">
    <div class="stat accentborder"><div class="k">mean alpha</div><div class="v">{num(track.get('alpha_mean'))}</div>
      <div class="sub">worst dimension {num(track.get('alpha_min'))}</div></div>
    <div class="stat"><div class="k">gold accuracy</div><div class="v">{pct(track.get('gold_accuracy'), 1)}</div>
      <div class="sub">pool vs adjudicated anchors</div></div>
    <div class="stat"><div class="k">items / responses</div>
      <div class="v">{intg(track.get('n_items'))}/{intg(track.get('n_responses'))}</div>
      <div class="sub">{intg(track.get('n_annotations'))} annotations</div></div>
    <div class="stat blockborder"><div class="k">claims blocked</div>
      <div class="v">{intg(counts.get('block', 0))}/{intg(gate_summary.get('n_claims'))}</div>
      <div class="sub">block rate {pct(gate_summary.get('block_rate'), 1)}</div></div>
  </div>
</section>
"""

    limits = f"""
<section class="block">
  <h3>Known limitations</h3>
  {_collapsible([e(l) for l in limitations], f"limits-{slug(key)}", 2, "limitations")
   if limitations else '<p class="muted small">No limitations recorded.</p>'}
</section>
"""

    return (
        header
        + build_reliability(track, key)
        + build_scores(track)
        + build_taxonomy(track, key)
        + build_coverage(track)
        + build_annotators(track)
        + build_redteam(track)
        + build_decision(track, key)
        + limits
    )


def build_methods(data: dict, track_keys: Sequence[str]) -> str:
    summary = data.get("summary", {}) or {}
    tracks = data.get("tracks", {}) or {}
    notice = summary.get("simulation_notice", "")

    limit_blocks = []
    for key in track_keys:
        track = tracks[key]
        limitations = track.get("known_limitations", []) or []
        limit_blocks.append(
            f'<div class="panelbox"><h3>{e(track.get("name", key))}</h3>'
            f'<div class="tiny muted mono" style="margin-bottom:8px">{e(key)} &middot; '
            f'{e(track.get("depth", ""))} &middot; {e(track.get("rubric_version", ""))}</div>'
            + (
                _collapsible([e(l) for l in limitations], f"mlimits-{slug(key)}", 2, "limitations")
                if limitations
                else '<p class="muted small">No limitations recorded.</p>'
            )
            + "</div>"
        )

    pool = summary.get("annotator_pool", {}) or {}
    traits = pool.get("trait_definitions", {}) or {}
    trait_rows = "".join(
        f"<tr><td class='code'>{e(k)}</td><td class='small dim'>{e(v)}</td></tr>"
        for k, v in sorted(traits.items())
    )
    trait_table = (
        _table([("trait", ""), ("definition", "")], [trait_rows], caption="")
        if trait_rows
        else ""
    )

    sim_annotators = pool.get("annotators", []) or []
    sim_rows = "".join(
        f'<tr><td class="code">{e(a.get("annotator_id", ""))}</td>'
        f'<td class="n">{num(a.get("bias"), 2)}</td>'
        f'<td class="n">{num(a.get("competence"), 2)}</td>'
        f'<td class="n">{num(a.get("fatigue_rate"), 3)}</td>'
        f'<td class="n">{num(a.get("speed_factor"), 2)}</td>'
        f'<td class="n">{num(a.get("value_position"), 2)}</td></tr>'
        for a in sim_annotators
    )
    sim_table = _table(
        [
            ("simulated annotator", ""),
            ("bias", "n"),
            ("competence", "n"),
            ("fatigue rate", "n"),
            ("speed factor", "n"),
            ("value position", "n"),
        ],
        [sim_rows],
        caption="Generative parameters of the annotator model. These are inputs, not measurements.",
    ) if sim_rows else ""

    # gate policy: show once if identical across tracks, otherwise per track
    policies = {}
    for key in track_keys:
        policy = get(tracks[key], "gate", "policy", default={}) or {}
        policies.setdefault(json.dumps(policy, sort_keys=True), []).append(key)
    policy_blocks = []
    for policy_json, keys in policies.items():
        policy = json.loads(policy_json)
        rows = "".join(
            f"<tr><td class='code'>{e(k)}</td><td class='n'>{e(v)}</td></tr>"
            for k, v in sorted(policy.items())
        )
        title = "Signal-gate policy" if len(policies) == 1 else f"Signal-gate policy ({', '.join(keys)})"
        policy_blocks.append(
            f"<h3 style='margin-top:20px'>{e(title)}</h3>"
            + _table([("threshold", ""), ("value", "n")], [rows])
        )

    return f"""
<section class="block">
  <h2>Methods and limitations</h2>
  <p class="lede">What this instrument is, what it is not, and where its edges are. The limitations
  below are copied verbatim from each track's own record; they were written before the results
  were read.</p>
  <div class="simbanner" role="note" aria-label="Simulation notice">
    <div class="simhead"><span class="mark">SIM</span><span>Simulated annotators &mdash; not an empirical finding</span></div>
    <div class="simbody">{e(notice)}</div>
  </div>
</section>

<section class="block">
  <h3>Per-track limitations</h3>
  <div class="grid2">{''.join(limit_blocks)}</div>
</section>

<section class="block">
  <h3>The annotator model</h3>
  <p class="lede small">{e(pool.get("notice", ""))}</p>
  <div class="stack">{trait_table}{sim_table}</div>
</section>

<section class="block">
  {''.join(policy_blocks)}
</section>
"""


# --------------------------------------------------------------------------
# document assembly
# --------------------------------------------------------------------------


def _embed_json(data: dict) -> str:
    """Serialise the payload so it can never terminate the host <script> tag."""
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _track_order(tracks: dict) -> list[str]:
    def key(name: str) -> tuple:
        depth = str(tracks[name].get("depth", "") or "")
        rank = DEPTH_ORDER.index(depth) if depth in DEPTH_ORDER else len(DEPTH_ORDER)
        return (-rank, name)

    return sorted(tracks.keys(), key=key)


def render_dashboard(data: dict, out_path: Path) -> Path:
    """Render the full interactive dashboard to ``out_path``. Returns the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    summary = (data or {}).get("summary", {}) or {}
    tracks = (data or {}).get("tracks", {}) or {}
    track_keys = _track_order(tracks)

    notice = summary.get("simulation_notice") or (
        "No simulation notice was recorded in the portfolio payload."
    )

    # (key, short tab label, full accessible name)
    tab_defs: list[tuple[str, str, str]] = [
        ("overview", "Portfolio overview", "Portfolio overview"),
        ("gate", "Signal gate ledger", "Signal gate ledger"),
    ]
    tab_defs += [
        (key, str(key).replace("_", " ").title(), tracks[key].get("name", key))
        for key in track_keys
    ]
    tab_defs.append(("methods", "Methods", "Methods and limitations"))

    tab_buttons = []
    for i, (key, label, full) in enumerate(tab_defs):
        selected = "true" if i == 0 else "false"
        tabindex = "0" if i == 0 else "-1"
        tab_buttons.append(
            f'<button type="button" role="tab" id="tab-{e(key)}" '
            f'aria-controls="panel-{e(key)}" aria-selected="{selected}" tabindex="{tabindex}" '
            f'aria-label="{e(full)}">{e(label)}</button>'
        )

    panels = {
        "overview": build_overview(data, track_keys),
        "gate": build_ledger(data, track_keys),
        "methods": build_methods(data, track_keys),
    }
    for key in track_keys:
        panels[key] = build_track_panel(tracks[key], key)

    panel_html = []
    for i, (key, label, full) in enumerate(tab_defs):
        hidden = "" if i == 0 else " hidden"
        panel_html.append(
            f'<div class="panel wrap" role="tabpanel" id="panel-{e(key)}" '
            f'aria-labelledby="tab-{e(key)}" tabindex="0"{hidden}>{panels[key]}</div>'
        )

    rec_counts = summary.get("recommendations", {}) or {}
    rec_strip = " &middot; ".join(
        f"{e(k)}: <b>{e(v)}</b>" for k, v in sorted(rec_counts.items())
    )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Rubricon &mdash; evaluation portfolio dashboard</title>
<meta name="description" content="Rubricon: rubric reliability, signal gating and decision ledger across four evaluation tracks. Simulated annotators." />
<style>{CSS}</style>
</head>
<body>
<a class="skiplink" href="#panel-overview">Skip to content</a>

<header class="masthead">
  <div class="wrap">
    <div class="brandrow">
      <div class="brand">Rubricon<span class="dotmark">.</span></div>
      <div class="tagline">Measurement infrastructure for rubric-based evaluation: reliability
      first, claims second. Every claim passes a signal gate that can refuse it.</div>
    </div>
    <div class="metastrip">
      <span><b>{e(intg(summary.get("n_tracks", len(tracks))))}</b> tracks</span>
      <span><b>{e(intg(summary.get("n_items")))}</b> items</span>
      <span><b>{e(intg(summary.get("n_responses")))}</b> responses</span>
      <span><b>{e(intg(summary.get("n_annotations")))}</b> annotations</span>
      <span><b>{e(pct(summary.get("block_rate"), 1))}</b> of claims blocked</span>
      <span>{rec_strip}</span>
    </div>
    <div class="simbanner" role="note" aria-label="Simulation notice">
      <div class="simhead">
        <span class="mark">SIM</span>
        <span>Simulated annotators &mdash; these numbers are not empirical findings</span>
      </div>
      <div class="simbody">{e(notice)}</div>
    </div>
  </div>
</header>

<nav class="tabbar" aria-label="Dashboard sections">
  <div class="wrap">
    <div class="tablist" role="tablist" id="tablist" aria-label="Dashboard sections">
      {''.join(tab_buttons)}
    </div>
  </div>
</nav>

<main>
{''.join(panel_html)}
</main>

<footer class="methods">
  <div class="wrap">
    <div class="upper muted">Honesty guarantee</div>
    <p class="dim" style="max-width:80ch; margin-top:8px">{e(notice)}</p>
    <p class="muted small">Rubricon &mdash; generated report. Single-file, offline, no external
    resources. Charts are hand-rolled SVG; the full portfolio payload is embedded in this
    document and available as <code>window.RUBRICON</code>.</p>
  </div>
</footer>

<script type="application/json" id="portfolio-data">{_embed_json(data or {})}</script>
<script>{JS}</script>
</body>
</html>
"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path


def render_all(data: dict, results_dir: Path) -> list[Path]:
    """Render every report artifact into ``results_dir``.

    Always writes the HTML dashboard. If the sibling markdown renderer is
    available it is invoked too; its absence is not an error.
    """
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = [render_dashboard(data, results_dir / "dashboard.html")]

    try:
        from .markdown import render_markdown  # type: ignore[attr-defined]
    except ImportError:
        return written

    result = render_markdown(data, results_dir / "report.md")
    if isinstance(result, (list, tuple)):
        written.extend(Path(p) for p in result)
    elif result is not None:
        written.append(Path(result))
    return written
