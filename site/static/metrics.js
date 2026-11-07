/* sim2real · the metrics page (site/metrics_pages.py): metrics, diagnostics and coverage over the runs in play, computed live.

   Zach (PROJECT - Sim2Real, 2026-11-06): "its just the row model you can basically like include or not what runs will be included in the
   metrics/diagonistics etc" and "visualize quickly like the currently selected runs or run what is its coverage". The runs in play are the
   runs table's ticked rows when it has any, else every row its filters (the rail, the query) leave.

   The rule is type_cards/CONTRACT.md's, "The browser, live (data-ui), the same numbers", and every step is selection.compute's:
   1. a run's value of a metric is its row of data/domain/metric_values/<dep>.json (selection.metric_values: runs.json's column, RobotDx's
      per-run row ÷ the station's T1 floor, or tools/run_metrics.py's value);
   2. across the runs in play, the metric's aggregate by data-ui's own summarize (median by default), min and max beside it;
   3. a diagnostic's level is its limits on that value (domain.level: error first, then warn; a unit's own limit from deployments.json where
      its type leaves it per unit; no value or no limit value is unknown); a gate's verdict its target's;
   4. coverage is the distinct reachable cells of data/domain/coverage_cells/<dep>.json whose run is in play, over the device's reachable
      cells, a % to 2 decimals rounded as Python's round() rounds.
   data-ui computes no verdict (its CONTRACT §35), so the levels are this file's one comparison; data-ui draws the tables and the heatmap.
   site/tests/test_site_flow.py holds every number to selection.compute for three selections made here (window.s2rMetrics.snapshot()).
   No storage is touched here. */
const root = document.querySelector("[data-metrics-page]");
if (root) start().catch((err) => { console.error(err); const out = document.getElementById("s2r-metrics-results"); if (out) out.insertAdjacentHTML("afterbegin", `<p class="s2r-merr">The live numbers did not load (${esc(String(err && err.message || err))}); the build's below.</p>`); });

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }

// Python's round(x, 2): correctly rounded, ties to even. A tie at the third decimal is exact in binary only at .125, .375, .625 and .875
// (x a multiple of 1/8); toFixed breaks those ties upward, Python to the even neighbour. Anywhere else both give the correctly rounded value.
function round2(x) {
  if (Number.isInteger(x * 8) && !Number.isInteger(x * 100)) {
    const lo = Math.floor(x * 100);
    return (lo % 2 === 0 ? lo : lo + 1) / 100;
  }
  return Number(x.toFixed(2));
}

// domain.level: error checked first, then warn; a side whose value is set per unit reads the unit's own (lim); no value, or no limit with a
// value, is unknown: never a guess
function level(diag, value, lim) {
  if (value === null || value === undefined) return "unknown";
  let checked = false;
  for (const [side, word] of [["error", "error"], ["warn", "warning"]]) {
    const L = diag[side];
    if (!L) continue;
    const v = lim && lim[side] !== undefined && lim[side] !== null ? lim[side] : L.value;
    if (v === null || v === undefined) continue;
    checked = true;
    if (!(L.op === "<=" ? value <= v : value >= v)) return word;
  }
  return checked ? "ok" : "unknown";
}

function bounds(L, v) { return !L || v === null || v === undefined ? [null, null] : (L.op === ">=" ? [v, null] : [null, v]); }

