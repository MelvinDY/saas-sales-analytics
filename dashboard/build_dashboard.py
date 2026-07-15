"""Build the self-contained HTML dashboard from the warehouse marts.

Reads ONLY the four mart tables (all metric logic lives in dbt), embeds the
data as JSON, and renders inline-SVG charts with no external requests:
KPI tiles, MRR-by-region stacked columns, an MRR movement bridge, churn
trend lines, churn-reason bars, the cohort retention heatmap, and plan-level
ARPU / NRR / CLV. Light/dark themed, hover tooltips, and a table view per
chart (the accessibility twin).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
WAREHOUSE = ROOT / "data" / "warehouse.duckdb"
OUT = Path(__file__).resolve().parent / "index.html"

TIERS = ["Basic", "Pro", "Enterprise"]
REGIONS = ["APAC", "AMER", "EMEA"]


def month_label(d: date) -> str:
    return d.strftime("%b %Y")


def series_by_key(rows, months, keys, key_col, val_col):
    """Pivot (month, key, value) rows into {key: [value per month]}."""
    lookup = {(r[0].date() if hasattr(r[0], "date") else r[0], r[1]): r[2]
              for r in rows}
    return {k: [lookup.get((m, k)) for m in months] for k in keys}


def fetch(con):
    months = [r[0].date() for r in con.sql(
        "select distinct revenue_month from mart_revenue_trends order by 1"
    ).fetchall()]

    totals = {r[0].date(): r[1:] for r in con.sql("""
        select revenue_month, sum(mrr), sum(active_customers), sum(new_mrr),
               sum(expansion_mrr), sum(contraction_mrr), sum(churned_mrr),
               sum(churned_customers)
        from mart_revenue_trends group by 1 order by 1
    """).fetchall()}
    mrr = [float(totals[m][0]) for m in months]
    active = [int(totals[m][1]) for m in months]

    region_rows = con.sql(
        "select revenue_month, region, sum(mrr) from mart_revenue_trends "
        "group by 1, 2").fetchall()
    mrr_by_region = series_by_key(region_rows, months, REGIONS, 1, 2)

    bridge = {
        "New": [float(totals[m][2]) for m in months],
        "Expansion": [float(totals[m][3]) for m in months],
        "Contraction": [-float(totals[m][4]) for m in months],
        "Churned": [-float(totals[m][5]) for m in months],
    }

    churn_rate_rows = con.sql("""
        with tier_month as (
            select churn_month, plan_tier,
                   sum(churned_customers)     as churned,
                   max(customers_at_start)    as at_start
            from mart_churn_analysis group by 1, 2)
        select churn_month, plan_tier,
               churned / nullif(at_start, 0) as churn_rate
        from tier_month
    """).fetchall()
    churn_by_tier = series_by_key(churn_rate_rows, months, TIERS, 1, 2)

    reasons = con.sql("""
        select churn_reason, sum(churned_mrr) as mrr
        from mart_churn_analysis group by 1 order by 2 desc
    """).fetchall()

    cohort_rows = con.sql("""
        select cohort_month, months_since_signup, retention_rate, cohort_size,
               active_customers
        from mart_cohort_retention
        where months_since_signup <= 36
        order by 1, 2
    """).fetchall()
    cohort_months = sorted({r[0].date() for r in cohort_rows})
    max_age = max(r[1] for r in cohort_rows)
    grid = {(r[0].date(), r[1]): (float(r[2]), r[3], r[4]) for r in cohort_rows}
    cohort = {
        "rows": [month_label(m) for m in cohort_months],
        "sizes": [grid[(m, 0)][1] for m in cohort_months],
        "cols": list(range(int(max_age) + 1)),
        "cells": [[round(grid[(m, a)][0], 3) if (m, a) in grid else None
                   for a in range(int(max_age) + 1)] for m in cohort_months],
    }

    plan_rows = con.sql("""
        select revenue_month, plan_tier, arpu, nrr_12m
        from mart_plan_performance
    """).fetchall()
    arpu_by_tier = series_by_key(
        [(r[0], r[1], r[2]) for r in plan_rows], months, TIERS, 1, 2)
    nrr_by_tier = series_by_key(
        [(r[0], r[1], r[3]) for r in plan_rows], months, TIERS, 1, 2)

    clv = {r[0]: [r[1], r[2]] for r in con.sql("""
        select plan_tier,
               sum(avg_realized_clv * churned_customers)
                   / nullif(sum(churned_customers), 0)  as realized,
               max(case when revenue_month =
                       (select max(revenue_month) from mart_plan_performance)
                   then predictive_clv end)             as predictive
        from mart_plan_performance group by 1
    """).fetchall()}

    latest = months[-1]
    prev = months[-2]
    nrr_blend = con.sql("""
        select sum(nrr_12m * mrr_12m_ago) / nullif(sum(mrr_12m_ago), 0)
        from mart_plan_performance
        where revenue_month = (select max(revenue_month)
                               from mart_plan_performance)
    """).fetchall()[0][0]

    kpis = {
        "asOf": month_label(latest),
        "mrr": mrr[-1],
        "arr": mrr[-1] * 12,
        "momGrowth": (mrr[-1] - mrr[-2]) / mrr[-2],
        "active": active[-1],
        "churnRate": float(totals[latest][6]) / active[-2],
        "nrr": float(nrr_blend),
        "mrrTrend": mrr[-13:],
        "activeTrend": active[-13:],
    }

    # insight sentences, computed rather than hand-written
    promo = [month_label(date(2024, m, 1)) for m in (5, 6, 7)]
    promo_m6 = [grid[(date(2024, m, 1), 6)][0] for m in (5, 6, 7)
                if (date(2024, m, 1), 6) in grid]
    baseline_m6 = [v for (cm, a), (v, _, _) in grid.items()
                   if a == 6 and cm.year == 2024 and cm.month not in (5, 6, 7)]
    insights = {
        "revenue": (
            f"MRR ended {month_label(latest)} at ${mrr[-1]/1000:,.0f}K "
            f"({kpis['momGrowth']:+.1%} MoM). Growth is led by new business — "
            f"new MRR has out-earned expansion in "
            f"{sum(1 for i in range(-12, 0) if bridge['New'][i] > bridge['Expansion'][i])}"
            f" of the last 12 months."),
        "churn": (
            f"“{reasons[0][0]}” is the costliest churn reason at "
            f"${float(reasons[0][1])/1000:,.0f}K of lifetime-churned MRR — "
            f"Basic churns roughly "
            f"{(sum(v for v in churn_by_tier['Basic'][-12:] if v) / max(1e-9, sum(v for v in churn_by_tier['Enterprise'][-12:] if v))):.0f}x"
            f" faster than Enterprise."),
        "cohort": (
            f"The {promo[0]}–{promo[2]} promo cohorts retain only "
            f"{min(promo_m6):.0%}–{max(promo_m6):.0%} of customers at "
            f"month 6, versus {sum(baseline_m6)/len(baseline_m6):.0%} for the "
            f"surrounding 2024 cohorts — discounted signups churned out fast."),
        "plan": (
            f"Net revenue retention splits cleanly by tier: Pro sits at "
            f"{nrr_by_tier['Pro'][-1]:.0%} (seat expansion offsets churn), "
            f"while Basic retains just {nrr_by_tier['Basic'][-1]:.0%} of its "
            f"year-ago revenue."),
    }

    return {
        "months": [month_label(m) for m in months],
        "kpis": kpis,
        "mrrByRegion": mrr_by_region,
        "bridge": bridge,
        "churnByTier": churn_by_tier,
        "reasons": [[r[0], float(r[1])] for r in reasons],
        "cohort": cohort,
        "arpuByTier": arpu_by_tier,
        "nrrByTier": nrr_by_tier,
        "clv": clv,
        "insights": insights,
    }


def main() -> None:
    con = duckdb.connect(str(WAREHOUSE), read_only=True)
    data = fetch(con)
    for k in ("mrrByRegion", "bridge", "churnByTier", "arpuByTier",
              "nrrByTier"):
        data[k] = {name: [None if v is None else round(float(v), 4)
                          for v in vals] for name, vals in data[k].items()}
    data["clv"] = {t: [None if v is None else round(float(v)) for v in vals]
                   for t, vals in data["clv"].items()}
    data["kpis"] = {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in data["kpis"].items()}
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SaaS Sales &amp; Revenue Analytics</title>
<style>
:root {
  color-scheme: light;
  --plane: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,.10);
  --good: #006300; --bad: #d03b3b;
  --s1: #2a78d6; --s2: #008300; --s3: #e87ba4; --s4: #eda100;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --plane: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
    --good: #0ca30c; --bad: #e66767;
    --s1: #3987e5; --s2: #008300; --s3: #d55181; --s4: #c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0d0d; --surface: #1a1a19;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
  --good: #0ca30c; --bad: #e66767;
  --s1: #3987e5; --s2: #008300; --s3: #d55181; --s4: #c98500;
}
* { box-sizing: border-box; margin: 0; }
html { overflow-y: scroll; }  /* stable gutter: charts measure width once */
body {
  background: var(--plane); color: var(--ink);
  font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
  padding: 24px clamp(12px, 3vw, 40px) 60px;
}
header { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
         margin-bottom: 6px; }
h1 { font-size: 21px; }
header .sub { color: var(--ink-2); }
#theme { margin-left: auto; background: var(--surface); color: var(--ink-2);
  border: 1px solid var(--border); border-radius: 8px; padding: 5px 12px;
  cursor: pointer; font: inherit; }
.filters { display: flex; gap: 6px; align-items: center; margin: 14px 0 18px; }
.filters span { color: var(--muted); margin-right: 4px; }
.filters button { background: var(--surface); border: 1px solid var(--border);
  color: var(--ink-2); border-radius: 8px; padding: 4px 12px; cursor: pointer;
  font: inherit; }
.filters button[aria-pressed="true"] { color: var(--ink); font-weight: 600;
  border-color: var(--axis); }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px,1fr));
        gap: 10px; margin-bottom: 22px; }
.tile { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 12px 14px; }
.tile .lbl { color: var(--ink-2); font-size: 12.5px; }
.tile .val { font-size: 26px; font-weight: 600; margin-top: 2px; }
.tile .delta { font-size: 12.5px; margin-top: 2px; }
.tile .delta.up { color: var(--good); } .tile .delta.down { color: var(--bad); }
.tile svg { display: block; margin-top: 6px; }
h2 { font-size: 15px; margin: 26px 0 4px; }
.insight { color: var(--ink-2); max-width: 76ch; margin-bottom: 12px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px,1fr));
         gap: 14px; }
.card { background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px 10px; min-width: 0; }
.card h3 { font-size: 13.5px; font-weight: 600; }
.card .head { display: flex; align-items: center; gap: 8px; }
.card .head button { margin-left: auto; background: none; color: var(--muted);
  border: 1px solid var(--border); border-radius: 6px; font: 11.5px system-ui;
  padding: 2px 8px; cursor: pointer; }
.legend { display: flex; gap: 14px; flex-wrap: wrap; margin: 6px 0 2px;
  color: var(--ink-2); font-size: 12px; }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px;
  margin-right: 5px; vertical-align: -1.5px; }
.legend i.line { height: 3px; border-radius: 2px; vertical-align: 2.5px; }
.chart { overflow-x: auto; }
.chart svg { display: block; }
.tblwrap { overflow: auto; max-height: 340px; display: none; }
.card.tbl .tblwrap { display: block; } .card.tbl .chart, .card.tbl .legend { display: none; }
table { border-collapse: collapse; font-size: 12px; width: 100%; }
th, td { text-align: right; padding: 3px 8px; border-bottom: 1px solid var(--grid);
  font-variant-numeric: tabular-nums; white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
thead th { position: sticky; top: 0; background: var(--surface); color: var(--ink-2); }
#tip { position: fixed; z-index: 10; pointer-events: none; display: none;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 10px; font-size: 12px; box-shadow: 0 4px 14px rgba(0,0,0,.14);
  max-width: 260px; }
#tip .t { color: var(--ink-2); margin-bottom: 4px; }
#tip .row { display: flex; align-items: center; gap: 7px; }
#tip .row i { width: 10px; height: 3px; border-radius: 2px; }
#tip .row b { margin-left: auto; padding-left: 12px;
  font-variant-numeric: tabular-nums; }
.note { margin-top: 30px; color: var(--muted); font-size: 12.5px; max-width: 86ch;
  border-top: 1px solid var(--grid); padding-top: 12px; }
.scale { display: flex; align-items: center; gap: 8px; font-size: 12px;
  color: var(--ink-2); margin-top: 6px; }
.scale .bar { width: 140px; height: 10px; border-radius: 5px; }
</style>
</head>
<body>
<header>
  <h1>SaaS Sales &amp; Revenue Analytics</h1>
  <span class="sub" id="asof"></span>
  <button id="theme" aria-label="Toggle color theme">◐ theme</button>
</header>
<div class="filters" role="group" aria-label="Date range">
  <span>Range</span>
  <button data-r="all" aria-pressed="true">All</button>
  <button data-r="24" aria-pressed="false">Last 24 mo</button>
  <button data-r="12" aria-pressed="false">Last 12 mo</button>
</div>
<div class="kpis" id="kpis"></div>
<div id="tip" role="status"></div>
<main id="main"></main>
<p class="note"><strong>About this data:</strong> synthetic SaaS dataset
(seeded generator: 1,147 customers, Jan 2023 – Jun 2026) modeled through a
dbt staging → intermediate → marts pipeline; the dashboard reads only the
mart tables, so every number here is reproducible in SQL. MRR movements
follow the standard bridge (new + expansion − contraction − churned); NRR is
the 12-month cohort definition; churned customers count as zero, new logos
excluded. Charts offer a table view for keyboard and screen-reader access.</p>
<script>
const DATA = __DATA__;
const $ = (s, p=document) => p.querySelector(s);
const NS = "http://www.w3.org/2000/svg";
const TIER_C = { Basic: "--s1", Pro: "--s2", Enterprise: "--s3" };
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const fmtK = v => { if (v == null) return "–";
  if (Math.abs(v) < 0.5) v = 0;
  return Math.abs(v) >= 1e6 ? "$" + (v/1e6).toFixed(2) + "M"
    : Math.abs(v) >= 1e3 ? "$" + (v/1e3).toFixed(Math.abs(v) < 1e4 ? 1 : 0) + "K"
    : "$" + Math.round(v).toLocaleString(); };
const fmtPct = v => v == null ? "–" : (v*100).toFixed(1) + "%";
const fmtNum = v => v == null ? "–" : Math.round(v).toLocaleString();

/* ---------- tooltip ---------- */
const tip = $("#tip");
function showTip(evt, title, rows) {
  tip.textContent = "";
  const t = document.createElement("div"); t.className = "t";
  t.textContent = title; tip.appendChild(t);
  for (const [name, val, color] of rows) {
    const r = document.createElement("div"); r.className = "row";
    const i = document.createElement("i");
    i.style.background = color || "transparent"; r.appendChild(i);
    const n = document.createElement("span"); n.textContent = name; r.appendChild(n);
    const b = document.createElement("b"); b.textContent = val; r.appendChild(b);
    tip.appendChild(r);
  }
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + 14, y = evt.clientY + 12;
  if (x + w > innerWidth - 8) x = evt.clientX - w - 14;
  if (y + h > innerHeight - 8) y = evt.clientY - h - 12;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
const hideTip = () => tip.style.display = "none";

/* ---------- svg helpers ---------- */
function svgEl(tag, attrs) {
  const e = document.createElementNS(NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
function niceTicks(lo, hi, n=4) {
  const span = hi - lo || 1, step0 = span / n,
    mag = Math.pow(10, Math.floor(Math.log10(step0))),
    step = [1,2,2.5,5,10].map(m => m*mag).find(s => span/s <= n) || 10*mag,
    start = Math.ceil(lo/step)*step, out = [];
  for (let v = start; v <= hi + 1e-9; v += step) out.push(v);
  return out;
}

/* ---------- generic axis frame ---------- */
function frame(svg, W, H, P, yTicks, yFmt, xLabels, xEvery) {
  for (const t of yTicks) {
    const y = t.y;
    svg.appendChild(svgEl("line", {x1:P.l, x2:W-P.r, y1:y, y2:y,
      stroke:"var(--grid)", "stroke-width":1}));
    const lbl = svgEl("text", {x:P.l-8, y:y+4, "text-anchor":"end",
      fill:"var(--muted)", "font-size":11, style:"font-variant-numeric:tabular-nums"});
    lbl.textContent = yFmt(t.v); svg.appendChild(lbl);
  }
  svg.appendChild(svgEl("line", {x1:P.l, x2:W-P.r, y1:H-P.b, y2:H-P.b,
    stroke:"var(--axis)", "stroke-width":1}));
  xLabels.forEach((m, i) => {
    if (i % xEvery !== 0) return;
    const lbl = svgEl("text", {x:m.x, y:H-P.b+16, "text-anchor":"middle",
      fill:"var(--muted)", "font-size":11});
    lbl.textContent = m.name; svg.appendChild(lbl);
  });
}

/* ---------- line chart with crosshair ---------- */
function lineChart(mount, months, series, yFmt, opts={}) {
  const W = Math.max((mount.clientWidth || 640) - 2, 380), H = 240,
    P = {l:52, r:14, t:12, b:26},
    xs = i => P.l + (months.length < 2 ? 0 : i*(W-P.l-P.r)/(months.length-1));
  let vals = series.flatMap(s => s.values).filter(v => v != null);
  let lo = Math.min(...vals, opts.ref != null ? opts.ref : Infinity),
      hi = Math.max(...vals, opts.ref != null ? opts.ref : -Infinity);
  if (opts.zero) lo = Math.min(lo, 0);
  const pad = (hi-lo)*0.08 || 1; lo -= pad; hi += pad;
  const ys = v => H-P.b - (v-lo)/(hi-lo)*(H-P.t-P.b);
  const svg = svgEl("svg", {width:W, height:H, viewBox:`0 0 ${W} ${H}`,
    role:"img", "aria-label": opts.label || "line chart"});
  frame(svg, W, H, P, niceTicks(lo,hi).map(v=>({v, y:ys(v)})), yFmt,
    months.map((name,i)=>({name, x:xs(i)})), Math.ceil(months.length/6));
  if (opts.ref != null) {
    svg.appendChild(svgEl("line", {x1:P.l, x2:W-P.r, y1:ys(opts.ref),
      y2:ys(opts.ref), stroke:"var(--axis)", "stroke-width":1}));
    const t = svgEl("text", {x:W-P.r-2, y:ys(opts.ref)-4, "text-anchor":"end",
      fill:"var(--muted)", "font-size":10.5});
    t.textContent = opts.refLabel || String(opts.ref); svg.appendChild(t);
  }
  for (const s of series) {
    let d = "", pen = false;
    s.values.forEach((v,i) => {
      if (v == null) { pen = false; return; }
      d += (pen ? "L" : "M") + xs(i).toFixed(1) + " " + ys(v).toFixed(1);
      pen = true;
    });
    svg.appendChild(svgEl("path", {d, fill:"none", stroke:`var(${s.c})`,
      "stroke-width":2, "stroke-linejoin":"round", "stroke-linecap":"round"}));
  }
  const cross = svgEl("line", {y1:P.t, y2:H-P.b, stroke:"var(--axis)",
    "stroke-width":1, visibility:"hidden"});
  svg.appendChild(cross);
  const dots = series.map(s => {
    const d = svgEl("circle", {r:4.5, fill:`var(${s.c})`,
      stroke:"var(--surface)", "stroke-width":2, visibility:"hidden"});
    svg.appendChild(d); return d;
  });
  svg.addEventListener("pointermove", e => {
    const r = svg.getBoundingClientRect(),
      i = Math.max(0, Math.min(months.length-1,
        Math.round((e.clientX-r.left-P.l)/((W-P.l-P.r)/(months.length-1)))));
    cross.setAttribute("x1", xs(i)); cross.setAttribute("x2", xs(i));
    cross.setAttribute("visibility", "visible");
    series.forEach((s,k) => {
      const v = s.values[i];
      dots[k].setAttribute("visibility", v==null ? "hidden" : "visible");
      if (v!=null){ dots[k].setAttribute("cx",xs(i)); dots[k].setAttribute("cy",ys(v)); }
    });
    showTip(e, months[i],
      series.map(s => [s.name, yFmt(s.values[i]), css(s.c)]));
  });
  svg.addEventListener("pointerleave", () => { hideTip();
    cross.setAttribute("visibility","hidden");
    dots.forEach(d=>d.setAttribute("visibility","hidden")); });
  mount.appendChild(svg);
}

/* ---------- stacked columns (supports negatives) ---------- */
function stackChart(mount, months, series, yFmt, opts={}) {
  const W = Math.max((mount.clientWidth || 640) - 2, 380), H = 250,
    P = {l:56, r:10, t:12, b:26},
    slot = (W-P.l-P.r)/months.length,
    bw = Math.min(24, Math.max(5, slot-4));
  let hi = 0, lo = 0;
  months.forEach((_,i) => {
    let up=0, dn=0;
    for (const s of series) { const v=s.values[i]||0; if (v>=0) up+=v; else dn+=v; }
    hi = Math.max(hi, up); lo = Math.min(lo, dn);
  });
  hi *= 1.06; lo = lo < 0 ? lo*1.06 : 0;
  const ys = v => H-P.b - (v-lo)/(hi-lo)*(H-P.t-P.b);
  const svg = svgEl("svg", {width:W, height:H, viewBox:`0 0 ${W} ${H}`,
    role:"img", "aria-label": opts.label || "stacked column chart"});
  frame(svg, W, H, P, niceTicks(lo,hi).map(v=>({v, y:ys(v)})), yFmt,
    months.map((name,i)=>({name, x:P.l+slot*i+slot/2})),
    Math.ceil(months.length/6));
  months.forEach((m,i) => {
    let up=0, dn=0;
    series.forEach((s, si) => {
      const v = s.values[i]||0; if (!v) return;
      let y0, y1;
      if (v>=0) { y1 = ys(up); up += v; y0 = ys(up); }
      else { y0 = ys(dn); dn += v; y1 = ys(dn); }
      const gap = si === 0 ? 0 : 1;   /* 2px visual gap = 1px trim each side */
      const rect = svgEl("rect", {x:P.l+slot*i+(slot-bw)/2,
        y:Math.min(y0,y1)+gap, width:bw,
        height:Math.max(0.5, Math.abs(y1-y0)-gap-1),
        rx:2, fill:`var(${s.c})`, tabindex:0});
      const show = e => showTip(e.clientX ? e : {clientX:innerWidth/2,
        clientY:innerHeight/3}, m,
        series.map(x => [x.name, yFmt(x.values[i]), css(x.c)]));
      rect.addEventListener("pointermove", show);
      rect.addEventListener("focus", show);
      rect.addEventListener("pointerleave", hideTip);
      rect.addEventListener("blur", hideTip);
      svg.appendChild(rect);
    });
  });
  svg.appendChild(svgEl("line", {x1:P.l, x2:W-P.r, y1:ys(0), y2:ys(0),
    stroke:"var(--axis)", "stroke-width":1}));
  mount.appendChild(svg);
}

/* ---------- horizontal bars, one series ---------- */
function hbarChart(mount, rows, fmt) {
  const W = Math.max((mount.clientWidth || 560) - 2, 380),
    rh = 30, P = {l:180, r:80, t:6, b:6}, H = P.t+P.b+rows.length*rh,
    hi = Math.max(...rows.map(r => r[1])),
    xs = v => P.l + v/hi*(W-P.l-P.r);
  const svg = svgEl("svg", {width:W, height:H, viewBox:`0 0 ${W} ${H}`,
    role:"img", "aria-label":"bar chart"});
  rows.forEach((r,i) => {
    const y = P.t + i*rh + (rh-18)/2;
    const lbl = svgEl("text", {x:P.l-8, y:y+13, "text-anchor":"end",
      fill:"var(--ink-2)", "font-size":12});
    lbl.textContent = r[0]; svg.appendChild(lbl);
    const rect = svgEl("rect", {x:P.l, y, width:Math.max(2, xs(r[1])-P.l),
      height:18, rx:3, fill:"var(--s1)", tabindex:0});
    const show = e => showTip(e.clientX ? e : {clientX:innerWidth/2,
      clientY:innerHeight/3}, r[0], [["Churned MRR", fmt(r[1]), css("--s1")]]);
    rect.addEventListener("pointermove", show);
    rect.addEventListener("focus", show);
    rect.addEventListener("pointerleave", hideTip);
    rect.addEventListener("blur", hideTip);
    svg.appendChild(rect);
    const val = svgEl("text", {x:xs(r[1])+6, y:y+13, fill:"var(--ink)",
      "font-size":12, style:"font-variant-numeric:tabular-nums"});
    val.textContent = fmt(r[1]); svg.appendChild(val);
  });
  mount.appendChild(svg);
}

/* ---------- cohort heatmap ---------- */
const RAMP_L = ["#cde2fb","#9ec5f4","#6da7ec","#3987e5","#256abf","#184f95","#0d366b"];
const RAMP_D = ["#0d366b","#184f95","#256abf","#3987e5","#6da7ec","#9ec5f4","#cde2fb"];
function rampColor(v) {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches
    ? document.documentElement.dataset.theme !== "light"
    : document.documentElement.dataset.theme === "dark";
  const R = dark ? RAMP_D : RAMP_L,
    x = Math.max(0, Math.min(1, v)) * (R.length-1),
    i = Math.min(R.length-2, Math.floor(x)), f = x-i,
    hex = c => [1,3,5].map(o => parseInt(c.slice(o,o+2),16));
  const a = hex(R[i]), b = hex(R[i+1]);
  return "rgb(" + a.map((c,k)=>Math.round(c+(b[k]-c)*f)).join(",") + ")";
}
function heatmap(mount, co) {
  const cell = 17, gap = 2, P = {l:92, r:8, t:26, b:8},
    W = P.l+P.r+co.cols.length*(cell+gap),
    H = P.t+P.b+co.rows.length*(cell+gap);
  const svg = svgEl("svg", {width:W, height:H, viewBox:`0 0 ${W} ${H}`,
    role:"img", "aria-label":"cohort retention heatmap"});
  co.cols.forEach(c => {
    if (c % 3 !== 0) return;
    const t = svgEl("text", {x:P.l+c*(cell+gap)+cell/2, y:P.t-8,
      "text-anchor":"middle", fill:"var(--muted)", "font-size":10.5});
    t.textContent = c; svg.appendChild(t);
  });
  co.rows.forEach((r,ri) => {
    if (ri % 2 === 0) {
      const t = svgEl("text", {x:P.l-8, y:P.t+ri*(cell+gap)+cell-4,
        "text-anchor":"end", fill:"var(--muted)", "font-size":10.5});
      t.textContent = r; svg.appendChild(t);
    }
    co.cells[ri].forEach((v,ci) => {
      if (v == null) return;
      const rect = svgEl("rect", {x:P.l+ci*(cell+gap), y:P.t+ri*(cell+gap),
        width:cell, height:cell, rx:3, fill:rampColor(v), tabindex:0});
      const show = e => showTip(e.clientX ? e : {clientX:innerWidth/2,
        clientY:innerHeight/3},
        `${r} cohort · month ${co.cols[ci]}`,
        [["Retention", fmtPct(v), rampColor(v)],
         ["Cohort size", fmtNum(co.sizes[ri]), null]]);
      rect.addEventListener("pointermove", show);
      rect.addEventListener("focus", show);
      rect.addEventListener("pointerleave", hideTip);
      rect.addEventListener("blur", hideTip);
      svg.appendChild(rect);
    });
  });
  mount.appendChild(svg);
  const sc = document.createElement("div"); sc.className = "scale";
  const lo = document.createElement("span"); lo.textContent = "0%";
  const bar = document.createElement("div"); bar.className = "bar";
  bar.style.background = `linear-gradient(90deg, ${[0,.25,.5,.75,1]
    .map(v => rampColor(v)).join(",")})`;
  const hi = document.createElement("span"); hi.textContent = "100% retained";
  sc.append(lo, bar, hi); mount.appendChild(sc);
}

/* ---------- cards, legends, tables ---------- */
function card(parent, title, tableBuilder) {
  const c = document.createElement("div"); c.className = "card";
  const head = document.createElement("div"); head.className = "head";
  const h = document.createElement("h3"); h.textContent = title;
  const btn = document.createElement("button"); btn.textContent = "table";
  btn.setAttribute("aria-pressed", "false");
  btn.onclick = () => { const on = c.classList.toggle("tbl");
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = on ? "chart" : "table"; };
  head.append(h, btn); c.appendChild(head);
  const legend = document.createElement("div"); legend.className = "legend";
  c.appendChild(legend);
  const mount = document.createElement("div"); mount.className = "chart";
  c.appendChild(mount);
  const tw = document.createElement("div"); tw.className = "tblwrap";
  tw.appendChild(tableBuilder()); c.appendChild(tw);
  parent.appendChild(c);
  return { mount, legend };
}
function legendFor(el, entries, lineKey=false) {
  for (const [name, c] of entries) {
    const s = document.createElement("span");
    const i = document.createElement("i");
    if (lineKey) i.className = "line";
    i.style.background = css(c); s.appendChild(i);
    s.appendChild(document.createTextNode(name)); el.appendChild(s);
  }
}
function tableOf(headers, rows) {
  const t = document.createElement("table");
  const tr = document.createElement("tr");
  for (const h of headers) { const th = document.createElement("th");
    th.textContent = h; tr.appendChild(th); }
  const thead = document.createElement("thead"); thead.appendChild(tr);
  t.appendChild(thead);
  const tb = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const cellv of row) { const td = document.createElement("td");
      td.textContent = cellv; tr.appendChild(td); }
    tb.appendChild(tr);
  }
  t.appendChild(tb);
  return t;
}

/* ---------- page assembly ---------- */
/* charts measure their card's width, so drawing is deferred until every
   card is in the grid and the layout is final */
const draws = [];
const draw = fn => draws.push(fn);
let range = "all";
function sliceIdx() {
  const n = DATA.months.length;
  return range === "all" ? 0 : Math.max(0, n - parseInt(range, 10));
}
function render() {
  $("#asof").textContent = "as of " + DATA.kpis.asOf +
    " · dbt marts on DuckDB · synthetic data";
  const start = sliceIdx(), months = DATA.months.slice(start),
    cut = s => s.slice(start);

  /* KPI tiles */
  const K = DATA.kpis, kp = $("#kpis"); kp.textContent = "";
  const tile = (lbl, val, delta, up, trend) => {
    const d = document.createElement("div"); d.className = "tile";
    const l = document.createElement("div"); l.className = "lbl";
    l.textContent = lbl;
    const v = document.createElement("div"); v.className = "val";
    v.textContent = val; d.append(l, v);
    if (delta) { const de = document.createElement("div");
      de.className = "delta " + (up ? "up" : "down");
      de.textContent = delta; d.appendChild(de); }
    if (trend) {
      const w = 120, h = 26,
        lo = Math.min(...trend), hi = Math.max(...trend),
        xs = i => i*w/(trend.length-1),
        ys = v => h-2 - (hi===lo ? .5 : (v-lo)/(hi-lo))*(h-4);
      const svg = svgEl("svg", {width:w, height:h, "aria-hidden":"true"});
      svg.appendChild(svgEl("path", {fill:"none", stroke:"var(--muted)",
        "stroke-width":1.5,
        d: trend.map((v,i)=>(i?"L":"M")+xs(i).toFixed(1)+" "+ys(v).toFixed(1)).join("")}));
      svg.appendChild(svgEl("circle", {cx:xs(trend.length-1),
        cy:ys(trend[trend.length-1]), r:3, fill:"var(--s1)",
        stroke:"var(--surface)", "stroke-width":2}));
      d.appendChild(svg);
    }
    kp.appendChild(d);
  };
  tile("Monthly recurring revenue", fmtK(K.mrr),
    (K.momGrowth>=0?"+":"") + fmtPct(K.momGrowth) + " vs prior month",
    K.momGrowth>=0, K.mrrTrend);
  tile("Annual run rate", fmtK(K.arr));
  tile("Active customers", fmtNum(K.active), null, true, K.activeTrend);
  tile("Customer churn (month)", fmtPct(K.churnRate));
  tile("Net revenue retention (12m)", fmtPct(K.nrr));

  const main = $("#main"); main.textContent = "";
  const section = (title, insight) => {
    const h = document.createElement("h2"); h.textContent = title;
    const p = document.createElement("p"); p.className = "insight";
    p.textContent = insight;
    const g = document.createElement("div"); g.className = "grid2";
    main.append(h, p, g); return g;
  };

  /* 1 · revenue */
  const g1 = section("Revenue overview", DATA.insights.revenue);
  const regions = [["APAC","--s1"],["AMER","--s2"],["EMEA","--s3"]];
  const c1 = card(g1, "MRR by region", () => tableOf(
    ["Month","APAC","AMER","EMEA","Total"],
    months.map((m,i) => [m,
      ...regions.map(([r]) => fmtK(cut(DATA.mrrByRegion[r])[i])),
      fmtK(regions.reduce((a,[r]) => a+(cut(DATA.mrrByRegion[r])[i]||0), 0))])));
  legendFor(c1.legend, regions);
  draw(() => stackChart(c1.mount, months,
    regions.map(([r,c]) => ({name:r, c, values:cut(DATA.mrrByRegion[r])})),
    fmtK, {label:"MRR by region stacked columns"}));

  const bridgeS = [["New","--s1"],["Expansion","--s2"],
                   ["Contraction","--s3"],["Churned","--s4"]];
  const c2 = card(g1, "MRR movement bridge", () => tableOf(
    ["Month","New","Expansion","Contraction","Churned","Net new"],
    months.map((m,i) => { const v = bridgeS.map(([k]) => cut(DATA.bridge[k])[i]||0);
      return [m, ...v.map(fmtK), fmtK(v.reduce((a,b)=>a+b,0))]; })));
  legendFor(c2.legend, bridgeS);
  draw(() => stackChart(c2.mount, months,
    bridgeS.map(([k,c]) => ({name:k, c, values:cut(DATA.bridge[k])})),
    fmtK, {label:"MRR movement bridge"}));

  /* 2 · churn */
  const g2 = section("Churn analysis", DATA.insights.churn);
  const tiers = ["Basic","Pro","Enterprise"].map(t => [t, TIER_C[t]]);
  const c3 = card(g2, "Monthly customer churn rate by plan", () => tableOf(
    ["Month","Basic","Pro","Enterprise"],
    months.map((m,i) => [m, ...tiers.map(([t]) =>
      fmtPct(cut(DATA.churnByTier[t])[i]))])));
  legendFor(c3.legend, tiers, true);
  draw(() => lineChart(c3.mount, months,
    tiers.map(([t,c]) => ({name:t, c, values:cut(DATA.churnByTier[t])})),
    fmtPct, {zero:true, label:"churn rate by plan tier"}));

  const c4 = card(g2, "Churned MRR by reason (lifetime)", () => tableOf(
    ["Reason","Churned MRR"], DATA.reasons.map(r => [r[0], fmtK(r[1])])));
  draw(() => hbarChart(c4.mount, DATA.reasons, fmtK));

  /* 3 · cohorts */
  const g3 = section("Cohort retention", DATA.insights.cohort);
  const co = DATA.cohort,
    rStart = range === "all" ? 0 : Math.max(0, co.rows.length - parseInt(range,10)),
    coCut = { rows: co.rows.slice(rStart), sizes: co.sizes.slice(rStart),
      cols: co.cols, cells: co.cells.slice(rStart) };
  const c5 = card(g3, "Logo retention by signup cohort", () => tableOf(
    ["Cohort","Size", ...co.cols.filter(c=>c%3===0&&c>0).map(c=>"M"+c)],
    coCut.rows.map((r,i) => [r, coCut.sizes[i],
      ...co.cols.filter(c=>c%3===0&&c>0).map(c =>
        fmtPct(coCut.cells[i][c]))])));
  draw(() => heatmap(c5.mount, coCut));

  /* 4 · plans */
  const g4 = section("Plan performance", DATA.insights.plan);
  const c6 = card(g4, "ARPU by plan tier", () => tableOf(
    ["Month","Basic","Pro","Enterprise"],
    months.map((m,i) => [m, ...tiers.map(([t]) =>
      fmtK(cut(DATA.arpuByTier[t])[i]))])));
  legendFor(c6.legend, tiers, true);
  draw(() => lineChart(c6.mount, months,
    tiers.map(([t,c]) => ({name:t, c, values:cut(DATA.arpuByTier[t])})),
    fmtK, {zero:true, label:"ARPU by plan tier"}));

  const c7 = card(g4, "Net revenue retention (12m) by plan tier", () => tableOf(
    ["Month","Basic","Pro","Enterprise"],
    months.map((m,i) => [m, ...tiers.map(([t]) =>
      fmtPct(cut(DATA.nrrByTier[t])[i]))])));
  legendFor(c7.legend, tiers, true);
  draw(() => lineChart(c7.mount, months,
    tiers.map(([t,c]) => ({name:t, c, values:cut(DATA.nrrByTier[t])})),
    fmtPct, {ref:1, refLabel:"100%", label:"NRR by plan tier"}));

  const clvS = [["Realized (avg, churned)","--s1"],["Predictive (ARPU ÷ churn)","--s2"]];
  const c8 = card(g4, "Customer lifetime value by plan tier", () => tableOf(
    ["Tier","Realized CLV","Predictive CLV"],
    Object.entries(DATA.clv).map(([t,v]) => [t, fmtK(v[0]), fmtK(v[1])])));
  legendFor(c8.legend, clvS);
  draw(() => (function grouped(mount) {
    const order = ["Basic","Pro","Enterprise"],
      W = Math.max((mount.clientWidth || 560) - 2, 380),
      rh = 56, P = {l:100, r:90, t:6, b:6}, H = P.t+P.b+order.length*rh,
      hi = Math.max(...order.flatMap(t => DATA.clv[t].map(v => v||0))),
      xs = v => P.l + v/hi*(W-P.l-P.r);
    const svg = svgEl("svg", {width:W, height:H, viewBox:`0 0 ${W} ${H}`,
      role:"img", "aria-label":"CLV by plan tier"});
    order.forEach((t,i) => {
      const y0 = P.t + i*rh;
      const lbl = svgEl("text", {x:P.l-8, y:y0+rh/2+4, "text-anchor":"end",
        fill:"var(--ink-2)", "font-size":12});
      lbl.textContent = t; svg.appendChild(lbl);
      DATA.clv[t].forEach((v,k) => {
        if (v == null) return;
        const y = y0 + 6 + k*22;
        const rect = svgEl("rect", {x:P.l, y, width:Math.max(2, xs(v)-P.l),
          height:16, rx:3, fill:`var(${clvS[k][1]})`, tabindex:0});
        const show = e => showTip(e.clientX ? e : {clientX:innerWidth/2,
          clientY:innerHeight/3}, t,
          [[clvS[k][0], fmtK(v), css(clvS[k][1])]]);
        rect.addEventListener("pointermove", show);
        rect.addEventListener("focus", show);
        rect.addEventListener("pointerleave", hideTip);
        rect.addEventListener("blur", hideTip);
        svg.appendChild(rect);
        const val = svgEl("text", {x:xs(v)+6, y:y+12.5, fill:"var(--ink)",
          "font-size":11.5, style:"font-variant-numeric:tabular-nums"});
        val.textContent = fmtK(v); svg.appendChild(val);
      });
    });
    mount.appendChild(svg);
  })(c8.mount));

  draws.splice(0).forEach(f => f());
}

/* theme + filters */
$("#theme").onclick = () => {
  const root = document.documentElement,
    dark = root.dataset.theme === "dark" ||
      (root.dataset.theme !== "light" &&
       matchMedia("(prefers-color-scheme: dark)").matches);
  root.dataset.theme = dark ? "light" : "dark";
  render();
};
for (const b of document.querySelectorAll(".filters button")) {
  b.onclick = () => {
    range = b.dataset.r;
    for (const x of document.querySelectorAll(".filters button"))
      x.setAttribute("aria-pressed", String(x === b));
    render();
  };
}
render();
addEventListener("resize", () => { clearTimeout(window.__rr);
  window.__rr = setTimeout(render, 150); });
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