async function start() {
  const spec = JSON.parse(document.getElementById("s2r-metrics-spec").textContent);
  const kit = await import("/static/data-ui/data-ui.js");
  await customElements.whenDefined("data-views");
  const [values, cells, runsDoc] = await Promise.all([fetch(spec.data.values).then((r) => r.json()), fetch(spec.data.cells).then((r) => r.json()),
                                                     fetch(spec.data.runs).then((r) => r.json())]);
  const runsEl = document.getElementById("metrics-runs");
  const RANK = spec.level_rank;
  const types = spec.types;
  const nodes = spec.nodes.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const limitsOf = (node) => Object.fromEntries((node.limits || []).map((x) => [x.diagnostic, x]));
  // the run x metric rows and the run x cell rows, by run
  const valuesByRun = new Map();
  for (const r of values.rows) { if (!valuesByRun.has(r.run)) valuesByRun.set(r.run, []); valuesByRun.get(r.run).push(r); }
  const cellsByRun = new Map();
  for (const r of cells.rows) { if (!r.reachable) continue; if (!cellsByRun.has(r.run)) cellsByRun.set(r.run, []); cellsByRun.get(r.run).push(r); }
  // run -> device: every run of the deployment (selection.compute reads a run's device from its runs.json row, values or not)
  const deviceOf = new Map(runsDoc.rows.map((r) => [r.run, r.device]));

  function summary(vals, name) {
    if (!vals.length) return { value: null, low: null, high: null, n: 0 };
    return { value: kit.summarize(vals, name), low: kit.summarize(vals, "Min"), high: kit.summarize(vals, "Max"), n: vals.length };
  }

  function compute(ids) {
    const inPlay = ids.filter((id) => deviceOf.has(id));
    const devices = new Set(inPlay.map((id) => deviceOf.get(id)));
    const out = [];
    for (const node of nodes) {
      if (!devices.has(node.device)) continue;
      const t = types[node.entity_type];
      const mine = inPlay.filter((id) => deviceOf.get(id) === node.device);
      const rows = [];
      for (const id of mine) for (const r of valuesByRun.get(id) || []) if (r.node === node.id) rows.push(r);
      const lim = limitsOf(node);
      const entries = {};
      const metrics = [];
      for (const m of t.metrics) {
        const base = { metric: m.id, title: m.title, unit: m.unit, pinned: m.pinned, family: m.family, aggregate: m.aggregate };
        let got;
        if (!m.per_run) {
          got = [{ ...base, model: null, value: null, low: null, high: null, n: 0, why: m.why_not }];
        } else if (!m.per_model) {
          const vals = rows.filter((r) => r.metric === m.id).map((r) => r.value);
          got = [{ ...base, model: null, ...summary(vals, m.summary), why: vals.length ? "" : whyNone(m.id, mine) }];
        } else {
          const by = new Map();
          for (const r of rows) if (r.metric === m.id) { const k = r.model ?? ""; if (!by.has(k)) by.set(k, []); by.get(k).push(r.value); }
          const keys = [...by.keys()].sort();
          got = keys.length ? keys.map((k) => ({ ...base, model: k || null, ...summary(by.get(k), m.summary), why: "" }))
            : [{ ...base, model: null, value: null, low: null, high: null, n: 0, why: "no model replayed the runs in play" }];
        }
        entries[m.id] = got;
        metrics.push(...got);
      }
      const diagnostics = [];
      for (const d of t.diagnostics) {
        if (d.units !== "metric") continue;  // a drift check needs its calibrated or commissioned value: not a selection's
        const ul = lim[d.id] || null;
        for (const e of entries[d.metric] || []) {
          const lv = level(d, e.value, ul);
          const wv = ul && ul.warn != null ? ul.warn : (d.warn ? d.warn.value : null);
          const ev = ul && ul.error != null ? ul.error : (d.error ? d.error.value : null);
          const [warn_lo, warn_hi] = bounds(d.warn, wv), [error_lo, error_hi] = bounds(d.error, ev);
          diagnostics.push({ subject: node.id, diagnostic: d.id, title: d.title, level: lv, rank: RANK[lv], value: e.value,
            unit: (d.warn || d.error || {}).unit || "", warn_lo, warn_hi, error_lo, error_hi, kind: d.kind, model: e.model, runs: e.n, metric: d.metric,
            message: lv === "warning" || lv === "error" ? (d.message || `${d.title} past its limit`) : "" });
        }
      }
      const gates = [];
      for (const g of t.gates) {
        const d = t.diagnostics.find((x) => x.id === g.diagnostic);
        const metric = d ? d.metric : "";
        const target = lim[g.diagnostic] ? lim[g.diagnostic].target : undefined;
        for (const e of entries[metric] || [{ model: null, value: null }]) {
          let verdict;
          if (e.value === null || e.value === undefined) verdict = "not_run";
          else if (g.target.value === null && (target === undefined || target === null)) verdict = "unknown";
          else { const v = g.target.value !== null ? g.target.value : target; verdict = (g.target.op === "<=" ? e.value <= v : e.value >= v) ? "pass" : "fail"; }
          gates.push({ gate: g.id, diagnostic: g.diagnostic, metric, model: e.model, verdict, value: e.value ?? null, acceptance: g.acceptance });
        }
      }
      out.push({ node: node.id, device: node.device, entity_type: node.entity_type, runs: mine.length, metrics, diagnostics, gates,
                 coverage: coverage(t, node.device, mine) });
    }
    return { runs: inPlay.length, run_ids: inPlay.slice().sort(), nodes: out };
  }

  function whyNone(metric, mine) {
    // the producer's own words where it wrote why a run has no value (a sine has no stop), the most common first
    const col = { "servo.stop_error": "stop_error_why", "driver.saturation": "saturation_why" }[metric];
    if (!col) return "no run in play has a value";
    const count = new Map();
    for (const id of mine) { const r = runsEl.row(id); const w = r && r[col]; if (w) count.set(w, (count.get(w) || 0) + 1); }
    const best = [...count.entries()].sort((a, b) => b[1] - a[1])[0];
    return best ? best[0] : "no run in play has a value";
  }

  function coverage(t, device, mine) {
    const c = t.coverage;
    const base = { gate_pct: c.gate_pct, rule: "" };
    if (!c.from_runs) return { ...base, pct: null, visited: null, reachable: null, verdict: "observed", why: c.why_not };
    const reach = cells.reachable_cells[device];
    if (reach === undefined) return { ...base, pct: null, visited: null, reachable: null, verdict: "unknown",
                                      why: `no joint description for ${device} (its live test schedule's description: range, speed, accel, torque limit)` };
    const seen = [];
    for (const id of mine) for (const r of cellsByRun.get(id) || []) if (r.device === device) seen.push(r.cell);
    const visited = kit.summarize(seen, "Unique");  // data-ui's own distinct count
    const pct = round2(100 * visited / Math.max(1, reach));
    return { ...base, pct, visited, reachable: reach, verdict: c.gate_pct === null ? "observed" : (pct >= c.gate_pct ? "pass" : "fail"), why: "",
             cells: new Set(seen) };
  }

  // ---- drawing -----------------------------------------------------------------------------------------------------------------------
  const out = document.getElementById("s2r-metrics-results");
  const fmt = (v, unit) => {
    if (v === null || v === undefined) return "—";
    // three significant digits, as the site's pages.num writes them ("9.5", "0.0123"); a large number whole
    const text = Math.abs(v) >= 1000 ? Math.round(v).toLocaleString("en-US") : String(Number(Number(v).toPrecision(3)));
    if (unit && unit.startsWith("×")) return `${text}${unit}`;
    return `${text} ${unit === "1" ? "" : unit || ""}`.trim();
  };
  const raw = (v) => (v === null || v === undefined ? "" : String(v));
  const chip = (lv) => `<span class="s2r-lv s2r-lv-${esc(lv)}" data-level="${esc(lv)}">${esc(lv)}</span>`;
  const dot = (lv, why) => `<span class="s2r-dot s2r-dot-${esc(lv)}" role="img" aria-label="${esc(lv)}" title="${esc(lv + (why ? ": " + why : ""))}"></span>`;
  const plural = (n, w) => `${n.toLocaleString("en-US")} ${w}${n === 1 ? "" : "s"}`;
  const worst = (levels) => levels.reduce((a, b) => (RANK[b] > RANK[a] ? b : a), levels.length ? levels[0] : "unknown");
  const independent = (n, metric) => { const m = types[n.entity_type].metrics.find((x) => x.id === metric); return m && !m.model_dependent; };
  const nodeLevel = (n) => worst(n.diagnostics.filter((d) => independent(n, d.metric)).map((d) => d.level));
  const headline = (n, metric) => {
    const rows = n.metrics.filter((m) => m.metric === metric && m.value !== null);
    rows.sort((a, b) => b.n - a.n || String(a.model || "").localeCompare(String(b.model || "")));
    return rows[0] || null;
  };

  function card(result, station) {
    const by = new Map(result.nodes.map((n) => [n.node, n]));
    const sn = by.get(station.id);
    if (!sn) return "";
    const t = types.integrated_servo;
    const tiles = t.metrics.filter((m) => m.pinned).map((m) => {
      const e = m.model_dependent ? headline(sn, m.id) : sn.metrics.find((x) => x.metric === m.id);
      const value = e ? e.value : null;
      const model = (e && e.model) || "";
      const d = t.diagnostics.find((x) => x.metric === m.id && x.units === "metric");
      const dx = d ? sn.diagnostics.find((x) => x.diagnostic === d.id && (x.model ?? null) === (e ? e.model ?? null : null)) : null;
      const note = value !== null ? `median of ${plural(e.n, "run")} · ${fmt(e.low, "")}–${fmt(e.high, m.unit)}` : ((e && e.why) || m.why_not || "no value");
      // beside a fidelity metric's headline model, every other model that replayed these runs (most runs first)
      let others = "";
      if (m.model_dependent) {
        const rest = sn.metrics.filter((x) => x.metric === m.id && x.value !== null && (x.model || "") !== model)
          .sort((a, b) => b.n - a.n || String(a.model || "").localeCompare(String(b.model || "")));
        if (rest.length) others = `<ul class="s2r-mothers" aria-label="Other models">` + rest.map((x) => {
          const xd = d ? sn.diagnostics.find((y) => y.diagnostic === d.id && (y.model ?? null) === (x.model ?? null)) : null;
          return `<li>${esc(x.model || "")} <span data-node="${esc(station.id)}" data-metric="${esc(m.id)}" data-model="${esc(x.model || "")}" data-value="${raw(x.value)}">`
            + `${esc(fmt(x.value, m.unit))}</span>${xd ? " " + chip(xd.level) : ""} <small>${plural(x.n, "run")}</small></li>`;
        }).join("") + "</ul>";
      }
      return `<div class="s2r-mtile${others ? " s2r-mtile-wide" : ""}"><dt>${esc(m.title)}${model ? ` <small>${esc(model)}</small>` : ""}</dt>`
        + `<dd><span data-node="${esc(station.id)}" data-metric="${esc(m.id)}" data-model="${esc(model)}" data-value="${raw(value)}">${esc(fmt(value, m.unit))}</span>`
        + `${dx ? " " + chip(dx.level) : ""}</dd><small title="${esc(note)}">${esc(note)}</small>${others}</div>`;
    }).join("");
    const c = sn.coverage;
    const cov = `<div class="s2r-mcov" data-coverage-node="${esc(station.id)}" data-coverage-pct="${raw(c.pct)}" data-coverage-visited="${raw(c.visited)}" data-coverage-reachable="${raw(c.reachable)}">`
      + (c.pct !== null ? `<b>${esc(fmt(c.pct, "%"))}</b> of ${c.reachable.toLocaleString("en-US")} reachable cells visited (${c.visited.toLocaleString("en-US")}) · gate ${c.gate_pct} % `
        + `<span class="s2r-v s2r-${c.verdict === "pass" ? "pass" : c.verdict === "fail" ? "fail" : "not_run"}">${esc(c.verdict)}</span>`
        + `<span class="s2r-mbar" role="img" aria-label="${esc(fmt(c.pct, "%"))} covered"><i style="width:${Math.min(100, c.pct)}%"></i><b style="left:${c.gate_pct}%"></b></span>`
        : `<span class="mut">${esc(c.why || "")}</span>`) + "</div>";
    const parts = spec.nodes.filter((n) => n.parent === station.id && by.has(n.id)).map((p) => {
      const pn = by.get(p.id);
      const vals = pn.metrics.filter((m) => m.value !== null && m.family !== "fidelity").map((m) =>
        `${esc(m.title)} <span data-node="${esc(p.id)}" data-metric="${esc(m.metric)}" data-model="" data-value="${raw(m.value)}">${esc(fmt(m.value, m.unit))}</span>`
        + (() => { const d = pn.diagnostics.find((x) => x.metric === m.metric && independent(pn, x.metric)); return d ? " " + chip(d.level) : ""; })());
      return `<li>${dot(nodeLevel(pn))}<b>${esc(p.title.split(": ")[0])}</b> ${vals.map((v) => `<span class="s2r-mval">${v}</span>`).join("") || '<span class="mut">no model-independent value</span>'}</li>`;
    }).join("");
    const lv = nodeLevel(sn);
    return `<section class="s2r-mnode" data-node="${esc(station.id)}" data-level="${esc(lv)}"><h3>${dot(lv, "the worst of its model-independent diagnostics over these runs")}`
      + `${esc(station.device)} <small>${plural(sn.runs, "run")}</small> <a class="s2r-mlink" href="/deployments/${station.id}/">its page</a></h3>`
      + `<dl class="s2r-mtiles">${tiles}</dl>${cov}<ul class="s2r-mparts">${parts}</ul></section>`;
  }

  // the detail tables and the heatmap: data-ui <data-views> fed the computed rows
  function views(id, base, attrs) {
    const host = document.getElementById(id);
    const el = document.createElement("data-views");
    el.id = id.replace("s2r-", "");
    for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
    el.setAttribute("no-url", "");
    host.textContent = "";
    host.appendChild(el);
    el.base = base;
    return el;
  }
  const dxEl = views("s2r-metrics-dx", { views: [{ type: "table", name: "Diagnostics", order: ["level", "station", "entity", "diagnostic", "model", "value", "limits", "runs", "message"],
    display: { level: "status" }, sort: [{ property: "rank", direction: "DESC" }, { property: "station", direction: "ASC" }] }],
    properties: { level: { displayName: "Level" }, station: { displayName: "Station" }, entity: { displayName: "Entity" }, diagnostic: { displayName: "Diagnostic" },
                  model: { displayName: "Model" }, value: { displayName: "Value (median)" }, limits: { displayName: "Limits" }, runs: { displayName: "Runs" },
                  message: { displayName: "What it says" } } }, { toolbar: "compact" });
  const allEl = views("s2r-metrics-all", { views: [{ type: "table", name: "Metrics", order: ["station", "entity", "metric", "pinned", "model", "value", "runs", "why"],
    sort: [{ property: "station", direction: "ASC" }, { property: "order", direction: "ASC" }] }],
    properties: { station: { displayName: "Station" }, entity: { displayName: "Entity" }, metric: { displayName: "Metric" }, pinned: { displayName: "Pinned" },
                  model: { displayName: "Model" }, value: { displayName: "Value (median, min–max)" }, runs: { displayName: "Runs" }, why: { displayName: "Why none" } } },
    { toolbar: "compact" });
  const colour = (css, fallback) => { const s = document.createElement("span"); s.style.color = css; s.hidden = true; document.body.appendChild(s);
    const c = getComputedStyle(s).color; s.remove(); return c || fallback; };
  const QD = ["−100…−50 %", "−50…−25 %", "−25…−10 %", "−10…−5 %", "−5…−2.5 %", "−2.5…−1 %", "±1 %", "1…2.5 %", "2.5…5 %", "5…10 %", "10…25 %", "25…50 %", "50…100 %"];
  let heatEl = null;
  function heatBase() {
    const blue = colour("var(--data-series-1)", "#2a78d6"), empty = colour("var(--bg2, #f1f1ef)", "#f1f1ef"), rule = colour("var(--rule, #ddd)", "#ddd");
    return { views: [{ type: "chart", name: "Coverage", chart: {
      mark: { type: "rect", stroke: rule, strokeWidth: 0.5 },
      width: 168, height: 150,
      encoding: {
        facet: { field: "device", type: "nominal", columns: 4, title: null, sort: { field: "order", op: "min" } },
        x: { field: "q_i", type: "ordinal", title: "q (12 cells over its range)", axis: { labelExpr: "datum.value + 1", labelAngle: 0, labelFontSize: 9 } },
        y: { field: "qd_label", type: "ordinal", sort: QD.slice().reverse(), title: "qd (% of max speed)", axis: { labelFontSize: 9 } },
        color: { field: "share", type: "quantitative", title: "qdd bands visited", scale: { domain: [0, 1], range: [empty, blue] }, legend: { format: ".0%" } },
        tooltip: [{ field: "device", title: "station" }, { field: "q_range", title: "q (deg)" }, { field: "qd_range", title: "qd (rad/s)" },
                  { field: "visited", title: "qdd bands visited" }, { field: "reachable", title: "reachable" }],
      },
      resolve: { scale: { x: "independent" } },
    } }] };
  }
  const stationOrder = new Map(spec.nodes.filter((n) => n.structural === "station").map((n, i) => [n.id, i]));
  function heatRows(result) {
    const rows = [];
    for (const n of result.nodes) {
      const order = stationOrder.get(n.node) ?? 99;
      if (n.entity_type !== "integrated_servo" || !n.coverage.cells) continue;
      const grid = cells.grid[n.device];
      if (!grid) continue;
      const [qe, qde] = [grid.axes[0].edges, grid.axes[1].edges];
      const agg = new Map();
      for (const c of grid.reachable) {
        const [i, j] = c.split(",").map(Number);
        const k = i + "," + j;
        const a = agg.get(k) || { i, j, visited: 0, reachable: 0 };
        a.reachable += 1;
        if (n.coverage.cells.has(c)) a.visited += 1;
        agg.set(k, a);
      }
      const deg = (x) => (x * 180 / Math.PI).toFixed(0);
      for (const a of agg.values()) {
        rows.push({ id: `${n.device}|${a.i}|${a.j}`, device: n.device, order, q_i: a.i, qd_i: a.j, qd_label: QD[a.j], visited: a.visited, reachable: a.reachable,
                    share: a.visited / a.reachable, q_range: `${deg(qe[a.i])}…${deg(qe[a.i + 1])}`, qd_range: `${qde[a.j].toFixed(3)}…${qde[a.j + 1].toFixed(3)}` });
      }
    }
    return rows;
  }

  function limitsText(d) {
    const parts = [];
    for (const [word, lo, hi] of [["warn", d.warn_lo, d.warn_hi], ["error", d.error_lo, d.error_hi]]) {
      if (hi !== null && hi !== undefined) parts.push(`${word} above ${fmt(hi, "")}`);
      if (lo !== null && lo !== undefined) parts.push(`${word} below ${fmt(lo, "")}`);
    }
    return parts.join(" · ") || "set per unit (no value for this unit)";
  }

  const freezeCode = document.querySelector(".s2r-freeze code");
  const freezeNote = document.querySelector(".s2r-freeze-note");
  const MAX_IDS = 400;

  let state = { how: "filtered", ids: [], result: { runs: 0, run_ids: [], nodes: [] } };
  function draw() {
    const result = state.result;
    const title = (id) => (spec.nodes.find((n) => n.id === id) || {}).title || id;
    const stations = spec.nodes.filter((n) => n.structural === "station");
    out.dataset.how = state.how;
    out.dataset.runs = String(result.runs);
    const n = result.runs;
    const word = state.how === "selected" ? `${plural(n, "run")} ticked` : `${plural(n, "run")} ${n === deviceOf.size ? "(every run)" : "the filters leave"}`;
    const sts = new Set(result.nodes.map((x) => x.device));
    out.innerHTML = `<p class="s2r-mhow"><b>${esc(word)}</b> over ${plural(sts.size, "station")}${state.how === "selected" ? " · clear the ticks to go back to the filtered rows" : ""}</p>`
      + `<div class="s2r-mnodes">${stations.map((s) => card(result, s)).join("")}</div>`;
    const dxRows = [], allRows = [];
    let order = 0;
    for (const node of result.nodes) {
      const station = (spec.nodes.find((x) => x.id === node.node) || {}).device;
      for (const d of node.diagnostics) dxRows.push({ id: `${node.node}|${d.diagnostic}|${d.model ?? ""}`, level: d.level, rank: d.rank, station, entity: title(node.node),
        diagnostic: d.title, model: d.model || "", value: d.value === null ? null : { value: d.value, unit: d.unit === "1" ? "" : d.unit }, limits: limitsText(d),
        runs: d.runs, message: d.message || (d.value === null ? "no value from these runs" : d.level === "unknown" ? "its limit has no value for this unit" : "within its limits") });
      for (const m of node.metrics) allRows.push({ id: `${node.node}|${m.metric}|${m.model ?? ""}`, order: order++, station, entity: title(node.node), metric: m.title,
        pinned: m.pinned, model: m.model || "", value: m.value === null ? { value: null, why: m.why } : { value: m.value, low: m.low, high: m.high, n: m.n, unit: m.unit },
        runs: m.n, why: m.value === null ? m.why : "" });
    }
    dxEl.data = dxRows;
    allEl.data = allRows;
    const heat = heatRows(result);
    if (!heatEl) { heatEl = views("s2r-metrics-coverage", heatBase(), { toolbar: "none", status: "off", controls: "off" }); }
    heatEl.data = heat.length ? heat : [];
    if (freezeCode) {
      const ids = result.run_ids;
      if (!ids.length) { freezeCode.textContent = ""; freezeNote.textContent = "No run is in play."; }
      else if (ids.length > MAX_IDS) {
        freezeCode.textContent = `PYTHONPATH=/home/bam/sim2real python3 -m type_cards.report freeze --id my-report --title "..." --question "..." --deployment ${spec.deployment} --preset "station: CAN 11"`;
        freezeNote.textContent = `${ids.length.toLocaleString("en-US")} runs are in play: name them with --select col=value (runs.json columns) or --preset, or narrow to ${MAX_IDS} or fewer for their ids.`;
      } else {
        freezeCode.textContent = `PYTHONPATH=/home/bam/sim2real python3 -m type_cards.report freeze --id my-report --title "..." --question "..." --deployment ${spec.deployment} --runs ${ids.join(",")}`;
        freezeNote.textContent = `${plural(ids.length, "run")}: name the report (--id, --title, --question) before you run it.`;
      }
    }
  }

  function inPlay() {
    const sel = runsEl.selection || [];
    if (sel.length) return { how: "selected", ids: sel.slice() };
    const m = runsEl.model;
    return { how: "filtered", ids: m ? m.rows.map((r) => r.run) : [] };
  }
  let queued = false;
  function update() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      if (!runsEl.model) return;
      const p = inPlay();
      const result = compute(p.ids);
      state = { how: p.how, ids: p.ids.slice().sort(), result };
      draw();
      ready = true;
      root.dataset.ready = "true";
    });
  }
  let ready = false;
  runsEl.addEventListener("data-views-render", update);
  runsEl.addEventListener("data-views-select", update);
  runsEl.addEventListener("data-views-change", update);
  if (runsEl.model) update();

  // presets: a rail filter that picks the same runs as the build's preset of that name (selection.presets); ticks cleared
  for (const b of document.querySelectorAll(".s2r-preset")) {
    b.addEventListener("click", () => {
      runsEl.clearSelection();
      const f = b.dataset.filter;
      runsEl.filters = f ? f : null;
      for (const o of document.querySelectorAll(".s2r-preset")) o.setAttribute("aria-pressed", o === b ? "true" : "false");
    });
  }
  const copy = document.querySelector(".s2r-freeze .s2r-copy");
  if (copy) copy.addEventListener("click", () => { try { navigator.clipboard.writeText(freezeCode.textContent); copy.textContent = "Copied"; } catch (e) { /* no clipboard */ } });

  // ?report=<id>: tick a frozen report's runs (its snapshot's definition), so its rows read live beside its frozen numbers
  const reportId = new URLSearchParams(location.search).get("report");
  if (reportId && /^[a-z0-9-]+$/.test(reportId)) {
    fetch(`${spec.data.reports}${reportId}.json`).then((r) => r.json()).then((snap) => {
      const tick = () => { runsEl.select((snap.report && snap.report.runs) || [], { mode: "replace" }); };
      if (runsEl.model) tick(); else runsEl.addEventListener("data-views-render", tick, { once: true });
    }).catch(() => {});
  }

  window.s2rMetrics = {
    get ready() { return ready; },
    snapshot() {
      // the result as selection.compute writes it (coverage's cells are this page's own working set, left out)
      const result = JSON.parse(JSON.stringify(state.result, (k, v) => (k === "cells" ? undefined : v)));
      return { how: state.how, ids: state.ids.slice(), result };
    },
  };
}
