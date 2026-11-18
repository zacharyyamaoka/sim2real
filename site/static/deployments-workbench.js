/* The Deployments workbench (/deployments/; site/deployments_workbench.py writes its data from sim2real.deployments_page).

   The AI pick of the 2026-11-17 proposal round, spliced (docs/proposals/2026-11-17-deployment-page/): V1 Workbench's frame (the typed tree
   on the left, the picked node's page on the right with tabs, a Table view with a foldable inspector, the 3D), V4's banner, question
   columns and "What changed" mode, V2's round 0 · now · change columns, V3's pulled-apart servo; then, by Zach's "# Ok" (2026-11-17:
   "Performance is what matters at the end of the day ... So performance is first and up center"; "Runs are the atomic unit"), every page
   leads with performance (real vs the target, the goal line drawn) and fidelity (real vs sim) sits under it; a Runs view lists every run
   with its Rerun recording.

   The frame is Obsidian's (Zach 2026-11-17: "the left toolbar sidebar like Obsidian ... 3 primary views could be the Scene View, the
   Sheet view and the Workbench-like view"): the ribbon at the far left switches the views (Deployments; Scene · Sheet · Workbench; Runs),
   the typed tree sits in a collapsible, resizable left sidebar, a right inspector folds. Scene (V3): the 3D is the page, every station
   wearing its performance in place, a servo pulled apart into its parts. Sheet (V2): the nested table, every performance metric as
   round 0 · now · change, the five questions an optional column group, the 3D and the inspector docked. Workbench (V1): the node's page.

   State lives in the URL (?d=<deployment>&n=<node>&view=scene|sheet|runs&tab=...&round=r0|r8&mode=changed&cols=questions&rr=<round>), so
   every view is a link, Back works, and the views share one selection (n) and one round. view=table is the Sheet's old name, still read.
   "r8" is the Now column, whatever round the campaign's latest scorecard holds (see rn()); "r0" is round 0, as found.
   WHY no framework: one tree of 45 nodes and a table of a few hundred runs; plain DOM, like the proposals. */
(function () {
  "use strict";
  var host = document.getElementById("dw");
  if (!host) return;
  var $ = function (id) { return document.getElementById(id); };
  var DATA = null, FX = null, byId = {}, Q = {}, RUNS = null, runsLoading = null;
  var rack3d = null, current = null, treeUI = null, VIEW = "home";
  // the views a deployment opens in; "" (no view in the URL) is the Workbench, so every older link (?d=…&n=…) still opens the node's page
  var VIEWS = { scene: "scene", sheet: "sheet", table: "sheet", runs: "runs" };
  var VIEW_NAME = { home: "Deployments", scene: "Scene", sheet: "Sheet", page: "Workbench", runs: "Runs" };

  // ---- small words ----------------------------------------------------------------------------------------------------------------
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function n(x, d) { return (Math.round(x * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d); }
  function lc(t) { t = String(t || ""); return /^[A-Z][a-z]/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t; }
  function canName(id) { return String(id).replace(/^can(\d+)$/, "CAN $1"); }
  var NS = "s2r.deployments-workbench.";
  function load(k, d) { try { var v = localStorage.getItem(NS + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }
  function save(k, v) { try { if (v == null) localStorage.removeItem(NS + k); else localStorage.setItem(NS + k, JSON.stringify(v)); } catch (e) { /* this visit only */ } }
  var WORD = { pass: "pass", fail: "fails", watch: "outside target, not gating", not_observable: "not observable on this rack", not_run: "not run",
               observed: "observed, no gate", none: "no gates here" };
  var KIND = { gated: "goal gate", counted: "counted gate (in the 180, not the goal)", shown: "shown, not gating", observed: "observed, no gate",
               not_observable: "not observable on this rack" };
  var FAMILY = { performance: ["Performance", "real or sim vs the target: does it do the job"], fidelity: ["Fidelity", "real vs sim: does the twin match"],
                 evidence: ["Evidence", "the ruler and the data the other two stand on"] };
  function dot(st, title) { st = st || "none"; return '<span class="dot ' + esc(st) + '" title="' + esc(title || WORD[st] || st) + '" aria-label="' + esc(title || WORD[st] || st) + '"></span>'; }
  function chip(st, text) { return '<span class="chip ' + esc(st) + '">' + esc(text == null ? (WORD[st] || st) : text) + "</span>"; }
  function code(m) { return m && m.code ? '<span class="code" title="' + esc(m.name) + '">' + esc(m.code) + "</span>" : ""; }
  function fmt(m, v) {
    if (!v || v.value == null) return v && v.status === "not_observable" ? "not observable" : "—";
    var x = v.value, u = m.unit;
    if (u === "°") return n(x, Math.abs(x) < 1 ? 3 : 2) + "°";
    if (u === "mm") return n(x, Math.abs(x) < 0.1 ? 3 : 2) + " mm";
    if (u === "× floor" || u === "× scatter") return n(x, 2) + "×";
    if (u === "%") return (x > 0 ? "+" : "") + n(x, 1) + " %";
    if (u === "of rows") return n(x * 100, 1) + " %";
    if (u === "of top speed") return x > 0 ? n(x, 1) + " of top speed" : "no rung";
    if (u === "") return x ? "met" : "not met";
    if (v.of != null) return x + " of " + v.of + (u === "rungs" || u === "stations" ? " " + u : "");
    if (u.indexOf("of ") === 0) return x + " " + u;
    return String(x) + (u ? " " + u : "");
  }
  function fmtShort(m, v) { return fmt(m, v).replace(" of top speed", "").replace(" rungs", "").replace(" stations", ""); }
  function deg(x, d) { return x == null ? "—" : n(x, d == null ? (Math.abs(x) < 1 ? 2 : 2) : d) + "°"; }
  function mm(x) { return x == null ? "—" : n(x, Math.abs(x) < 0.1 ? 3 : 2) + " mm"; }
  // WHY degrees: Zach reads angles and angular speeds in degrees, never rad (memory feedback_angles_in_degrees); data stays SI.
  function degPerS(radPerS) { return radPerS == null ? "—" : Math.round(radPerS * 180 / Math.PI) + " °/s"; }
  function gateText(m) { return m.gate ? m.gate.text : "no gate"; }

  // ---- the data -----------------------------------------------------------------------------------------------------------------
  function node(id) { return byId[id] || null; }
  function kids(id) { var x = byId[id]; return x ? x.children.map(function (c) { return byId[c]; }) : []; }
  function parent(id) { var x = byId[id]; return x && x.parent ? byId[x.parent] : null; }
  function ancestors(id) { var out = [], p = parent(id); while (p) { out.unshift(p); p = parent(p.id); } return out; }
  function walk(fn, id, depth) { id = id || FX.root; depth = depth || 0; var x = byId[id]; fn(x, depth); x.children.forEach(function (c) { walk(fn, c, depth + 1); }); }
  function stationOf(id) { var x = byId[id]; while (x && x.level !== "station") x = x.parent ? byId[x.parent] : null; return x; }
  function round(rid) { return FX.rounds.filter(function (r) { return r.id === rid; })[0]; }
  function other(rid) { return rid === "r8" ? "r0" : "r8"; }
  // WHY "r8" means "now", whatever round it holds (round 9 on 2026-11-18): the id was round 8's when the page was written, and the URL
  // (?round=r0, the default dropped) and the tests key on it; every label reads the round's own number from the data instead (Zach:
  // "open up that deployment and at a glance see exactly the current state")
  function rn(rid) { var r = FX && round(rid); return r ? "round " + r.round : ""; }
  function scoredDay(rid) { var r = FX && round(rid); return r ? String(r.scored_utc).slice(0, 10) : ""; }
  // a round below now whose scorecard is missing is skipped in the history, and said so, never drawn as if it were there
  function historyGap() {
    var gap = (FX && FX.history_missing) || [];
    return gap.length ? '<p class="caveat dw-histgap">No scorecard for round' + (gap.length > 1 ? "s " : " ") + esc(gap.join(", ")) + ": skipped in the history below, not drawn.</p>" : "";
  }
  function metric(x, mid) { return x ? x.metrics.filter(function (m) { return m.id === mid; })[0] || null : null; }
  function rung(st, rid, f) { return (st.rungs[rid] || []).filter(function (r) { return r.fraction === f; })[0] || {}; }
  function change(m, rid) {
    var a = m.values[other(rid)], b = m.values[rid];
    if (!a || !b || a.value == null || b.value == null) return { dir: "na", word: "" };
    var x = a.value, y = b.value;
    if (m.unit === "%") { x = Math.abs(x); y = Math.abs(y); }
    if (Math.abs(x - y) < 1e-9) return { dir: "flat", word: "same" };
    var better = m.better === "higher" ? y > x : y < x;
    if (rid === "r0") better = !better;
    return { dir: better ? "up" : "down", word: better ? "better" : "worse" };
  }
  function arrow(c) { return c.dir === "up" ? '<span class="up" title="better">▲ better</span>' : c.dir === "down" ? '<span class="down" title="worse">▼ worse</span>' : c.dir === "flat" ? '<span class="flat">= same</span>' : ""; }
  // the worst status of a node's metrics in one family (gated and shown gates only; a shown miss is "watch")
  function familyStatus(x, fam, rid) {
    var st = "none", rank = { fail: 3, watch: 2, pass: 1 };
    x.metrics.forEach(function (m) {
      if (m.family !== fam) return;
      var v = m.values[rid]; if (!v) return;
      var s = v.status;
      if (m.kind === "shown" && s === "fail") s = "watch";
      if ((m.kind === "gated" || m.kind === "shown") && (rank[s] || 0) > (rank[st] || 0)) st = s;
      else if (st === "none" && s === "not_observable") st = "not_observable";
    });
    return st;
  }

  // ---- state in the URL ------------------------------------------------------------------------------------------------------------
  function state() {
    var p = new URLSearchParams(location.search);
    var dep = p.get("d");
    return { dep: dep, node: p.get("n") || (FX ? FX.root : "rack"), view: p.get("view") || "", tab: p.get("tab") || "", round: p.get("round") === "r0" ? "r0" : "r8",
             mode: p.get("mode") === "changed" ? "changed" : "", cols: p.get("cols") === "questions" ? "questions" : "perf", rr: p.get("rr"),
             st: p.get("st") || "", q: p.get("q") || "", raw: p };
  }
  function href(patch) {
    var s = state(), p = new URLSearchParams(location.search);
    Object.keys(patch || {}).forEach(function (k) {
      var key = { node: "n", dep: "d" }[k] || k, v = patch[k];
      if (key === "view" && v === "page") v = "";
      if (v == null || v === "" || (key === "round" && v === "r8") || (key === "n" && FX && v === FX.root)) p.delete(key); else p.set(key, v);
    });
    if (!p.get("d")) { return location.pathname; }
    var qs = p.toString();
    return location.pathname + (qs ? "?" + qs : "");
  }
  function go(patch, replace) {
    var h = href(patch);
    if (h === location.pathname + location.search) return false;
    if (replace) history.replaceState(null, "", h); else history.pushState(null, "", h);
    render();
    return true;
  }
  addEventListener("popstate", function () { render(); });
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest("a[data-go]");
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    history.pushState(null, "", a.getAttribute("href"));
    render();
  });
  function link(patch, text, cls) { return '<a data-go href="' + esc(href(patch)) + '"' + (cls ? ' class="' + cls + '"' : "") + ">" + text + "</a>"; }

  // ---- icons --------------------------------------------------------------------------------------------------------------------------
  var P = {
    deployment: '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M5 3v10M11 3v10"/>',
    pendulum_arm_1dof: '<circle cx="8" cy="4" r="2"/><path d="M8 6l3 7"/><circle cx="11.3" cy="13" r="1.4"/>',
    integrated_servo: '<rect x="2" y="5" width="8" height="6" rx="1"/><path d="M10 7h2.5M10 9h2.5"/><circle cx="13.5" cy="8" r="1.5"/>',
    foc_controller: '<rect x="3.5" y="3.5" width="9" height="9" rx="1"/><path d="M6 1.5v2M10 1.5v2M6 12.5v2M10 12.5v2M1.5 6h2M1.5 10h2M12.5 6h2M12.5 10h2"/>',
    bldc_motor: '<circle cx="8" cy="8" r="5.5"/><circle cx="8" cy="8" r="1.6"/>',
    gearbox: '<circle cx="8" cy="8" r="3.2"/><path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M3.6 12.4L5 11M11 5l1.4-1.4"/>',
    encoder: '<circle cx="8" cy="8" r="5.5"/><path d="M8 8l3-3M8 2.5v1.5"/>',
    rigid_link: '<rect x="2" y="6.5" width="12" height="3" rx="1.5"/><circle cx="4" cy="8" r=".8"/><circle cx="12" cy="8" r=".8"/>',
    depth_camera: '<rect x="1.5" y="5" width="13" height="6.5" rx="1.5"/><circle cx="5.5" cy="8.2" r="1.6"/><circle cx="10.5" cy="8.2" r="1.6"/>',
  };
  function icon(t) { return '<span class="ic"><svg viewBox="0 0 16 16">' + (P[t] || P.deployment) + "</svg></span>"; }
  var SVG = {
    collapse: '<svg viewBox="0 0 16 16"><path d="M4 6l4 3 4-3M4 10l4 3 4-3"/></svg>',
    expand: '<svg viewBox="0 0 16 16"><path d="M4 9l4-3 4 3M4 5l4-3 4 3"/></svg>',
    search: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>',
    twisty: '<svg viewBox="0 0 12 12"><path d="M4 2.5L7.5 6 4 9.5"/></svg>',
    tree: '<svg viewBox="0 0 16 16"><path d="M3 3h4M5 3v9h4M5 7.5h4"/><rect x="9" y="6" width="5" height="3" rx=".8"/><rect x="9" y="10.5" width="5" height="3" rx=".8"/></svg>',
    close: '<svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    side: '<svg viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M10 2.5v11"/></svg>',
  };

  // ---- the splitter: drag to resize, remembered, double-click restores ----------------------------------------------------------
  function sash(el, target, opt) {
    var key = "size." + opt.key, horiz = !!opt.horizontal, prop = horiz ? "height" : "width";
    function apply(px) { px = Math.max(opt.min || 120, Math.min(opt.max || 1200, px)); target.style[prop] = px + "px"; target.style.flex = "none"; if (opt.onResize) opt.onResize(px); return px; }
    var saved = load(key, null);
    apply(saved != null ? saved : opt.dflt);
    if (el.dataset.wired) return;
    el.dataset.wired = "1";
    el.setAttribute("role", "separator");
    el.setAttribute("aria-orientation", horiz ? "horizontal" : "vertical");
    el.title = "Drag to resize · double-click to reset";
    el.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      var start = horiz ? ev.clientY : ev.clientX, size = target.getBoundingClientRect()[prop];
      el.setPointerCapture(ev.pointerId);
      el.classList.add("dragging");
      document.body.classList.add(horiz ? "dw-resizing-h" : "dw-resizing");
      function move(e) { var d = (horiz ? e.clientY : e.clientX) - start; apply(size + (opt.invert ? -d : d)); }
      function up() {
        el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up);
        el.classList.remove("dragging"); document.body.classList.remove("dw-resizing", "dw-resizing-h");
        save(key, Math.round(target.getBoundingClientRect()[prop]));
      }
      el.addEventListener("pointermove", move); el.addEventListener("pointerup", up);
    });
    el.addEventListener("dblclick", function () { save(key, null); apply(opt.dflt); });
  }

  // ---- the answers: performance first, fidelity under it ------------------------------------------------------------------------
  function perfLine(x, rid) {
    // a station: how far up the speed ladder it does its job, and the numbers at the goal's rung
    var up = metric(x, "passes_up_to"), v = up.values[rid];
    var r = rung(x, rid, 0.9), t = FX.thresholds;
    var head = v.value > 0 ? "Tracks and stops up to " + n(v.value, 1) + " of top speed" : "Does not track at any rung";
    var worst = r.stop_tool_max_mm;
    var detail = "At 0.9 of top speed: tracking " + deg(r.tracking_rms_deg) + " RMS, " + deg(r.tracking_peak_deg) + " peak · tip stop " + mm(r.stop_tool_mm) + " median" +
      (worst != null ? ", worst " + mm(worst) : "") + " (goals ≤ " + t.tracking_rms_deg + "°, ≤ " + t.tracking_peak_deg + "°, ≤ " + t.stop_tool_mm + " mm).";
    var overs = (x.rungs[rid] || []).filter(function (rr) { return rr.stop_tool_mm != null && rr.stop_tool_mm <= t.stop_tool_mm && rr.stop_tool_max_mm != null && rr.stop_tool_max_mm > t.stop_tool_mm; }).map(function (rr) { return rr.fraction; });
    if (overs.length) detail += " Worst single stop over 1 mm at the " + overs.map(function (f) { return n(f, 1); }).join(", ") + " rung" + (overs.length > 1 ? "s" : "") + " (the gate reads the median).";
    return { status: v.status, head: head + (v.status === "pass" ? "" : " · goal ≥ 0.9"), detail: detail };
  }
  function fidLine(x, rid) {
    var m = metric(x, "twin_over_floor") || metric(x, "T2") || metric(x, "stations_twinned");
    if (!m) {
      var fs = x.metrics.filter(function (mm) { return mm.family === "fidelity"; });
      if (!fs.length) return null;
      m = fs.filter(function (mm) { return mm.values[rid].status === "fail"; })[0] || fs[0];
    }
    var v = m.values[rid], o = m.values[other(rid)];
    var st = m.kind === "shown" && v.status === "fail" ? "watch" : v.status;
    var head = m.name + " " + fmt(m, v) + (m.gate ? " · goal " + gateText(m) : "") + " · " + (WORD[st] || st);
    return { status: st, head: head, detail: (v.detail || "") + (o ? " · " + round(other(rid)).label.toLowerCase() + ": " + fmt(m, o) : "") };
  }
  function rackAnswer(x, rid) {
    var perf = x.performance[rid], t = FX.thresholds;
    var tracking = metric(x, "stations_tracking").values[rid];
    var rows = [];
    var head = tracking.value === 6 ? "All six stations track and stop within the gates up to 0.9 of top speed" : tracking.value + " of 6 stations track and stop up to 0.9 of top speed";
    rows.push({ cls: "lead " + (tracking.value === 6 ? "pass" : "fail"), lab: "Performance", st: tracking.value === 6 ? "pass" : "fail", head: head,
                detail: perf.passed + " of " + perf.of + " real performance gates (tracking and tip stop, every rung)" + (other(rid) ? " · " + round(other(rid)).label.toLowerCase() + ": " + x.performance[other(rid)].passed : "") + "." });
    var gap = perf.gaps[0];
    if (gap) {
      var vals = gap.stations.map(function (s) { return gap.values[s]; });
      var key = gap.gate === "tracking" ? "tracking_rms_deg" : "stop_tool_mm";
      var lo = Math.min.apply(null, vals.map(function (v) { return v[key]; })), hi = Math.max.apply(null, vals.map(function (v) { return v[key]; }));
      var where = (gap.fraction === 1 ? "full speed (1.0 of top speed)" : gap.fraction + " of top speed");
      var names = gap.stations.length === 6 ? "every station" : gap.stations.map(canName).join(", ");
      var what = gap.gate === "tracking" ? "tracking RMS " + deg(lo) + "–" + deg(hi) + " (goal ≤ " + t.tracking_rms_deg + "°)" : "tip stop " + mm(lo) + "–" + mm(hi) + " (goal ≤ " + t.stop_tool_mm + " mm)";
      rows.push({ cls: "watch", lab: "Top gap", st: "watch", head: "At " + where + ", " + gap.gate + " misses on " + names, detail: what + (perf.gaps.length > 1 ? " · " + (perf.gaps.length - 1) + " more failing cell group" + (perf.gaps.length > 2 ? "s" : "") + " in the grid below." : "."), go: gap.stations.length === 1 ? gap.stations[0] : null });
    }
    (perf.worst_stops_over || []).forEach(function (w) {
      var st = node(w.station);
      rows.push({ cls: "", lab: "Worst stop", st: "watch", head: canName(w.station) + "'s worst stop is over 1 mm at the " + w.rungs.map(function (f) { return n(f, 1); }).join(", ") + " rung" + (w.rungs.length > 1 ? "s" : ""),
                  detail: "The gate reads the median of a rung's stops (" + (st ? (st.rungs[rid] || []).filter(function (r) { return w.rungs.indexOf(r.fraction) >= 0; }).map(function (r) { return mm(r.stop_tool_mm); }).join(", ") : "") + " there); the worst: " +
                    (st ? (st.rungs[rid] || []).filter(function (r) { return w.rungs.indexOf(r.fraction) >= 0; }).map(function (r) { return mm(r.stop_tool_max_mm); }).join(", ") : "") + ".", go: w.station });
    });
    var stops = x.stops[rid];
    if (stops && stops.question) {
      var q = Q[stops.question], names2 = stops.stations.map(canName).join(", ");
      var lead = stops.stations.length === 1 ? node(stops.stations[0]) : null, lm = lead ? metric(lead, lead.questions[rid][stops.question].metric) : null;
      // the goal's miss, named by the family its question belongs to: Twin is fidelity, Job performance, the first three the evidence
      var lab = { twin: "Fidelity", job: "Performance", floor: "Evidence", data: "Evidence", routines: "Evidence" }[stops.question];
      var each = stops.stations.map(function (s) { var k = node(s), km = metric(k, k.questions[rid][stops.question].metric); return canName(s) + " " + (km ? fmtShort(km, km.values[rid]) : ""); }).join(" · ");
      rows.push({ cls: "fid fail", lab: lab, st: "fail",
                  head: (stops.stations.length === 1 ? "One thing stops the campaign goal: " : "The campaign goal stops at " + q.name + ": ") + names2 + (lead ? " (" + lead.line + ") · " + q.name + " " + fmt(lm, lm.values[rid]) : ""),
                  detail: lm ? lm.name + " · goal " + gateText(lm) + " · " + round(other(rid)).label.toLowerCase() + ": " + fmt(lm, lm.values[other(rid)]) + " · " + (lm.values[rid].detail || "") : q.ask + " " + each, go: lead ? lead.id : null });
    } else if (x.verdict[rid].status === "pass") {
      rows.push({ cls: "fid pass", lab: "Goal", st: "pass", head: "The campaign goal is met", detail: "Every station tracks to 0.9 of top speed and its twin passes at every rung." });
    }
    return rows;
  }
  function answerRows(x, rid) {
    if (x.level === "deployment") return rackAnswer(x, rid);
    var rows = [];
    if (x.level === "station") {
      var p = perfLine(x, rid);
      rows.push({ cls: "lead " + p.status, lab: "Performance", st: p.status, head: p.head, detail: p.detail });
      var f = fidLine(x, rid);
      if (f) rows.push({ cls: "fid " + f.status, lab: "Fidelity", st: f.status, head: f.head, detail: f.detail });
      return rows;
    }
    if (!x.metrics.length) return [{ cls: "lead none", lab: "This level", st: "none", head: "No gates of its own", detail: "Judged " + x.judged_at + "." }];
    ["performance", "fidelity"].forEach(function (fam) {
      var ms = x.metrics.filter(function (m) { return m.family === fam; });
      if (!ms.length) return;
      var seen = ms.filter(function (m) { return m.values[rid].status !== "not_observable" && m.values[rid].status !== "not_run"; });
      var hidden = ms.filter(function (m) { return m.values[rid].status === "not_observable"; });
      var st = familyStatus(x, fam, rid);
      var lead = seen.filter(function (m) { return m.values[rid].status === "fail"; })[0] || seen[0];
      var head = lead ? lead.name + " " + fmt(lead, lead.values[rid]) + (lead.gate ? " · goal " + gateText(lead) : "") : hidden.length ? "Not observable on this rack" : "Not run in this round";
      var detail = (lead && lead.values[rid].detail ? lead.values[rid].detail + ". " : "") +
        (hidden.length ? hidden.map(function (m) { return (m.code ? m.code + " " : "") + lc(m.name) + ": " + (m.values[rid].detail || "not observable on this rack"); }).join("; ") + "." : "") +
        (!lead && !hidden.length ? ms.map(function (m) { return m.values[rid].detail; }).filter(Boolean).join(" · ") : "");
      rows.push({ cls: (rows.length ? "fid " : "lead ") + (lead ? st : "none"), lab: FAMILY[fam][0], st: lead ? st : hidden.length ? "not_observable" : "not_run", head: head, detail: detail });
    });
    return rows;
  }
  function answerHTML(x, rid) {
    return '<div class="dw-answer">' + answerRows(x, rid).map(function (r) {
      var inner = dot(r.st) + '<span class="lab">' + esc(r.lab) + '</span><div><div class="a-head">' + esc(r.head) + '</div><div class="a-detail">' + esc(r.detail) + "</div></div>";
      return r.go ? '<button class="row ' + r.cls + '" data-node="' + esc(r.go) + '" title="Open ' + esc(canName(r.go)) + '">' + inner + "</button>" : '<div class="row ' + r.cls + '">' + inner + "</div>";
    }).join("") + "</div>";
  }
  // one line for a child row or a tree tooltip
  function oneLine(x, rid) {
    var r = answerRows(x, rid)[0];
    var f = answerRows(x, rid)[1];
    return r.head + (f && f.st !== "pass" ? " · " + f.lab.toLowerCase() + ": " + f.head : "");
  }
  function lineStatus(x, rid) {
    var v = x.verdict[rid].status;
    return v === "none" ? (x.metrics.length ? (x.metrics.some(function (m) { return m.values[rid].status === "not_observable"; }) ? "not_observable" : "not_run") : "none") : v;
  }

  // ---- the typed tree ------------------------------------------------------------------------------------------------------------
  function Tree(el, opts) {
    var self = this, selected = null, filter = "";
    var folded = new Set(load("tree.folded", FX.nodes.filter(function (x) { return x.level === "servo"; }).map(function (x) { return x.id; })));
    el.innerHTML = '<div class="dw-tree"><div class="dw-tree-tools"><span class="ic">' + SVG.tree + '</span><b>Typed component tree</b>' +
      '<button class="dw-iconbtn" data-t="collapse" title="Collapse all">' + SVG.collapse + '</button><button class="dw-iconbtn" data-t="expand" title="Expand all">' + SVG.expand + "</button></div>" +
      '<label class="dw-tree-find">' + SVG.search + '<input type="search" placeholder="Search parts, types, CAN ids…" aria-label="Search the typed tree"></label>' +
      '<div class="dw-tree-sec"><span>Components</span><span class="cnts"></span></div><div class="dw-tree-body" tabindex="0" role="tree" aria-label="typed component tree"></div><div class="dw-tnone" hidden>No part matches.</div></div>';
    var body = el.querySelector(".dw-tree-body"), input = el.querySelector("input"), none = el.querySelector(".dw-tnone"), cnts = el.querySelector(".cnts");
    function worse(a, b) { var o = { fail: 4, watch: 2, pass: 1 }; return (o[a] || 0) > (o[b] || 0); }
    function text(x) { return (x.short + " " + x.title + " " + x.type.name + " " + (x.unit || "") + " " + (x.line || "")).toLowerCase(); }
    function match(x) { if (!filter) return true; if (text(x).indexOf(filter.toLowerCase()) >= 0) return true; return x.children.some(function (c) { return match(byId[c]); }); }
    function li(x) {
      var r = opts.round(), v = lineStatus(x, r), k = x.children.length, open = !folded.has(x.id) || !!filter;
      var below = k && !open && worse(x.rollup[r], x.verdict[r].status) ? '<span title="something below is worse">' + dot(x.rollup[r]) + "</span>" : "";
      var name = esc(x.short);
      if (filter) { var re = new RegExp("(" + filter.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"); name = name.replace(re, "<mark>$1</mark>"); }
      var h = '<li role="treeitem" data-id="' + esc(x.id) + '"' + (k ? ' aria-expanded="' + open + '"' : "") + ' aria-selected="' + (selected === x.id) + '">' +
        '<div class="dw-trow" title="' + esc(x.title + " · " + oneLine(x, r)) + '"><span class="tw"' + (k ? ' data-tw="1"' : "") + ">" + (k ? SVG.twisty : "") + "</span>" + icon(x.type.id) +
        '<span class="tname">' + name + '</span><span class="tline">' + esc(x.line || x.type.name) + '</span><span class="tmeta">' + below + dot(v, WORD[v] + (x.verdict[r].first ? " at " + Q[x.verdict[r].first].name : "")) + "</span></div>";
      if (k) h += '<ul role="group">' + x.children.map(function (c) { return match(byId[c]) ? li(byId[c]) : ""; }).join("") + "</ul>";
      return h + "</li>";
    }
    self.render = function () {
      var root = byId[FX.root];
      body.innerHTML = match(root) ? "<ul>" + li(root) + "</ul>" : "";
      none.hidden = !!body.textContent.trim();
      var r = opts.round(), c = { pass: 0, watch: 0, fail: 0 };
      FX.nodes.forEach(function (x) { var s = x.verdict[r].status; if (c[s] != null) c[s] += 1; });
      cnts.innerHTML = '<span class="cnt" title="nodes passing">' + dot("pass") + c.pass + '</span><span class="cnt" title="outside a target that does not gate">' + dot("watch") + c.watch + '</span><span class="cnt" title="a goal gate fails">' + dot("fail") + c.fail + "</span>";
    };
    self.select = function (id) {
      selected = id;
      ancestors(id).forEach(function (a) { folded.delete(a.id); });
      // WHY: picking a servo opens it, so its driver, motor, gearbox and encoder show (V3's pulled-apart servo, in the tree too)
      if (byId[id] && byId[id].level === "servo") folded.delete(id);
      self.render();
      var row = body.querySelector('li[data-id="' + CSS.escape(id) + '"] > .dw-trow');
      if (row) row.scrollIntoView({ block: "nearest" });
    };
    function persist() { save("tree.folded", Array.from(folded)); }
    function rows() { return Array.prototype.slice.call(body.querySelectorAll("li")).filter(function (l) { return l.offsetParent !== null; }); }
    body.addEventListener("click", function (ev) {
      var l = ev.target.closest("li"); if (!l) return;
      var id = l.getAttribute("data-id");
      if (ev.target.closest("[data-tw]")) { if (folded.has(id)) folded.delete(id); else folded.add(id); persist(); self.render(); return; }
      opts.onSelect(id);
    });
    body.addEventListener("keydown", function (ev) {
      var all = rows(), at = all.findIndex(function (l) { return l.getAttribute("data-id") === selected; }), cur = all[at];
      function to(l) { if (l) { ev.preventDefault(); opts.onSelect(l.getAttribute("data-id")); } }
      if (ev.key === "ArrowDown") to(all[at + 1]);
      else if (ev.key === "ArrowUp") to(all[at - 1]);
      else if (ev.key === "Home") to(all[0]);
      else if (ev.key === "End") to(all[all.length - 1]);
      else if (ev.key === "ArrowRight" && cur && cur.hasAttribute("aria-expanded")) { ev.preventDefault(); if (folded.has(selected)) { folded.delete(selected); persist(); self.render(); } else to(all[at + 1]); }
      else if (ev.key === "ArrowLeft" && cur) { ev.preventDefault(); if (cur.getAttribute("aria-expanded") === "true") { folded.add(selected); persist(); self.render(); } else { var p = parent(selected); if (p) opts.onSelect(p.id); } }
    });
    el.querySelector('[data-t="collapse"]').addEventListener("click", function () { FX.nodes.forEach(function (x) { if (x.children.length && x.id !== FX.root) folded.add(x.id); }); persist(); self.render(); });
    el.querySelector('[data-t="expand"]').addEventListener("click", function () { folded.clear(); persist(); self.render(); });
    input.addEventListener("input", function () { filter = input.value.trim(); self.render(); });
    input.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { input.value = ""; filter = ""; self.render(); } });
    self.render();
  }

  // ---- charts: the goal line drawn ---------------------------------------------------------------------------------------------------
  // a value up the speed ladder, round 0 dashed under the round shown; the goal band and line ("GOOD ≤ 0.5°", as on W&B)
  var RUNG_KEYS = {
    tracking_rms_deg: { name: "Tracking RMS", unit: "°", gate: function () { return FX.thresholds.tracking_rms_deg; } },
    tracking_peak_deg: { name: "Tracking peak", unit: "°", gate: function () { return FX.thresholds.tracking_peak_deg; } },
    stop_tool_mm: { name: "Tip stop, median", unit: "mm", gate: function () { return FX.thresholds.stop_tool_mm; } },
    stop_tool_max_mm: { name: "Tip stop, worst", unit: "mm", gate: function () { return FX.thresholds.stop_tool_mm; }, note: "not the gate" },
  };
  function goalText(g, unit) { return "GOOD ≤ " + g + (unit === "°" ? "°" : " " + unit); }
  function rungPlot(st, key, rid) {
    var W = 340, H = 170, L = 40, R = 12, T = 36, B = 26;
    var spec = RUNG_KEYS[key], gate = spec.gate(), o = other(rid);
    var now = (st.rungs[rid] || []).map(function (r) { return r[key]; }).filter(function (x) { return x != null; });
    var top = Math.max(gate * 2, (now.length ? Math.max.apply(null, now) : gate) * 1.15);
    function X(f) { return L + (f - 0.2) / 0.8 * (W - L - R); }
    function Y(v) { return T + (1 - Math.min(v, top) / top) * (H - T - B); }
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(spec.name + " up the speed ladder") + '">';
    s += '<rect x="' + L + '" y="' + Y(gate) + '" width="' + (W - L - R) + '" height="' + (H - B - Y(gate)) + '" fill="var(--pass)" opacity=".08"/>';
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(gate) + '" y2="' + Y(gate) + '" stroke="var(--pass)" stroke-dasharray="5 3" stroke-width="1.3"/>';
    s += '<text x="' + (W - R) + '" y="' + (Y(gate) - 4) + '" text-anchor="end" font-size="10.5" font-weight="650" fill="var(--pass)">' + goalText(gate, spec.unit) + "</text>";
    [0, top / 2, top].forEach(function (t) { s += '<text x="' + (L - 5) + '" y="' + (Y(t) + 3.5) + '" text-anchor="end" font-size="10" fill="var(--ink3)">' + (t < 1 ? t.toFixed(2) : t.toFixed(1)) + "</text>"; });
    [0.2, 0.4, 0.6, 0.8, 0.9, 1.0].forEach(function (f) { s += '<text x="' + X(f) + '" y="' + (H - 9) + '" text-anchor="middle" font-size="10" fill="var(--ink3)">' + n(f, 1) + "</text>"; });
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + (H - B) + '" y2="' + (H - B) + '" stroke="var(--rule)"/>';
    [o, rid].forEach(function (r) {
      var pts = (st.rungs[r] || []).filter(function (x) { return x[key] != null; });
      var col = r === rid ? "var(--real)" : "var(--was)";
      if (pts.length > 1) s += '<polyline fill="none" stroke="' + col + '" stroke-width="' + (r === rid ? 2 : 1.4) + '"' + (r !== rid ? ' stroke-dasharray="4 3"' : "") + ' points="' + pts.map(function (x) { return X(x.fraction) + "," + Y(x[key]); }).join(" ") + '"/>';
      pts.forEach(function (x) {
        var bad = x[key] > gate;
        s += '<circle cx="' + X(x.fraction) + '" cy="' + Y(x[key]) + '" r="' + (r === rid ? 3.4 : 2.6) + '" fill="' + (r === rid ? (bad ? "var(--fail)" : col) : "var(--bg)") + '" stroke="' + (r === rid && bad ? "var(--fail)" : col) + '" stroke-width="1.4"><title>' + esc(round(r).label + " · " + x.fraction + " rung · " + x[key] + " " + spec.unit) + "</title></circle>";
        if (x[key] > top) s += '<text x="' + X(x.fraction) + '" y="' + (T - 5) + '" text-anchor="middle" font-size="9.5" fill="var(--was)">↑' + (x[key] < 10 ? x[key].toFixed(1) : Math.round(x[key])) + "</text>";
      });
    });
    s += '<text x="4" y="14" font-size="12" font-weight="650" fill="var(--ink)">' + esc(spec.name) + ' <tspan fill="var(--ink3)" font-weight="400">' + esc(spec.unit) + (spec.note ? " · " + esc(spec.note) : "") + "</tspan></text>";
    return s + "</svg>";
  }
  function legend(rid) {
    return '<span class="dw-lg"><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--was)" stroke-dasharray="4 3" stroke-width="1.4"/></svg> ' + esc(round(other(rid)).label + " · " + round(other(rid)).long) +
      ' · <svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--real)" stroke-width="2"/></svg> ' + esc(round(rid).label + " · " + round(rid).long) +
      ' · <svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--pass)" stroke-dasharray="5 3" stroke-width="1.3"/></svg> the goal · x: the fraction of top speed</span>';
  }
  // round by round (every scored round up to now): one line per station at the goal's rung, log scale, the goal line drawn; red points miss it
  var HIST_KEYS = {
    tracking_rms_09: { name: "Tracking RMS at 0.9 of top speed", unit: "°", gate: function () { return FX.thresholds.tracking_rms_deg; } },
    stop_09: { name: "Tip stop at 0.9 of top speed, median", unit: "mm", gate: function () { return FX.thresholds.stop_tool_mm; } },
    stop_max_09: { name: "Tip stop at 0.9 of top speed, worst", unit: "mm", gate: function () { return FX.thresholds.stop_tool_mm; } },
  };
  function historyPlot(key, only) {
    var hist = FX.history || [], spec = HIST_KEYS[key], gate = spec.gate();
    var W = 640, H = 270, L = 46, R = 112, T = 34, B = 30;
    var sids = only ? [only] : ["can1", "can11", "can12", "can13", "can14", "can15"];
    var vals = [];
    hist.forEach(function (h) { sids.forEach(function (s) { var v = h.stations[s][key]; if (v != null && v > 0) vals.push(v); }); });
    if (!vals.length) return "";
    var lo = Math.min(gate / 4, Math.min.apply(null, vals)), hi = Math.max(gate * 2, Math.max.apply(null, vals));
    var l0 = Math.floor(Math.log10(lo)), l1 = Math.ceil(Math.log10(hi));
    function X(i) { return L + i / Math.max(1, hist.length - 1) * (W - L - R); }
    function Y(v) { return T + (1 - (Math.log10(Math.max(v, Math.pow(10, l0))) - l0) / (l1 - l0)) * (H - T - B); }
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="' + esc(spec.name + ", round by round") + '">';
    s += '<rect x="' + L + '" y="' + Y(gate) + '" width="' + (W - L - R) + '" height="' + (H - B - Y(gate)) + '" fill="var(--pass)" opacity=".05"/>';
    for (var e = l0; e <= l1; e++) {
      s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(Math.pow(10, e)) + '" y2="' + Y(Math.pow(10, e)) + '" stroke="var(--rule2)"/>';
      s += '<text x="' + (L - 6) + '" y="' + (Y(Math.pow(10, e)) + 4) + '" text-anchor="end" font-size="11.5" fill="var(--ink3)">' + Math.pow(10, e) + "</text>";
    }
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(gate) + '" y2="' + Y(gate) + '" stroke="var(--pass)" stroke-dasharray="5 3" stroke-width="1.4"/>';
    s += '<text x="' + (L + 4) + '" y="' + (Y(gate) - 6) + '" font-size="12.5" font-weight="700" fill="var(--pass)">' + goalText(gate, spec.unit) + "</text>";
    hist.forEach(function (h, i) { s += '<text x="' + X(i) + '" y="' + (H - 11) + '" text-anchor="middle" font-size="11.5" fill="var(--ink3)">' + h.round + "</text>"; });
    s += '<text x="' + (W - R + 6) + '" y="' + (H - 11) + '" text-anchor="start" font-size="11.5" fill="var(--ink3)">round</text>';
    var ends = [];
    sids.forEach(function (sid) {
      var pts = hist.map(function (h, i) { return { i: i, v: h.stations[sid][key], r: h.round }; }).filter(function (p) { return p.v != null && p.v > 0; });
      if (!pts.length) return;
      var hot = only || sid === (state().node || "");
      s += '<polyline fill="none" stroke="var(--ink2)" stroke-opacity="' + (hot ? 0.95 : 0.45) + '" stroke-width="' + (hot ? 2 : 1.2) + '" points="' + pts.map(function (p) { return X(p.i) + "," + Y(p.v); }).join(" ") + '"/>';
      pts.forEach(function (p) {
        s += '<circle cx="' + X(p.i) + '" cy="' + Y(p.v) + '" r="3.2" fill="' + (p.v <= gate ? "var(--pass)" : "var(--fail)") + '"><title>' + esc(canName(sid) + " · round " + p.r + " · " + (spec.unit === "°" ? deg(p.v) : mm(p.v))) + "</title></circle>";
      });
      var last = pts[pts.length - 1];
      ends.push({ y: Y(last.v), text: canName(sid) + " " + (spec.unit === "°" ? deg(last.v) : mm(last.v)), ok: last.v <= gate });
    });
    // the end labels, read without a legend: spread 13 px apart, kept inside the plot
    ends.sort(function (a, b) { return a.y - b.y; });
    for (var k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 13) ends[k].y = ends[k - 1].y + 13;
    var over = ends.length ? ends[ends.length - 1].y - (H - B - 4) : 0;
    if (over > 0) ends.forEach(function (en) { en.y -= over; });
    ends.forEach(function (en) { s += '<text x="' + (W - R + 6) + '" y="' + (en.y + 4) + '" font-size="11.5" fill="' + (en.ok ? "var(--ink2)" : "var(--fail)") + '">' + esc(en.text) + "</text>"; });
    s += '<text x="4" y="16" font-size="13" font-weight="650" fill="var(--ink)">' + esc(spec.name) + ' <tspan fill="var(--ink3)" font-weight="400">' + esc(spec.unit) + ", log scale</tspan></text>";
    return s + "</svg>";
  }

  // ---- the stations x speed grid (where every station stands at every rung, the round shown) -------------------------------------
  var GRID = { tracking_rms_deg: ["Tracking RMS", "°", "tracking_rms_deg"], tracking_peak_deg: ["Tracking peak", "°", "tracking_peak_deg"],
               stop_tool_mm: ["Tip stop, median", "mm", "stop_tool_mm"], stop_tool_max_mm: ["Tip stop, worst", "mm", "stop_tool_mm"] };
  function grid(rid, key) {
    var t = FX.thresholds, g = GRID[key], gate = t[g[2]];
    var sts = kids(FX.root).filter(function (x) { return x.level === "station"; });
    var h = '<table class="dw-grid2"><thead><tr><th class="st">Station</th>' + [0.2, 0.4, 0.6, 0.8, 0.9, 1.0].map(function (f) { return "<th>" + n(f, 1) + "</th>"; }).join("") + "</tr></thead><tbody>";
    sts.forEach(function (st) {
      h += '<tr><td class="st">' + link({ node: st.id, view: "", tab: "" }, "<b>" + esc(st.short) + "</b>") + " <small>" + esc(st.line) + "</small></td>" + [0.2, 0.4, 0.6, 0.8, 0.9, 1.0].map(function (f) {
        var r = rung(st, rid, f), v = r[key];
        if (v == null) return '<td class="na" title="not measured">—</td>';
        var ok = v <= gate, worst = key === "stop_tool_max_mm";
        var cls = worst ? (ok ? "" : "over") : ok ? "" : "fail";
        var txt = g[1] === "°" ? deg(v) : mm(v);
        return '<td class="' + cls + '" data-node="' + esc(st.id) + '" title="' + esc(st.short + " · " + f + " of top speed (" + degPerS(r.speed_rad_s) + ") · " + g[0] + " " + txt + " · goal ≤ " + gate + " " + g[1] + (worst ? " (not the gate: it reads the median)" : "")) + '">' + esc(txt) + "</td>";
      }).join("") + "</tr>";
    });
    return h + "</tbody></table>";
  }

  // ---- metric tables: Round 0 · Now · Change, by family ------------------------------------------------------------------------------
  function metricTable(x, rid, opts) {
    opts = opts || {};
    if (!x.metrics.length) return '<p class="muted">No metrics at this level: ' + esc(x.judged_at) + ".</p>";
    var r0 = "r0", r8 = "r8";
    var cols = opts.compact ? '<tr><th>Metric</th><th title="round 0, as found">Round 0</th><th title="' + esc(rn(r8)) + ', now">Now</th><th title="round 0 → now"></th></tr>'
      : '<tr><th>Metric</th><th>' + esc(round(r0).label) + ' <span class="muted" style="text-transform:none;letter-spacing:0">' + esc(rn(r0)) + '</span></th><th>' + esc(round(r8).label) + ' <span class="muted" style="text-transform:none;letter-spacing:0">' + esc(rn(r8)) + '</span></th><th>Change</th><th class="gate">Goal</th><th>Counts as</th><th>Defined in</th></tr>';
    var h = '<table class="dw-mt"><thead>' + cols + "</thead><tbody>";
    var span = opts.compact ? 4 : 7;
    ["performance", "fidelity", "evidence"].forEach(function (fam) {
      var ms = x.metrics.filter(function (m) { return m.family === fam; });
      if (!ms.length) return;
      h += '<tr class="grp"><td colspan="' + span + '">' + esc(FAMILY[fam][0]) + "<small>" + esc(FAMILY[fam][1]) + "</small></td></tr>";
      ms.forEach(function (m) {
        var a = m.values[r0], b = m.values[r8], c = change(m, "r8");
        var sa = m.kind === "shown" && a.status === "fail" ? "watch" : a.status, sb = m.kind === "shown" && b.status === "fail" ? "watch" : b.status;
        var f2 = opts.compact ? fmtShort : fmt;
        h += '<tr data-m="' + esc(m.id) + '"' + (opts.compact && b.detail ? ' title="' + esc(b.detail) + '"' : "") + '><td class="metric">' + code(m) + esc(m.name) + (b.detail && !opts.compact ? '<div class="sub">' + esc(b.detail) + "</div>" : "") + "</td>" +
          '<td class="num was">' + dot(sa) + " " + esc(f2(m, a)) + "</td>" +
          '<td class="num">' + dot(sb) + " " + esc(f2(m, b)) + "</td>" +
          '<td class="num">' + (opts.compact ? arrow(c).replace(/ (better|worse|same)</, "<") : arrow(c)) + "</td>" +
          (opts.compact ? "" : '<td class="gate">' + esc(gateText(m)) + "</td>" + '<td class="muted">' + esc(KIND[m.kind]) + '</td><td class="muted mono" style="font-size:11.5px">' + esc(m.defined) + "</td>") + "</tr>";
      });
    });
    return h + "</tbody></table>";
  }

  // ---- the five questions --------------------------------------------------------------------------------------------------------------
  function fiveQuestions(x, rid, compact) {
    return '<div class="dw-fq' + (compact ? " compact" : "") + '">' + FX.questions.map(function (q) {
      var s = x.questions[rid][q.id], m = s.metric ? metric(x, s.metric) : null, v = m ? m.values[rid] : null, st = s.status;
      var o = m ? m.values[other(rid)] : null, c = m ? change(m, rid) : null;
      var body = m ? '<span class="fv">' + esc(m.name) + " " + esc(fmt(m, v)) + "</span>" + (m.gate ? ' <span class="muted">· goal ' + esc(m.gate.text) + "</span>" : "") +
        (o ? ' <span class="was">' + esc(round(other(rid)).label.toLowerCase() + " " + fmt(m, o)) + "</span> " + (c.dir === "up" ? '<span class="up">▲</span>' : c.dir === "down" ? '<span class="down">▼</span>' : "") : "") +
        (v && v.detail ? '<div class="d">' + esc(v.detail) + "</div>" : "") +
        (s.via && s.via.length ? '<div class="d">and a child that gates it: ' + s.via.map(function (id) { return esc(node(id).short + " (" + (node(id).line || "") + ")"); }).join(", ") + "</div>" : "") +
        (s.misses ? '<div class="d" style="color:var(--warn)">+ ' + s.misses + " counted gate" + (s.misses > 1 ? "s" : "") + " miss: " + s.missed.map(function (id) { var mm2 = metric(x, id); return esc(lc(mm2.name) + " " + fmt(mm2, mm2.values[rid])); }).join(", ") + "</div>" : "")
        : '<span class="d">' + (s.via && s.via.length ? "from its children: " + s.via.map(function (id) { return esc(node(id).short); }).join(", ") : (q.id === "routines" || q.id === "data" ? "asked at the station" : "no metric at this level")) + "</span>";
      return '<div class="dw-fq-row ' + st + '" data-q="' + q.id + '"><span class="dw-fq-n">' + q.n + '</span><div class="dw-fq-name">' + q.name + "<small>" + esc(q.ask) + "</small></div>" +
        '<div class="dw-fq-body">' + chip(st, st === "none" ? "—" : WORD[st]) + " " + body + "</div></div>";
    }).join("") + "</div>";
  }
  var RULE = '<ol class="dw-rule"><li>Every level answers the same five questions, in this order; the first one it does not pass names its cause.</li>' +
    "<li>A parent passes a question only at its <b>own output</b> and with every child that gates it (MOC - Sim2Real Success Criteria and Metrics, proposal C; <code>sim2real.verdicts</code>).</li>" +
    "<li>On this rack the servo's gates are shown under a station, never gating it (MOC decision 1's default): a miss there reads amber, not red.</li>" +
    "<li>Not observable on this rack, or not run, never fails a question.</li></ol>";

  // ---- the 3D: schematic, labelled as such; a click selects the same node the tree does ------------------------------------------------
  var STATIONS = {
    can11: { x: -0.44, y: 0.58, family: "JMC", link: "arm", plate: "a" }, can12: { x: -0.03, y: 0.47, family: "JMC", link: "hub", plate: "b" },
    can13: { x: 0.07, y: 0.25, family: "JMC", link: "bar", plate: "b" }, can1: { x: 0.36, y: 0.47, family: "GIM", link: "disc", plate: "c" },
    can14: { x: 0.36, y: 0.25, family: "GIM", link: "disc", plate: "c" }, can15: { x: 0.50, y: 0.47, family: "GIM", link: "oval", plate: "c" },
  };
  var PLATES = { a: { x: -0.44, w: 0.2, h: 0.66, y: 0.37 }, b: { x: 0.02, w: 0.26, h: 0.5, y: 0.31 }, c: { x: 0.43, w: 0.28, h: 0.5, y: 0.31 } };
  var STATUS_HEX = { pass: 0x4cc06e, fail: 0xf2685c, watch: 0xf0a548 };
  // a station's performance (how far up the speed ladder it does its job) and its fidelity (its twin over its repeat floor)
  function stationPerf(x, rid) { var m = metric(x, "passes_up_to"); return m ? m.values[rid] : { status: "none", value: null }; }
  function stationFid(x, rid) {
    var m = metric(x, "twin_over_floor"); if (!m) return null;
    var v = m.values[rid];
    return { m: m, v: v, st: m.kind === "shown" && v.status === "fail" ? "watch" : v.status };
  }
  // labels in the 3D never sit on each other, on a station's joint (a click there picks that station's mesh) or under the chips, the
  // ViewCube, the caption and the time bar: each, lowest first, takes the nearest free spot to its anchor inside the view (straight up
  // first, then a little down, then beside it); with no free spot left it takes the one it overlaps least. A label pushed off its anchor
  // draws a thin leader back to it, so it still reads as its station's. Anchors: a station's label at its bottom centre (ax 0.5), a
  // part's at its bottom left (ax 0; ax 1, its bottom right, flipped near the right edge). Six stations on three plates crowd (CAN 1, 14
  // and 15 share one): WHY the sideways spots and the fallback (2026-11-18: CAN 14's and 15's labels sat on each other, one cut to "CAN").
  var SPOTS = [];
  for (var sdy = -175; sdy <= 63; sdy += 7) for (var ssx = -2; ssx <= 2; ssx++) SPOTS.push([sdy, ssx]);
  function spread(items, W, H, obstacles, leads) {
    items.sort(function (a, b) { return b.y - a.y; });
    var done = (obstacles || []).slice(), lines = [];
    function overlap(l, t, r, b) {
      var s = 0;
      done.forEach(function (d) { var ox = Math.min(r, d.r + 2) - Math.max(l, d.l - 2), oy = Math.min(b, d.b + 1) - Math.max(t, d.t - 1); if (ox > 0 && oy > 0) s += ox * oy; });
      return s;
    }
    items.forEach(function (it) {
      if (it.ax === 0 && it.x + it.w > W - 6) { it.x -= 28; it.ax = 1; }
      it.el.classList.toggle("flip", it.ax === 1);
      var ox = it.x, oy = it.y;
      if (it.ax === 0.5) it.x = Math.max(it.w / 2 + 4, Math.min(W - it.w / 2 - 4, it.x));
      var x0 = it.x, y0 = Math.max(it.h + 4, Math.min(H - 4, it.y)), step = it.w / 2 + 6;
      var spots = SPOTS.map(function (s) { return [s[0], s[1] * step, (s[0] < 0 ? -s[0] : 1.6 * s[0]) + 0.8 * Math.abs(s[1] * step)]; }).sort(function (a, b) { return a[2] - b[2]; });
      var best = null, least = null;
      for (var i = 0; i < spots.length && !best; i++) {
        var x = x0 + spots[i][1], y = y0 + spots[i][0], l = x - it.w * it.ax, r = l + it.w, t = y - it.h;
        if (t < 4 || y > H - 4 || l < 4 || r > W - 4) continue;
        var o = overlap(l, t, r, y);
        if (!o) best = [x, y];
        else if (!least || o < least[2]) least = [x, y, o];
      }
      var at = best || least || [x0, y0];
      it.x = at[0]; it.y = at[1];
      var L = it.x - it.w * it.ax;
      done.push({ l: L, r: L + it.w, t: it.y - it.h, b: it.y });
      it.el.style.left = it.x + "px"; it.el.style.top = it.y + "px";
      // the leader: from the anchor (kept inside the view) to the nearest point of the label's box, when it moved more than a hair
      if (it.lead) {
        var ax2 = Math.max(4, Math.min(W - 4, ox)), ay2 = Math.max(4, Math.min(H - 4, oy)), nx = Math.max(L, Math.min(L + it.w, ax2)), ny = Math.max(it.y - it.h, Math.min(it.y, ay2));
        if (Math.hypot(nx - ax2, ny - ay2) > 10) lines.push('<line x1="' + ax2.toFixed(1) + '" y1="' + ay2.toFixed(1) + '" x2="' + nx.toFixed(1) + '" y2="' + ny.toFixed(1) + '"/><circle cx="' + ax2.toFixed(1) + '" cy="' + ay2.toFixed(1) + '" r="2"/>');
      }
    });
    if (leads) leads.innerHTML = lines.join("");
  }
  function Rack3D(el, opts) {
    var self = this, THREE = window.THREE;
    el.classList.add("scene");
    if (!THREE || !window.OrbitControls) { el.innerHTML = '<p class="muted" style="padding:16px">The 3D view needs three.js (static/three-orbit-0.186.1.min.js).</p>'; self.select = self.setRound = self.setLabels = self.setFocusScale = self.explode = self.resize = function () {}; return; }
    var renderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); } catch (err) { el.innerHTML = '<p class="muted" style="padding:16px">No WebGL in this browser: the 3D view is off.</p>'; self.select = self.setRound = self.setLabels = self.setFocusScale = self.explode = self.resize = function () {}; return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);
    var scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(35, 1, 0.01, 20);
    var HOME = { pos: new THREE.Vector3(0.62, 0.78, 1.55), target: new THREE.Vector3(0.0, 0.34, 0.0) };
    camera.position.copy(HOME.pos);
    var controls = new window.OrbitControls(camera, renderer.domElement);
    controls.target.copy(HOME.target); controls.enableDamping = true; controls.dampingFactor = 0.12; controls.minDistance = 0.18; controls.maxDistance = 4;
    // the home view fits the whole rack across whatever the view's shape is: the Scene's tall stage needs the camera further back than
    // the Workbench's wide strip (the rack spans about ±0.6 m; 0.72 leaves room for the labels). It refits on resize until you orbit.
    var atHome = true;
    function homePos() {
      var dir = HOME.pos.clone().sub(HOME.target), base = dir.length(), half = Math.tan(camera.fov * Math.PI / 360);
      return HOME.target.clone().add(dir.normalize().multiplyScalar(Math.max(base, 0.72 / (half * (camera.aspect || 1)))));
    }
    controls.addEventListener("start", function () { atHome = false; });
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8d96, 1.6));
    var sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(1.2, 2.2, 1.6); scene.add(sun);
    var gridH = new THREE.GridHelper(2.4, 24, 0x7f838c, 0x5a5e66); gridH.material.opacity = 0.35; gridH.material.transparent = true; scene.add(gridH);
    function M(hex, rough, metal) { return new THREE.MeshStandardMaterial({ color: hex, roughness: rough == null ? 0.55 : rough, metalness: metal == null ? 0.2 : metal }); }
    var meshes = [], groups = {};
    function tag(mesh, nodeId, station) { mesh.userData.nodeId = nodeId; mesh.userData.station = station; meshes.push(mesh); return mesh; }
    Object.keys(PLATES).forEach(function (k) {
      var p = PLATES[k];
      var plate = new THREE.Mesh(new THREE.BoxGeometry(p.w, p.h, 0.008), M(0xc3c7ce, 0.45, 0.35)); plate.position.set(p.x, p.y, 0); scene.add(plate);
      var foot = new THREE.Mesh(new THREE.BoxGeometry(p.w, 0.012, 0.12), M(0xa9aeb6, 0.5, 0.3)); foot.position.set(p.x, 0.006, 0); scene.add(foot);
    });
    function cyl(r, len, mat) { var g = new THREE.CylinderGeometry(r, r, len, 40); g.rotateX(Math.PI / 2); return new THREE.Mesh(g, mat); }
    Object.keys(STATIONS).forEach(function (sid) {
      var s = STATIONS[sid], st = node(sid); if (!st) return;
      var tip = st.tip_length_m, g = new THREE.Group(); g.position.set(s.x, s.y, 0); scene.add(g);
      var back = new THREE.Group(); g.add(back);
      var gearbox, motor, encoder, driver;
      if (s.family === "JMC") {
        gearbox = cyl(0.031, 0.045, M(0x9097a3, 0.4, 0.6)); gearbox.position.z = -0.027;
        motor = cyl(0.03, 0.11, M(0x4e566b, 0.5, 0.35)); motor.position.z = -0.105;
        encoder = cyl(0.013, 0.006, M(0x2f3540, 0.4, 0.4)); encoder.position.z = -0.164;
        driver = new THREE.Mesh(new THREE.BoxGeometry(0.046, 0.046, 0.006), M(0x2c4f6b, 0.6, 0.1)); driver.position.z = -0.172;
      } else {
        gearbox = cyl(0.027, 0.01, M(0x5b6170, 0.45, 0.5)); gearbox.position.z = -0.009;
        motor = cyl(0.026, 0.034, M(0x24262c, 0.5, 0.35)); motor.position.z = -0.032;
        encoder = cyl(0.011, 0.005, M(0x3a3f4a, 0.4, 0.4)); encoder.position.z = -0.052;
        driver = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.04, 0.006), M(0x2c4f6b, 0.6, 0.1)); driver.position.z = -0.058;
      }
      [[gearbox, "/servo/gearbox"], [motor, "/servo/motor"], [encoder, "/servo/encoder"], [driver, "/servo/driver"]].forEach(function (pair) { pair[0].userData.home = pair[0].position.z; back.add(tag(pair[0], sid + pair[1], sid)); });
      var swing = new THREE.Group(); swing.position.z = 0.012; g.add(swing);
      swing.add(tag(cyl(0.008, 0.016, M(0xd7dae0, 0.3, 0.8)), sid + "/servo", sid));
      var linkMat = M(0xb7bcc5, 0.4, 0.55), lnk;
      if (s.link === "arm") {
        lnk = new THREE.Mesh(new THREE.BoxGeometry(0.036, tip + 0.03, 0.012), linkMat); lnk.position.set(0, -tip / 2 + 0.01, 0.012);
        var mass = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.03), M(0x8d939d, 0.5, 0.5)); mass.position.set(0, -tip + 0.04, 0.02); swing.add(tag(mass, sid + "/link", sid));
      } else if (s.link === "oval") {
        lnk = new THREE.Mesh(new THREE.CapsuleGeometry(0.018, tip, 6, 18), linkMat); lnk.position.set(0, -tip / 2, 0.01);
        var m2 = cyl(0.02, 0.03, M(0x24262c, 0.5, 0.35)); m2.position.set(0, -tip, 0.03); swing.add(tag(m2, sid + "/link", sid));
      } else if (s.link === "bar") {
        lnk = new THREE.Mesh(new THREE.BoxGeometry(0.02, tip * 2, 0.005), linkMat); lnk.position.set(0, 0, 0.01);
      } else {
        lnk = cyl(tip, 0.005, linkMat); lnk.position.z = 0.01;
        if (s.link === "disc") {
          var tg = new THREE.Mesh(new THREE.PlaneGeometry(tip * 0.9, tip * 0.9), new THREE.MeshBasicMaterial({ color: 0xffffff })); tg.position.set(0, 0, 0.0131); swing.add(tg);
          var inner = new THREE.Mesh(new THREE.PlaneGeometry(tip * 0.5, tip * 0.5), new THREE.MeshBasicMaterial({ color: 0x111111 })); inner.position.set(0.002, -0.002, 0.0133); swing.add(inner);
        }
      }
      swing.add(tag(lnk, sid + "/link", sid));
      var ball = new THREE.Mesh(new THREE.SphereGeometry(0.006, 16, 12), M(0xd95926, 0.4, 0.1)); ball.position.set(0, s.link === "disc" || s.link === "hub" ? tip : -tip, 0.022); swing.add(ball);
      var ring = new THREE.Mesh(new THREE.TorusGeometry(s.link === "arm" || s.link === "oval" ? 0.034 : tip + 0.012, 0.0035, 10, 64), new THREE.MeshBasicMaterial({ color: 0x8a8d96 })); ring.position.z = 0.006; g.add(ring);
      var hit = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.3, 12), new THREE.MeshBasicMaterial({ visible: false })); hit.rotation.x = Math.PI / 2; hit.position.z = -0.05; g.add(tag(hit, sid, sid));
      var anchor = new THREE.Vector3(s.x, s.y + Math.max(tip, 0.03) + 0.05, 0.02);
      if (s.link === "arm" || s.link === "oval") anchor.set(s.x, s.y + 0.07, 0.02);
      groups[sid] = { swing: swing, back: back, ring: ring, anchor: anchor, link: s.link };
    });
    var chips = document.createElement("div"); chips.className = "s-chips";
    chips.innerHTML = '<span class="chip sim" title="Drawn from each station\'s tip length, motor family and load; the plate layout is schematic, not the CAD">schematic geometry · simulated</span>' +
      (DATA.render ? '<button class="dw-btn" data-cad aria-pressed="false" title="The MuJoCo render of the rack\'s cad2robot payload (the site\'s media)">CAD render</button>' : "");
    el.appendChild(chips);
    var img = document.createElement("div"); img.className = "s-img"; img.hidden = true;
    if (DATA.render) img.style.backgroundImage = "url(" + DATA.render + ")";
    el.appendChild(img);
    var cap = document.createElement("div"); cap.className = "s-cap"; cap.textContent = "drag to orbit · scroll to zoom · click a station or a part";
    el.appendChild(cap);
    var cadBtn = chips.querySelector("[data-cad]");
    if (cadBtn) cadBtn.addEventListener("click", function () {
      var on = img.hidden; img.hidden = !on; cadBtn.setAttribute("aria-pressed", String(on)); cadBtn.textContent = on ? "Back to 3D" : "CAD render";
      cap.textContent = on ? "MuJoCo render of the rack's cad2robot payload (the site's media), a still" : "drag to orbit · scroll to zoom · click a station or a part"; paint();
    });
    var labelLayer = document.createElement("div"); labelLayer.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:2"; el.appendChild(labelLayer);
    var leads = document.createElementNS("http://www.w3.org/2000/svg", "svg"); leads.setAttribute("class", "s-leads"); leads.setAttribute("aria-hidden", "true"); labelLayer.appendChild(leads);
    var labels = {}, plabels = {};
    Object.keys(groups).forEach(function (sid) {
      var l = document.createElement("div"); l.className = "s-label"; l.style.pointerEvents = "auto"; l.dataset.id = sid;
      l.addEventListener("click", function (ev) { ev.stopPropagation(); opts.onPick(sid); });
      labelLayer.appendChild(l); labels[sid] = l;
      // V3's pulled-apart servo, named in place: a label beside each of the servo's four parts, shown while that servo is pulled apart
      groups[sid].back.children.forEach(function (m) {
        var id = m.userData.nodeId; if (!node(id)) return;
        var pl = document.createElement("div"); pl.className = "s-label s-plabel"; pl.style.pointerEvents = "auto"; pl.dataset.id = id; pl.hidden = true;
        pl.addEventListener("click", function (ev) { ev.stopPropagation(); opts.onPick(id); });
        labelLayer.appendChild(pl); plabels[id] = { el: pl, mesh: m, station: sid };
      });
    });
    var cube = document.createElement("div"); cube.className = "viewcube";
    cube.innerHTML = '<div class="cube">' + [["FRONT", "translateZ(26px)", [0, 0, 1]], ["BACK", "rotateY(180deg) translateZ(26px)", [0, 0, -1]], ["RIGHT", "rotateY(90deg) translateZ(26px)", [1, 0, 0]],
      ["LEFT", "rotateY(-90deg) translateZ(26px)", [-1, 0, 0]], ["TOP", "rotateX(90deg) translateZ(26px)", [0, 1, 0.0001]], ["BOTTOM", "rotateX(-90deg) translateZ(26px)", [0, -1, 0.0001]]].map(function (f) {
        return '<div class="face" data-dir="' + f[2].join(",") + '" style="transform:' + f[1] + '" title="View from ' + f[0].toLowerCase() + '">' + f[0] + "</div>";
      }).join("") + "</div>";
    el.appendChild(cube);
    var cubeInner = cube.querySelector(".cube");
    cube.addEventListener("click", function (ev) {
      var f = ev.target.closest(".face"); if (!f) return;
      var d = f.dataset.dir.split(",").map(Number), dist = camera.position.distanceTo(controls.target);
      atHome = false;
      tweenTo(controls.target.clone().add(new THREE.Vector3(d[0], d[1], d[2]).normalize().multiplyScalar(dist)), controls.target.clone());
    });
    var selected = null, rid = "r8", exploded = null, tween = null, dirty = true, t0 = performance.now(), labelMode = "all", focusScale = 1;
    function selectedStation() { var st = selected ? stationOf(selected) : null; return st ? st.id : null; }
    function paint() {
      Object.keys(groups).forEach(function (sid) {
        // the ring wears the station's performance (performance first: does it do the job); fidelity is the label's second word
        var st = stationPerf(node(sid), rid).status;
        groups[sid].ring.material.color.setHex(STATUS_HEX[st] || 0x8a8d96);
        groups[sid].ring.scale.setScalar(sid === selectedStation() ? 1.18 : 1);
      });
      meshes.forEach(function (m) {
        var on = selected && (m.userData.nodeId === selected || (selected === m.userData.station && m.userData.nodeId !== m.userData.station) || m.userData.nodeId.indexOf(selected + "/") === 0);
        if (m.material.emissive) m.material.emissive.setHex(on ? 0x2a3b55 : 0x000000);
        if (exploded && m.userData.station === exploded && m.material.emissive && node(m.userData.nodeId) && m.userData.nodeId.indexOf("/servo/") > 0) {
          var s2 = lineStatus(node(m.userData.nodeId), rid);
          if (!on && (s2 === "fail" || s2 === "watch")) m.material.emissive.setHex(s2 === "fail" ? 0x5a1410 : 0x4a3008);
        }
      });
      Object.keys(labels).forEach(function (sid) {
        var l = labels[sid], x = node(sid), up = stationPerf(x, rid), f = stationFid(x, rid);
        l.hidden = !img.hidden || (labelMode === "selected" && !!selectedStation() && sid !== selectedStation());
        l.innerHTML = dot(up.status, "performance: " + (WORD[up.status] || up.status)) + "<b>" + esc(x.short) + '</b><small title="tracks and stops up to this fraction of its top speed">' + esc(up.value > 0 ? "to " + n(up.value, 1) : "no rung") + "</small>" +
          (f && (f.st === "fail" || f.st === "watch") ? '<small class="fid ' + f.st + '" title="fidelity: ' + esc(f.m.name) + '">twin ' + esc(fmtShort(f.m, f.v)) + "</small>" : "");
        l.title = x.title + " · " + oneLine(x, rid);
        l.classList.toggle("sel", sid === selectedStation());
      });
      Object.keys(plabels).forEach(function (id) {
        // a part's label leads with its performance row, as its page does (the motor and gearbox: "not observable on this rack"); a
        // fidelity miss follows as a second word
        var p = plabels[id], x = node(id), rows = answerRows(x, rid), s2 = rows[0].st, f2 = rows[1];
        p.el.hidden = !img.hidden || exploded !== p.station;
        p.el.innerHTML = dot(s2) + "<b>" + esc(x.short) + "</b><small>" + esc(s2 === "none" ? "no gates" : WORD[s2] || s2) + "</small>" +
          (f2 && (f2.st === "fail" || f2.st === "watch") ? '<small class="fid ' + f2.st + '">fidelity ' + (f2.st === "fail" ? "fails" : "outside target") + "</small>" : "");
        p.el.title = x.title + " · " + oneLine(x, rid);
        p.el.classList.toggle("sel", id === selected);
      });
      dirty = true;
    }
    function tweenTo(pos, target, ms) { tween = { from: camera.position.clone(), to: pos, tfrom: controls.target.clone(), tto: target, t: performance.now(), ms: ms || 450 }; }
    self.select = function (id, focus) {
      selected = id;
      var sid = selectedStation();
      if (focus && sid) {
        var s = STATIONS[sid], gg = groups[sid];
        var cy = gg.link === "arm" ? s.y - 0.16 : gg.link === "oval" ? s.y - 0.05 : s.y;
        var target = new THREE.Vector3(s.x, cy, 0), dist = (gg.link === "arm" ? 1.25 : 0.75) * focusScale;
        var dir = camera.position.clone().sub(controls.target).normalize();
        if (exploded === sid) { target.set(s.x, s.y, -0.14); dist = 0.75 * Math.sqrt(focusScale); dir = new THREE.Vector3(0.85, 0.3, 0.45).normalize(); }
        atHome = false;
        tweenTo(target.clone().add(dir.multiplyScalar(dist)), target);
      } else if (focus && !sid) { atHome = true; tweenTo(homePos(), HOME.target.clone()); }
      paint();
    };
    self.setRound = function (r) { rid = r; paint(); };
    // "selected": only the picked station wears its label (V2's small dock); "all": every station does (the Scene, the Workbench's strip)
    self.setLabels = function (mode) { if (mode !== labelMode) { labelMode = mode; paint(); } };
    // how far the camera stays from a picked station: the Scene keeps the other stations in view (1.7), the strip and the dock come close
    self.setFocusScale = function (k) { focusScale = k; };
    // V3's pulled-apart servo: the station whose servo (or a part of it) is picked has its motor, gearbox, encoder and driver drawn apart
    self.explode = function (sid) {
      exploded = sid || null;
      Object.keys(groups).forEach(function (k) { groups[k].back.children.forEach(function (m, i) { m.userData.goal = m.userData.home - (exploded === k ? 0.05 * (i + 1) : 0); }); });
      paint();
    };
    self.exploded = function () { return exploded; };
    var ray = new THREE.Raycaster(), ptr = new THREE.Vector2(), down = null;
    renderer.domElement.addEventListener("pointerdown", function (e) { down = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener("pointerup", function (e) {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      var r = renderer.domElement.getBoundingClientRect();
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      var hits = ray.intersectObjects(meshes, false), real = hits.filter(function (h) { return h.object.userData.nodeId !== h.object.userData.station; });
      var h = real[0] || hits[0]; if (!h) return;
      var id = h.object.userData.nodeId, sid = h.object.userData.station;
      // the first click on a station picks the station; inside the picked station a click picks its servo or link, and a servo's
      // parts once it is pulled apart (V3)
      var inside = selected && (selected === sid || selected.indexOf(sid + "/") === 0);
      if (!inside) id = sid;
      else if (exploded !== sid && id.indexOf("/servo/") > 0) id = sid + "/servo";
      opts.onPick(id);
    });
    controls.addEventListener("change", function () { dirty = true; });
    var v3 = new THREE.Vector3();
    function resize() {
      var w = el.clientWidth, hh = el.clientHeight; if (!w || !hh) return;
      renderer.setSize(w, hh, false); camera.aspect = w / hh; camera.updateProjectionMatrix();
      // WHY retarget a flight home: it was aimed at the home fit of the slot the 3D just left (the Workbench's wide strip, or the
      // detached 1:1 holder on first load), so the Scene opened too close and CAN 15, at the rack's right end, fell out of view
      if (atHome && tween) { tween.to = homePos(); tween.tto = HOME.target.clone(); }
      else if (atHome) { camera.position.copy(homePos()); controls.target.copy(HOME.target); }
      dirty = true;
    }
    if (window.ResizeObserver) new ResizeObserver(resize).observe(el);
    function bg() { var c = getComputedStyle(host).getPropertyValue("--scene-bg").trim() || "#111214"; scene.background = new THREE.Color(c); dirty = true; }
    bg();
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", bg);
    function frame(now) {
      requestAnimationFrame(frame);
      if (document.hidden || !el.isConnected || !el.offsetParent) return;
      if (tween) { var k = Math.min(1, (now - tween.t) / tween.ms), ease = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; camera.position.lerpVectors(tween.from, tween.to, ease); controls.target.lerpVectors(tween.tfrom, tween.tto, ease); if (k >= 1) tween = null; dirty = true; }
      var sid = selectedStation();
      Object.keys(groups).forEach(function (k2) {
        var gg = groups[k2], goal = k2 === sid ? Math.sin((now - t0) / 1000 * 2.1) * 0.35 : 0;
        if (Math.abs(gg.swing.rotation.z - goal) > 1e-4) { gg.swing.rotation.z += (goal - gg.swing.rotation.z) * (k2 === sid ? 1 : 0.15); dirty = true; }
        gg.back.children.forEach(function (m) { if (m.userData.goal != null && Math.abs(m.position.z - m.userData.goal) > 1e-4) { m.position.z += (m.userData.goal - m.position.z) * 0.2; dirty = true; } });
      });
      controls.update();
      if (!dirty) return;
      dirty = false;
      renderer.render(scene, camera);
      var w = el.clientWidth, hh = el.clientHeight, placed = [];
      Object.keys(labels).forEach(function (k3) {
        if (labels[k3].hidden) return;
        // a station out of the view keeps its label out of it too (never piled at the edge, as if it were there); a station in the view
        // always wears its label, pulled inside the view when the spot above the station is not (2026-11-18: CAN 15's went missing)
        v3.set(STATIONS[k3].x, STATIONS[k3].y, 0.02).project(camera);
        var jx = (v3.x + 1) / 2 * w, jy = (1 - v3.y) / 2 * hh, out = v3.z > 1 || jx < 0 || jx > w || jy < 0 || jy > hh;
        labels[k3].style.display = out ? "none" : "";
        if (out) return;
        v3.copy(groups[k3].anchor).project(camera);
        var lx = v3.z > 1 ? jx : (v3.x + 1) / 2 * w, ly = v3.z > 1 ? jy : (1 - v3.y) / 2 * hh;
        placed.push({ el: labels[k3], x: lx, y: ly, w: labels[k3].offsetWidth, h: labels[k3].offsetHeight, ax: 0.5, lead: true });
      });
      Object.keys(plabels).forEach(function (id) {
        var p = plabels[id]; if (p.el.hidden) return;
        p.mesh.getWorldPosition(v3); v3.project(camera);
        var px = (v3.x + 1) / 2 * w, py = (1 - v3.y) / 2 * hh, pout = v3.z > 1 || px < 0 || px > w || py < 0 || py > hh;
        p.el.style.display = pout ? "none" : "";
        if (!pout) placed.push({ el: p.el, x: px + 14, y: py + 10, w: p.el.offsetWidth, h: p.el.offsetHeight, ax: 0, lead: true });
      });
      var obstacles = [chips, cube, cap].map(function (o) { return { l: o.offsetLeft, t: o.offsetTop, r: o.offsetLeft + o.offsetWidth, b: o.offsetTop + o.offsetHeight }; });
      // the Scene's time bar floats over the 3D's foot (a sibling in the stage, drawn above the labels): no label goes under it
      var bar = el.parentNode && el.parentNode.querySelector(":scope > .dw-timebar");
      if (bar && bar.offsetWidth) { var er = el.getBoundingClientRect(), br = bar.getBoundingClientRect(); obstacles.push({ l: br.left - er.left, t: br.top - er.top, r: br.right - er.left, b: br.bottom - er.top }); }
      Object.keys(groups).forEach(function (k4) {
        v3.set(STATIONS[k4].x, STATIONS[k4].y, 0.02).project(camera);
        if (v3.z <= 1) { var jx = (v3.x + 1) / 2 * w, jy = (1 - v3.y) / 2 * hh; obstacles.push({ l: jx - 14, t: jy - 14, r: jx + 14, b: jy + 14 }); }
      });
      spread(placed, w, hh, obstacles, leads);
      var e = camera.matrixWorldInverse.elements, f = [1, -1, 1], m = [];
      for (var j = 0; j < 3; j++) { for (var i = 0; i < 3; i++) m.push(e[j * 4 + i] * f[i] * f[j]); m.push(0); }
      cubeInner.style.transform = "translateZ(-26px) matrix3d(" + m.concat([0, 0, 0, 1]).join(",") + ")";
    }
    resize(); paint(); requestAnimationFrame(frame);
    self.resize = resize;
    // for the acceptance script: where a station's joint is on screen, so a test can click the mesh itself
    self.screenOf = function (sid) { var s = STATIONS[sid], p = new THREE.Vector3(s.x, s.y, 0.02).project(camera), r = renderer.domElement.getBoundingClientRect(); return { x: r.left + (p.x + 1) / 2 * r.width, y: r.top + (1 - p.y) / 2 * r.height }; };
    window.__dwRack = self;
  }

  // ---- one 3D for every view: the same scene (and its camera) moves between the Workbench's strip, the Scene's stage and the Sheet's dock
  function mount3d(slot) {
    if (!rack3d) { var keep = document.createElement("div"); rack3d = new Rack3D(keep, { onPick: function (id) { go({ node: id }); } }); rack3d._host = keep; }
    if (rack3d._host.parentNode !== slot) slot.insertBefore(rack3d._host, slot.firstChild);
  }
  // the picked node in 3D: a servo or one of its parts pulls that station's servo apart; true when the pick changed (the camera flies to it)
  function sync3d(x, rid) {
    var station = stationOf(x.id);
    rack3d.setLabels(VIEW === "sheet" ? "selected" : "all");
    rack3d.setFocusScale(VIEW === "scene" ? 1.7 : 1);
    rack3d.explode(x.level === "servo" || x.level === "part" ? (station && x.id.indexOf("/link") < 0 ? station.id : null) : null);
    rack3d.setRound(rid);
    var changed = current !== x.id;
    rack3d.select(x.id === FX.root ? null : x.id, changed);
    current = x.id;
    return changed;
  }

  // ---- the W&B backdoor (Zach, Daily Note 2026-11-18: "Each deployment in the sim2real app should have a button to open within weights
  // and biases, as like a backdoor, so that we can always still support W&B for summary"): the deployment's project, and its report when
  // it has one, each in a new tab. The links are the deployment's data (app/registry.json via the page data); none without a project.
  var EXT = '<svg class="ext" viewBox="0 0 16 16" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5 7.5 8.5M11.5 9.5v4h-9v-9h4"/></svg>';
  function wandbLinks(d) {
    var w = d && d.wandb;
    if (!w || !w.url) return "";
    return '<span class="dw-wandb">' +
      '<a class="dw-btn" data-wandb="project" href="' + esc(w.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc("Open the W&B project " + (w.project || "") + " in a new tab") + '">Open in W&amp;B' + EXT + "</a>" +
      (w.report ? '<a class="dw-btn" data-wandb="report" href="' + esc(w.report) + '" target="_blank" rel="noopener noreferrer" title="' + esc("Open its W&B report" + (w.report_title ? ", " + w.report_title + "," : "") + " in a new tab") + '">W&amp;B report' + EXT + "</a>" : "") +
      "</span>";
  }

  // ---- home: every deployment ------------------------------------------------------------------------------------------------------
  function home() {
    var row = function (d) {
      var img = d.image ? '<img src="' + esc(d.image) + '" alt="" loading="lazy">' : '<span class="noimg"></span>';
      var head;
      if (d.workbench && d.headline) {
        var h = d.headline.r8, h0 = d.headline.r0;
        head = '<div class="head">' + chip(h.perf_gates === h.perf_total ? "pass" : "tag", "performance, real vs the target") +
          "<b>" + h.perf_gates + " of " + h.perf_total + ' performance gates</b><span class="was">was ' + h0.perf_gates + " as found (round 0)</span>" +
          '<div class="m">campaign goal ' + (h.goal_met ? "met" : "not met: fidelity") + " · " + h.gates_passed + " of " + h.gates_total + " gates</div></div>";
      } else if (d.kind === "virtual") {
        head = '<div class="head">' + chip(d.oracle === "pass" ? "pass" : d.oracle ? "fail" : "none", d.oracle ? "oracle " + d.oracle : "no oracle verdict") + '<div class="m">sim only · opens its page</div></div>';
      } else {
        head = '<div class="head"><div class="m">' + esc(DATA.missing || "opens its page") + "</div></div>";
      }
      var t = '<div><div class="t">' + esc(d.title) + " " + chip(d.kind === "physical" ? "real" : "sim", d.kind === "physical" ? "real hardware" : "virtual") + '</div><div class="l">' + esc(d.summary || d.what) + '</div><div class="m">' + esc(d.where || d.what) + "</div></div>";
      var a = d.workbench ? '<a class="dw-drow" data-go href="' + esc(location.pathname + "?d=" + encodeURIComponent(d.id)) + '" data-dep="' + esc(d.id) + '">' + img + t + head + "</a>"
        : '<a class="dw-drow" href="' + esc(d.page) + '" data-dep="' + esc(d.id) + '">' + img + t + head + "</a>";
      // WHY beside the row's link, never in it: a link inside a link is invalid HTML, and a click on it would also open the row
      var wb = wandbLinks(d);
      return wb ? '<div class="dw-drow-w" data-dep="' + esc(d.id) + '">' + a + '<div class="dw-drow-wb">' + wb + "</div></div>" : a;
    };
    var phys = DATA.deployments.filter(function (d) { return d.kind === "physical"; }), virt = DATA.deployments.filter(function (d) { return d.kind !== "physical"; });
    $("dw-home").innerHTML = "<h1>Deployments</h1><p class=\"lede\">Every machine we do sim to real on. Open one for its 3D view and its typed component tree; every node shows its <b>performance</b> against the target first, then how close its twin is.</p>" +
      '<div class="dw-dlist"><div class="dw-dsec">Physical · real hardware</div>' + phys.map(row).join("") + '<div class="dw-dsec">Virtual · system-ID oracle examples and scenarios</div>' + virt.map(row).join("") + "</div>" +
      '<p class="after"><a href="' + esc(DATA.all_url) + '">Every deployment as a card, filtered by kind and tags →</a></p>';
  }

  // ---- the node's page ---------------------------------------------------------------------------------------------------------------
  function tabsFor(x) {
    var t = [];
    if (x.level === "deployment" || x.level === "station") t.push(["perf", "Performance"]);
    if (x.metrics.length) t.push(["metrics", "Metrics", x.metrics.length]);
    if (x.level === "deployment" || x.level === "station") t.push(["runs", "Runs"]);
    if (x.metrics.length) t.push(["questions", "Five questions"]);
    t.push(["def", "Where it is defined"]);
    return t;
  }
  function entity(st) {
    var x = node(st.node) || node(FX.root), rid = st.round, tabs = tabsFor(x);
    var tab = tabs.some(function (t) { return t[0] === st.tab; }) ? st.tab : tabs[0][0];
    var ps = familyStatus(x, "performance", rid), fs = familyStatus(x, "fidelity", rid);
    if (x.level === "station") ps = metric(x, "passes_up_to").values[rid].status;
    if (x.level === "deployment") ps = metric(x, "stations_tracking").values[rid].status;
    var chips = (ps !== "none" ? chip(ps === "not_observable" ? "not_observable" : ps, "performance: " + (ps === "pass" ? "pass" : ps === "fail" ? "fails" : WORD[ps])) : "") + " " +
      (fs !== "none" ? chip(fs === "not_observable" ? "not_observable" : fs, "fidelity: " + (fs === "pass" ? "pass" : fs === "fail" ? "fails" : WORD[fs])) : "");
    var health = x.health ? '<span class="k">Unit health · RobotDx</span>faults in this round\'s runs <b>' + x.health[rid].faults + "</b> · missing plays <b>" + x.health[rid].missing + '</b><div class="muted" style="margin-top:3px">live faults, temperature, last heard: RobotDx (not on this page)</div>'
      : x.unit ? '<span class="k">Unit</span>' + esc(x.unit) + '<div class="muted" style="margin-top:3px">its live health is RobotDx\'s, apart from these gates</div>' : '<span class="k">Unit</span>no physical unit: a composition';
    var facts = (x.facts || []).map(function (f) { return "<span>" + esc(f[0]) + " <b>" + esc(f[1]) + "</b></span>"; }).join("");
    if (x.device && DATA.old_pages[x.device] && x.level === "station") facts += '<span><a href="' + esc(DATA.old_pages[x.device]) + '">every recorded run of ' + esc(x.device) + ", older sessions too →</a></span>";
    var html = '<div class="dw-head"><h1 class="dw-title">' + icon(x.type.id) + esc(x.title) + " " + chips + "</h1>" +
      '<div class="dw-sub">' + chip("tag", x.type.name) + "<span>judged at " + esc(x.judged_at) + "</span><span>" + esc(round(rid).label + " · " + round(rid).long) + " · scored " + esc(round(rid).scored_utc.replace("T", " ").replace(/:\d\dZ$/, "Z")) + "</span>" + (x.gating ? "" : chip("tag", "shown, not gating")) + "</div>" +
      '<div class="dw-grid">' + answerHTML(x, rid) + '<div class="dw-health">' + health + "</div></div>" + (facts ? '<div class="dw-facts">' + facts + "</div>" : "") + (x.caveat ? '<div class="caveat" style="margin-top:8px">' + esc(x.caveat) + "</div>" : "") + "</div>" +
      '<div class="dw-scene-wrap" id="dw-sceneWrap"></div><div class="dw-sash h" id="dw-sashS"></div>' +
      '<div class="dw-tabs" role="tablist">' + tabs.map(function (t) { return '<button role="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === tab) + '">' + esc(t[1]) + (t[2] ? '<span class="n">' + t[2] + "</span>" : "") + "</button>"; }).join("") + "</div>" +
      '<div class="dw-tabbody" id="dw-tabbody"></div>';
    var el = $("dw-entity");
    el.innerHTML = html;
    mount3d($("dw-sceneWrap"));
    sash($("dw-sashS"), $("dw-sceneWrap"), { key: "scene", horizontal: true, min: 140, max: 640, dflt: 280, onResize: function () { if (rack3d) rack3d.resize(); } });
    if (sync3d(x, rid)) el.scrollTop = 0;
    el.querySelectorAll("[data-tab]").forEach(function (b) { b.addEventListener("click", function () { go({ tab: b.dataset.tab }, true); }); });
    var body = $("dw-tabbody");
    if (tab === "perf") body.innerHTML = x.level === "deployment" ? perfRack(x, rid) : perfStation(x, rid);
    else if (tab === "metrics") body.innerHTML = '<p class="lede">Every metric at this level, performance first, round 0 (as found, before any fit) beside now (' + esc(rn("r8")) + ') and which way it moved.</p>' + metricTable(x, rid) + children(x, rid);
    else if (tab === "runs") body.innerHTML = runsTeaser(x, rid);
    else if (tab === "questions") body.innerHTML = '<p class="lede">The five questions in order at this level: the ruler (Floor), the data, the routines, then fidelity (Twin) and the job.</p>' + fiveQuestions(x, rid) + RULE + children(x, rid);
    else body.innerHTML = definition(x);
    body.querySelectorAll("[data-node]").forEach(function (b) { b.addEventListener("click", function () { go({ node: b.dataset.node, view: "", tab: "" }); }); });
    el.querySelectorAll(".dw-answer [data-node]").forEach(function (b) { b.addEventListener("click", function () { go({ node: b.dataset.node, view: "", tab: "" }); }); });
    body.querySelectorAll("[data-grid]").forEach(function (b) { b.addEventListener("click", function () { var top = el.scrollTop; save("grid", b.dataset.grid); entity(state()); el.scrollTop = top; }); });
  }
  function tile(label, value, st, goal, was) {
    return '<div class="dw-tile"><span class="k">' + esc(label) + '</span><div class="tv">' + (st ? dot(st) : "") + esc(value) + '</div><div class="g">' + esc(goal || "") + (was ? ' · <span class="was">' + esc(was) + "</span>" : "") + "</div></div>";
  }
  function perfRack(x, rid) {
    var t = FX.thresholds, o = other(rid), sts = kids(FX.root).filter(function (k) { return k.level === "station"; });
    function worstAt(r, key) { var v = sts.map(function (s) { return [s, rung(s, r, 0.9)[key]]; }).filter(function (p) { return p[1] != null; }); v.sort(function (a, b) { return b[1] - a[1]; }); return v[0] || [null, null]; }
    var rms = worstAt(rid, "tracking_rms_deg"), rms0 = worstAt(o, "tracking_rms_deg"), stop = worstAt(rid, "stop_tool_mm"), stop0 = worstAt(o, "stop_tool_mm"), wst = worstAt(rid, "stop_tool_max_mm");
    var up = metric(x, "stations_tracking"), pg = metric(x, "perf_gates");
    var tiles = '<div class="dw-tiles">' +
      tile("Stations tracking to 0.9 of top speed", up.values[rid].value + " of 6", up.values[rid].status, "goal 6 of 6", round(o).label.toLowerCase() + " " + up.values[o].value) +
      tile("Real performance gates", pg.values[rid].value + " of " + pg.values[rid].of, pg.values[rid].value === pg.values[rid].of ? "pass" : null, "tracking + tip stop, every rung", round(o).label.toLowerCase() + " " + pg.values[o].value) +
      tile("Worst tracking RMS at 0.9", deg(rms[1]) + " · " + (rms[0] ? rms[0].short : ""), rms[1] != null ? (rms[1] <= t.tracking_rms_deg ? "pass" : "fail") : null, "GOOD ≤ " + t.tracking_rms_deg + "°", round(o).label.toLowerCase() + " " + deg(rms0[1])) +
      tile("Worst tip stop at 0.9, median", mm(stop[1]) + " · " + (stop[0] ? stop[0].short : ""), stop[1] != null ? (stop[1] <= t.stop_tool_mm ? "pass" : "fail") : null, "GOOD ≤ " + t.stop_tool_mm + " mm", round(o).label.toLowerCase() + " " + mm(stop0[1])) +
      tile("Worst single stop at 0.9", mm(wst[1]) + " · " + (wst[0] ? wst[0].short : ""), null, "not the gate (it reads the median)", "") + "</div>";
    var gk = load("grid", "tracking_rms_deg");
    if (!GRID[gk]) gk = "tracking_rms_deg";
    var gridSwitch = '<div class="dw-seg" role="group" aria-label="What the grid shows">' + Object.keys(GRID).map(function (k) { return '<button data-grid="' + k + '" aria-pressed="' + (k === gk) + '">' + esc(GRID[k][0]) + "</button>"; }).join("") + "</div>";
    return '<h3>Where it stands · ' + esc(round(rid).label + ", " + round(rid).long) + "</h3>" + tiles +
      '<h3>Round by round · the goal line drawn</h3><p class="lede">Each station at the goal\'s rung (0.9 of its top speed), every scored round. Green points meet the goal, red miss it. ' +
      'Caveat: round 0 was scored against the plan tick, later rounds against the measured target (re-scored the later way, round 0 reads worse, not better), and CAN 11\'s top speed doubled after round 0.</p>' + historyGap() +
      '<div class="dw-plots wide"><div class="pc">' + historyPlot("tracking_rms_09") + '</div><div class="pc">' + historyPlot("stop_09") + "</div></div>" +
      '<h3 style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">Every station × every speed rung ' + gridSwitch + '</h3><p class="lede">The fraction of each station\'s top speed across, the round shown. Green meets the goal, red misses it; a worst stop over 1 mm is outlined amber (the gate reads the median). Click a station for its page.</p>' +
      grid(rid, gk) + children(x, rid);
  }
  function perfStation(x, rid) {
    var t = FX.thresholds, o = other(rid), r = rung(x, rid, 0.9), r0 = rung(x, o, 0.9), up = metric(x, "passes_up_to"), pg = metric(x, "perf_gates");
    var tiles = '<div class="dw-tiles">' +
      tile("Highest rung tracked", up.values[rid].value > 0 ? n(up.values[rid].value, 1) + " of top speed" : "none", up.values[rid].status, "goal ≥ 0.9", round(o).label.toLowerCase() + " " + (up.values[o].value > 0 ? n(up.values[o].value, 1) : "none")) +
      tile("Tracking RMS at 0.9", deg(r.tracking_rms_deg), r.tracking_rms_deg != null ? (r.tracking_rms_deg <= t.tracking_rms_deg ? "pass" : "fail") : null, "GOOD ≤ " + t.tracking_rms_deg + "°", round(o).label.toLowerCase() + " " + deg(r0.tracking_rms_deg)) +
      tile("Tracking peak at 0.9", deg(r.tracking_peak_deg), r.tracking_peak_deg != null ? (r.tracking_peak_deg <= t.tracking_peak_deg ? "pass" : "fail") : null, "GOOD ≤ " + t.tracking_peak_deg + "°", round(o).label.toLowerCase() + " " + deg(r0.tracking_peak_deg)) +
      tile("Tip stop at 0.9, median", mm(r.stop_tool_mm), r.stop_tool_mm != null ? (r.stop_tool_mm <= t.stop_tool_mm ? "pass" : "fail") : null, "GOOD ≤ " + t.stop_tool_mm + " mm", round(o).label.toLowerCase() + " " + mm(r0.stop_tool_mm)) +
      tile("Worst single stop at 0.9", mm(r.stop_tool_max_mm), null, "of " + (r.stops || "—") + " stops · not the gate", round(o).label.toLowerCase() + " " + mm(r0.stop_tool_max_mm)) +
      tile("Real performance gates", pg.values[rid].value + " of " + pg.values[rid].of, null, "tracking + tip stop, 6 rungs", round(o).label.toLowerCase() + " " + pg.values[o].value) + "</div>";
    var omega = x.omega[o] !== x.omega[rid] ? "each rung is a fraction of that round's top speed: " + degPerS(x.omega.r0) + " in round 0, " + degPerS(x.omega.r8) + " now" : "top speed " + degPerS(x.omega[rid]) + " in both rounds";
    return "<h3>Where it stands · " + esc(round(rid).label + ", " + round(rid).long) + "</h3>" + tiles +
      '<h3>Up the speed ladder · the goal line drawn</h3><div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">' + legend(rid) + '<span class="muted" style="font-size:12px">' + esc(omega) + "</span></div>" +
      '<div class="dw-plots">' + Object.keys(RUNG_KEYS).map(function (k) { return '<div class="pc">' + rungPlot(x, k, rid) + "</div>"; }).join("") + "</div>" +
      '<h3>Round by round</h3>' + historyGap() + '<div class="dw-plots wide"><div class="pc">' + historyPlot("tracking_rms_09", x.id) + '</div><div class="pc">' + historyPlot("stop_max_09", x.id) + "</div></div>" + children(x, rid);
  }
  function children(x, rid) {
    if (!x.children.length) return "";
    var title = x.level === "station" ? "Under this station · shown, not gating (MOC decision 1)" : x.level === "servo" ? "Its parts · pulled apart in the 3D" : "Under it";
    return '<div class="dw-childs"><h3>' + esc(title) + "</h3>" + kids(x.id).map(function (k) {
      var st = lineStatus(k, rid);
      return '<div class="dw-crow" data-node="' + esc(k.id) + '">' + dot(st) + icon(k.type.id) + "<b>" + esc(k.short) + '</b><span class="muted" style="white-space:nowrap">' + esc(k.line || "") + '</span><span class="cl">' + esc(oneLine(k, rid)) + "</span></div>";
    }).join("") + "</div>";
  }
  function runsTeaser(x, rid) {
    var sid = x.level === "station" ? x.id : "";
    return '<p class="lede">Every run is a row: its round, rung and speed, whether it was a repeat or held out, its tracking against the goal, and its Rerun recording one click away.</p>' +
      '<p>' + link({ view: "runs", st: sid, rr: rid === "r0" ? "0" : "", tab: "" }, "Open the Runs view" + (sid ? " for " + esc(x.short) : "") + " →", "dw-btn") + "</p>";
  }
  function definition(x) {
    return "<h3>Where this level's numbers come from</h3><pre class=\"dw-sketch\">" +
      '<span class="c"># sim2real (src/sim2real/): the verdict lives on the composition, written once</span>\n' +
      "from sim2real import deployments_page, verdicts\n" +
      'doc = deployments_page.build()          <span class="c"># the campaign scorecards in (read-only), this typed tree out</span>\n' +
      'verdicts.QUESTIONS                      <span class="c"># Floor → Data → Routines → Twin → Job, once</span>\n' +
      'verdicts.roll_up(nodes, rounds)         <span class="c"># a parent passes only at its own output and with every child that gates it</span>\n' +
      'deployments_page.runs()                 <span class="c"># every play of every round, with its Rerun recording</span>\n\n' +
      '<span class="c"># this node: ' + esc(x.title) + " (" + esc(x.type.name) + ', ' + esc(x.type.rm) + ')</span>\n' +
      x.metrics.map(function (m) { return esc((m.code ? m.code + " " : "") + m.name) + '  <span class="c"># ' + esc(m.family) + " · " + esc(KIND[m.kind]) + " · " + esc(m.defined) + "</span>"; }).join("\n") +
      "</pre>" +
      '<p class="lede" style="margin-top:10px">The gate numbers are each scorecard\'s own thresholds; the five cell gates re-state the campaign\'s frozen <code>pendulum_goal.cell_gates</code> and are held to the scorecards\' 82 and 151 of 180 at every build. ' +
      "Next (not built): the model-free metric functions move to robot_models' <code>metrics/</code> folder (" + "Zach's \"folder called metrics\"" + "), and the cards call them.</p>";
  }

  // ---- the Sheet (V2): the nested tree-table; every performance metric as round 0 · now · change, fidelity beside it; the five
  // questions an optional column group; What changed dims the rows that did not move. Its 3D and inspector sit docked on the right. --
  var tableFolded = null;
  function perfCols() {
    var t = FX.thresholds;
    function at(key) { return function (x, r) { return rung(x, r, 0.9)[key]; }; }
    return [
      { id: "rung", name: "Highest rung tracked", goal: "goal ≥ 0.9", get: function (x, r) { return metric(x, "passes_up_to").values[r].value; },
        fmt: function (v) { return v == null ? "—" : v > 0 ? n(v, 1) : "none"; }, ok: function (v) { return v >= 0.9; }, higher: true },
      { id: "rms", name: "Tracking RMS at 0.9", goal: "GOOD ≤ " + t.tracking_rms_deg + "°", get: at("tracking_rms_deg"), fmt: function (v) { return deg(v); }, ok: function (v) { return v <= t.tracking_rms_deg; } },
      { id: "peak", name: "Tracking peak at 0.9", goal: "GOOD ≤ " + t.tracking_peak_deg + "°", get: at("tracking_peak_deg"), fmt: function (v) { return deg(v); }, ok: function (v) { return v <= t.tracking_peak_deg; } },
      { id: "stop", name: "Tip stop at 0.9, median", goal: "GOOD ≤ " + t.stop_tool_mm + " mm", get: at("stop_tool_mm"), fmt: mm, ok: function (v) { return v <= t.stop_tool_mm; } },
      // not the gate (it reads the median): over 1 mm reads amber, never red
      { id: "worst", name: "Worst stop at 0.9", goal: "not the gate", get: at("stop_tool_max_mm"), fmt: mm, ok: null, watch: function (v) { return v > t.stop_tool_mm; } },
    ];
  }
  function chg(dir, a, b) {
    var word = { up: "better", down: "worse", flat: "same" }[dir] || "";
    return '<td class="chg ' + dir + '"' + (word ? ' title="round 0 → now: ' + esc(word + (a != null ? " (" + a + " → " + b + ")" : "")) + '"' : "") + ">" + ({ up: "▲", down: "▼", flat: "=" }[dir] || "") + "</td>";
  }
  function trio(x, c) {
    if (x.level !== "station") return '<td class="q bl none" data-c="' + c.id + '" data-r="r0">—</td><td class="q none" data-c="' + c.id + '" data-r="r8">—</td><td class="chg"></td>';
    var a = c.get(x, "r0"), b = c.get(x, "r8");
    function st(v) { return v == null ? "" : c.ok ? (c.ok(v) ? "pass" : "fail") : c.watch && c.watch(v) ? "watch" : ""; }
    var dir = a == null || b == null ? "na" : Math.abs(a - b) < 1e-9 ? "flat" : (c.higher ? b > a : b < a) ? "up" : "down";
    return '<td class="q was bl" data-c="' + c.id + '" data-r="r0" title="' + esc(c.name + " · round 0, as found: " + c.fmt(a)) + '"><span class="cell">' + (st(a) ? dot(st(a)) : "") + esc(c.fmt(a)) + "</span></td>" +
      '<td class="q ' + st(b) + '" data-c="' + c.id + '" data-r="r8" title="' + esc(c.name + " · now, " + rn("r8") + ": " + c.fmt(b) + " · " + c.goal) + '"><span class="cell">' + (st(b) ? dot(st(b)) : "") + esc(c.fmt(b)) + "</span></td>" + chg(dir, c.fmt(a), c.fmt(b));
  }
  function fidMetric(x) { return metric(x, "twin_over_floor") || metric(x, "T2") || metric(x, "stations_twinned"); }
  function fidTrio(x) {
    var fm = fidMetric(x);
    if (!fm) return '<td class="q bl none" data-c="twin" data-r="r0">—</td><td class="q none" data-c="twin" data-r="r8">—</td><td class="chg"></td>';
    function s(v) { return fm.kind === "shown" && v.status === "fail" ? "watch" : v.status; }
    var a = fm.values.r0, b = fm.values.r8, c = change(fm, "r8");
    return '<td class="q was bl" data-c="twin" data-r="r0" title="' + esc(fm.name + " · round 0, as found: " + fmt(fm, a)) + '"><span class="cell">' + dot(s(a)) + esc(fmtShort(fm, a)) + "</span></td>" +
      '<td class="q ' + s(b) + '" data-c="twin" data-r="r8" title="' + esc(fm.name + " · now: " + fmt(fm, b) + (fm.gate ? " · goal " + gateText(fm) : "")) + '"><span class="cell">' + dot(s(b)) + esc(fmtShort(fm, b)) + "</span></td>" + chg(c.dir, fmtShort(fm, a), fmtShort(fm, b));
  }
  var KEY_IDS = ["passes_up_to", "tracking_rms_09", "tracking_peak_09", "tip_stop_09", "tip_stop_worst_09", "tip_tracking_09", "gates_passed", "perf_gates", "sim_stop", "sim_predicts", "goal_met", "stations_tracking"];
  function otherCell(x, rid) {
    var fm = fidMetric(x);
    var others = x.metrics.filter(function (m) { return m.family !== "evidence" && m !== fm && KEY_IDS.indexOf(m.id) < 0; });
    return others.length ? '<td class="ty bl" title="' + esc(others.map(function (m) { return (m.code ? m.code + " " : "") + m.name + " " + fmt(m, m.values[rid]); }).join(" · ")) + '">' + others.map(function (m) { var s = m.kind === "shown" && m.values[rid].status === "fail" ? "watch" : m.values[rid].status; return dot(s) + " " + esc((m.code || "") + " " + fmtShort(m, m.values[rid])); }).join(" &nbsp;") + "</td>" : '<td class="muted bl">—</td>';
  }
  function tableCols(st) {
    var rid = st.mode === "changed" ? "r8" : st.round, withQ = st.cols === "questions", P = perfCols();
    var sub = '<th class="bl sub" title="round 0 · as found, before any fit">Round 0</th><th class="sub" title="' + esc(rn("r8")) + ' · now">Now</th><th class="sub" title="round 0 → now">Δ</th>';
    var head = '<tr><th rowspan="3" class="nmh">Typed component tree</th><th rowspan="3">Type</th><th class="grp bl perf" colspan="' + P.length * 3 + '">Performance · real vs the target</th>' +
      '<th class="grp bl fid" colspan="3">Fidelity · real vs sim</th><th rowspan="3" class="bl">Other</th>' +
      (withQ ? '<th class="grp bl" colspan="5">The five questions · ' + esc(st.mode === "changed" ? rn("r0") + " → " + rn("r8") : round(rid).label) + '</th><th rowspan="3" class="bl">Verdict</th>' : "") + "</tr>" +
      "<tr>" + P.map(function (c) { return '<th colspan="3" class="bl mh" data-col="' + c.id + '">' + esc(c.name) + "<small>" + esc(c.goal) + "</small></th>"; }).join("") +
      '<th colspan="3" class="bl mh" data-col="twin">Twin ÷ floor<small>goal ≤ ' + FX.thresholds.sim_vs_real_floor_ratio + "×</small></th>" +
      (withQ ? FX.questions.map(function (q, i) { return '<th rowspan="2" data-q="' + q.id + '" class="' + (i === 0 ? "bl" : "") + '">' + q.n + " " + q.name + "<small>" + esc(q.ask) + "</small></th>"; }).join("") : "") + "</tr>" +
      "<tr>" + P.map(function () { return sub; }).join("") + sub + "</tr>";
    return { head: head, withQ: withQ,
      cells: function (x) {
        var h = P.map(function (c) { return trio(x, c); }).join("") + fidTrio(x) + otherCell(x, rid);
        if (!withQ) return h;
        var v = st.mode === "changed" ? dot(lineStatus(x, "r0")) + '<span class="arrow">→</span>' + dot(lineStatus(x, "r8")) : (function () { var s = lineStatus(x, rid); return '<span class="cell">' + dot(s) + esc(s === "none" ? "no gates" : WORD[s]) + (x.verdict[rid].first ? " · " + Q[x.verdict[rid].first].name : "") + "</span>"; })();
        return h + FX.questions.map(function (q, i) { return qcell(x, q, rid, st.mode, i === 0); }).join("") + '<td class="q bl ' + (st.mode === "changed" ? "" : lineStatus(x, rid)) + '">' + v + "</td>";
      } };
  }
  function qcell(x, q, rid, mode, first) {
    var s = x.questions[rid][q.id], cls = "q" + (first ? " bl" : ""), dq = ' data-q="' + q.id + '"';
    if (mode === "changed") {
      var a = x.questions.r0[q.id], b = x.questions.r8[q.id], m = b.metric ? metric(x, b.metric) : null;
      if (b.status === "none") return '<td class="' + cls + ' none"' + dq + ">—</td>";
      var moved = a.status !== b.status || (m && JSON.stringify(m.values.r0.value) !== JSON.stringify(m.values.r8.value));
      return '<td class="' + cls + " " + (moved ? "" : "same") + '"' + dq + '><span class="cell">' + dot(a.status) + '<span class="was">' + (m ? esc(fmtShort(m, m.values.r0)) : "") + '</span><span class="arrow">→</span>' + dot(b.status) + (m ? esc(fmtShort(m, m.values.r8)) : "") + "</span></td>";
    }
    var mm2 = s.metric ? metric(x, s.metric) : null;
    if (s.status === "none") return '<td class="' + cls + ' none"' + dq + ">" + (s.via && s.via.length ? "" : "—") + "</td>";
    var text = s.status === "not_observable" ? "not observable" : mm2 ? fmtShort(mm2, mm2.values[rid]) : "";
    return '<td class="' + cls + " " + s.status + '"' + dq + ' title="' + esc(q.name + " at " + x.short + ": " + (WORD[s.status] || "") + (s.via && s.via.length ? " (via " + s.via.map(function (id) { return node(id).short; }).join(", ") + ")" : "")) + '"><span class="cell">' + dot(s.status) + esc(text) + (s.misses ? '<span class="misses" title="counted gates that miss (in the 180, not the goal)">+' + s.misses + "</span>" : "") + "</span></td>";
  }
  function keyMetric(x, rid) {
    var v = x.verdict[rid]; if (v.first) return metric(x, x.questions[rid][v.first].metric);
    var pref = { deployment: "perf_gates", station: "passes_up_to", servo: "T2" }[x.level];
    return (pref && metric(x, pref)) || x.metrics[0] || null;
  }
  function table(st) {
    if (!tableFolded) tableFolded = new Set(load("table.folded", FX.nodes.filter(function (x) { return x.level === "servo"; }).map(function (x) { return x.id; })));
    var sel = st.node, cols = tableCols(st), rows = [];
    walk(function (x, depth) {
      for (var p = parent(x.id); p; p = parent(p.id)) if (tableFolded.has(p.id)) return;
      var moved = st.mode !== "changed" || FX.questions.some(function (q) { var a = x.questions.r0[q.id], b = x.questions.r8[q.id]; return a.status !== b.status; }) || x.metrics.some(function (m) { return JSON.stringify(m.values.r0.value) !== JSON.stringify(m.values.r8.value); });
      rows.push('<tr data-id="' + esc(x.id) + '" class="' + (x.id === sel ? "sel" : "") + (moved ? "" : " same") + '"><td class="nmc"><span class="nm" style="padding-left:' + depth * 16 + 'px">' +
        '<span class="tw" ' + (x.children.length ? 'data-tw="1"' : 'style="visibility:hidden"') + '><svg viewBox="0 0 12 12" style="transform:rotate(' + (tableFolded.has(x.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' +
        // WHY the short name only: the sidebar's tree already carries each station's line; the Sheet's width goes to the numbers
        icon(x.type.id) + '<b title="' + esc(x.title + (x.line ? " · " + x.line : "")) + '">' + esc(x.short) + '</b></span></td><td class="ty" title="' + esc(x.type.name) + '">' + esc(x.type.name) + "</td>" + cols.cells(x) + "</tr>");
    });
    var groupBtn = '<span class="lab">Column group</span><button class="dw-btn" data-cols="questions" aria-pressed="' + cols.withQ + '" title="' + (cols.withQ ? "Hide" : "Show") + ' the five questions: Floor → Data → Routines → Twin → Job">' + (cols.withQ ? "✓ " : "+ ") + "Five questions</button>";
    var note = st.mode === "changed" ? "What changed: rows that did not move are dimmed" + (cols.withQ ? "; each question cell reads " + rn("r0") + " → " + rn("r8") : "") : "Every metric: round 0 (as found) · now (" + rn("r8") + ") · change";
    $("dw-tablewrap").innerHTML = '<div class="dw-ttools"><span class="lab">' + esc(note) + '</span><span class="dw-grow"></span>' + groupBtn + "</div>" +
      '<table class="dw-tt"><thead>' + cols.head + "</thead><tbody>" + rows.join("") + "</tbody></table>";
    $("dw-tablewrap").querySelectorAll("[data-cols]").forEach(function (b) { b.addEventListener("click", function () { go({ cols: cols.withQ ? "" : "questions" }, true); }); });
    var tr = $("dw-tablewrap").querySelector("tr.sel"); if (tr && tr.scrollIntoView) tr.scrollIntoView({ block: "nearest" });
  }
  $("dw-tablewrap").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]"); if (!tr) return;
    var id = tr.dataset.id;
    if (ev.target.closest("[data-tw]")) { if (tableFolded.has(id)) tableFolded.delete(id); else tableFolded.add(id); save("table.folded", Array.from(tableFolded)); table(state()); return; }
    if (node(id) && node(id).level === "servo" && tableFolded.has(id)) { tableFolded.delete(id); save("table.folded", Array.from(tableFolded)); }
    save("insp.folded", false);
    if (!go({ node: id }, true)) render();
  });

  // ---- the right inspector (Scene and Sheet): the picked node, performance first, then fidelity; it folds (Esc or the toggle) -------------
  function rightOpen() { return !load("insp.folded", false); }
  function setRight(open) { save("insp.folded", !open); render(); }
  function perfMini(x, rid) {
    var o = other(rid), t = FX.thresholds, was = round(o).label.toLowerCase() + " ";
    function ok(v, g) { return v == null ? null : v <= g ? "pass" : "fail"; }
    if (x.level === "station") {
      var r = rung(x, rid, 0.9), r0 = rung(x, o, 0.9), up = metric(x, "passes_up_to");
      return '<h3>Performance · ' + esc(round(rid).label + ", " + round(rid).long) + '</h3><div class="dw-tiles mini">' +
        tile("Highest rung tracked", up.values[rid].value > 0 ? n(up.values[rid].value, 1) + " of top speed" : "none", up.values[rid].status, "goal ≥ 0.9", was + (up.values[o].value > 0 ? n(up.values[o].value, 1) : "none")) +
        tile("Tracking RMS at 0.9", deg(r.tracking_rms_deg), ok(r.tracking_rms_deg, t.tracking_rms_deg), "GOOD ≤ " + t.tracking_rms_deg + "°", was + deg(r0.tracking_rms_deg)) +
        tile("Tip stop at 0.9, median", mm(r.stop_tool_mm), ok(r.stop_tool_mm, t.stop_tool_mm), "GOOD ≤ " + t.stop_tool_mm + " mm", was + mm(r0.stop_tool_mm)) +
        tile("Worst single stop at 0.9", mm(r.stop_tool_max_mm), null, "not the gate", was + mm(r0.stop_tool_max_mm)) + "</div>" +
        '<div class="dw-plots one"><div class="pc">' + rungPlot(x, "tracking_rms_deg", rid) + "</div></div>";
    }
    if (x.level === "deployment") {
      var tr = metric(x, "stations_tracking"), pg = metric(x, "perf_gates");
      return '<h3>Performance · ' + esc(round(rid).label + ", " + round(rid).long) + '</h3><div class="dw-tiles mini">' +
        tile("Stations tracking to 0.9", tr.values[rid].value + " of 6", tr.values[rid].status, "goal 6 of 6", was + tr.values[o].value) +
        tile("Real performance gates", pg.values[rid].value + " of " + pg.values[rid].of, pg.values[rid].value === pg.values[rid].of ? "pass" : null, "tracking + tip stop, every rung", was + pg.values[o].value) + "</div>";
    }
    return "";
  }
  function ichildren(x, rid) {
    if (!x.children.length) return "";
    var title = x.level === "station" ? "Under this station · shown, not gating" : x.level === "servo" ? "Its parts · pulled apart in the 3D" : "Under it";
    return '<div class="dw-ichilds"><h3>' + esc(title) + "</h3>" + kids(x.id).map(function (k) {
      return '<div class="dw-crow" data-node="' + esc(k.id) + '">' + dot(lineStatus(k, rid)) + icon(k.type.id) + "<b>" + esc(k.short) + '</b><span class="cl">' + esc(oneLine(k, rid)) + "</span></div>";
    }).join("") + "</div>";
  }
  function inspector(x, rid) {
    var body = $("dw-inspBody");
    body.innerHTML = '<div class="dw-insp-head">' + icon(x.type.id) + '<b title="' + esc(x.title) + '">' + esc(x.title) + "</b>" + link({ view: "", tab: "" }, "Open in Workbench", "dw-btn") +
      '<button class="dw-iconbtn" data-fold title="Fold the inspector (Esc)" aria-label="Fold the inspector">' + SVG.close + "</button></div>" +
      '<div class="dw-insp-body">' + answerHTML(x, rid) + perfMini(x, rid) + ichildren(x, rid) +
      (x.metrics.length ? "<h3>Every metric · round 0 → now</h3>" + metricTable(x, rid, { compact: true }) : "") + (x.metrics.length ? "<h3>Five questions</h3>" + fiveQuestions(x, rid, true) : "") + "</div>";
    body.querySelector("[data-fold]").addEventListener("click", function () { setRight(false); });
    body.querySelectorAll("[data-node]").forEach(function (b) { b.addEventListener("click", function () { go({ node: b.dataset.node }); }); });
  }
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && (VIEW === "sheet" || VIEW === "scene") && rightOpen() && ev.target.tagName !== "INPUT") setRight(false); });

  // ---- the Scene (V3): the 3D is the page; every station wears its performance in place; a time bar moves between the rounds ---------
  function scene(st) {
    var x = node(st.node) || node(FX.root), rid = st.mode === "changed" ? "r8" : st.round;
    mount3d($("dw-stage"));
    sync3d(x, rid);
    var root = node(FX.root), pg = metric(root, "perf_gates"), tr = metric(root, "stations_tracking"), tw = metric(root, "stations_twinned");
    function when(r) { return round(r).scored_utc.slice(5, 10); }
    $("dw-timebar").innerHTML = '<span class="tb-l">As found<small>' + esc(rn("r0")) + " · " + esc(when("r0")) + '</small></span><input id="dw-time" type="range" min="0" max="1" step="1" value="' + (rid === "r0" ? 0 : 1) + '" aria-label="' + esc("Round shown: as found (" + rn("r0") + ") or now (" + rn("r8") + ")") + '">' +
      '<span class="tb-r">Now<small>' + esc(rn("r8")) + " · " + esc(when("r8")) + "</small></span>" +
      '<span class="tb-sum"><span><b>' + pg.values[rid].value + " of " + pg.values[rid].of + "</b> real performance gates</span><span><b>" + tr.values[rid].value + " of 6</b> track to 0.9" + (tw ? " · <b>" + tw.values[rid].value + " of 6</b> twinned" : "") + "</span></span>";
    $("dw-time").addEventListener("input", function () { go({ round: this.value === "0" ? "r0" : "r8", mode: "" }, true); });
  }

  // ---- the Runs view: every run of a round, the summary first, each with its Rerun recording ------------------------------------------
  var runSort = load("runs.sort", { key: "station", dir: 1 });
  function loadRuns() {
    if (RUNS) return Promise.resolve(RUNS);
    if (!runsLoading) runsLoading = fetch(DATA.runs_url).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (d) { RUNS = d; return d; });
    return runsLoading;
  }
  var RCOLS = [
    ["station", "Station"], ["fraction", "Rung"], ["speed_rad_s", "Speed"], ["kind", "Kind"], ["name", "Run"],
    ["tracking_rms_deg", "Tracking RMS"], ["tracking_peak_deg", "Tracking peak"], ["tracks", "Meets the goal"],
    ["sim_tracking_rms_deg", "Sim's RMS"], ["sim_vs_real_deg", "Sim vs real"], ["stops", "Stops"], ["fault", "Fault"], ["replay_url", "Recording"],
  ];
  function runs(st) {
    var el = $("dw-runs");
    if (!RUNS) { el.innerHTML = '<p class="muted">Loading every run…</p>'; loadRuns().then(function () { if (state().view === "runs") runs(state()); }).catch(function (e) { el.innerHTML = '<p class="muted">The runs table did not load (' + esc(e.message) + ").</p>"; }); return; }
    var rows = RUNS.rows, rounds = [];
    rows.forEach(function (r) { if (rounds.indexOf(r.round) < 0) rounds.push(r.round); });
    rounds.sort(function (a, b) { return a - b; });
    // "now" is the Now column's round (the same scorecard everywhere on the page); the last round with runs only if the tree has none
    var nowR = FX && round("r8") ? round("r8").round : rounds[rounds.length - 1];
    var rr = st.rr != null && st.rr !== "" && rounds.indexOf(+st.rr) >= 0 ? +st.rr : rounds.indexOf(nowR) >= 0 ? nowR : rounds[rounds.length - 1];
    var t = RUNS.thresholds || FX.thresholds;
    var mine = rows.filter(function (r) { return r.round === rr; });
    var f = { st: st.st, kind: st.raw.get("kind") || "", rung: st.raw.get("rung") || "", miss: st.raw.get("miss") === "1", q: (st.q || "").toLowerCase() };
    var shown = mine.filter(function (r) {
      return (!f.st || r.station === f.st) && (!f.kind || r.kind === f.kind) && (!f.rung || String(r.fraction) === f.rung) && (!f.miss || r.tracks === "fail") &&
        (!f.q || (r.name + " " + canName(r.station) + " " + r.kind).toLowerCase().indexOf(f.q) >= 0);
    });
    var k = runSort.key, d = runSort.dir;
    shown.sort(function (a, b) {
      var x = a[k], y = b[k];
      if (k === "station") { x = +a.station.replace("can", ""); y = +b.station.replace("can", ""); }
      if (x == null && y == null) return 0; if (x == null) return 1; if (y == null) return -1;
      if (x < y) return -d; if (x > y) return d;
      return a.fraction - b.fraction || (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);
    });
    var meets = mine.filter(function (r) { return r.tracks === "pass"; }).length, judged = mine.filter(function (r) { return r.tracks !== "not_run"; }).length;
    var faults = mine.filter(function (r) { return r.fault; }).length, recs = mine.filter(function (r) { return r.replay_url; }).length;
    var rms = mine.map(function (r) { return r.tracking_rms_deg; }).filter(function (v) { return v != null; }).sort(function (a, b) { return a - b; });
    var med = rms.length ? rms[Math.floor(rms.length / 2)] : null;
    var at09 = mine.filter(function (r) { return r.fraction === 0.9; }), at09ok = at09.filter(function (r) { return r.tracks === "pass"; }).length;
    var sts = ["can1", "can11", "can12", "can13", "can14", "can15"];
    var selSt = stationOf(st.node);
    var only = selSt && selSt.id !== f.st ? '<button class="dw-btn" data-st="' + esc(selSt.id) + '" title="The tree\'s selection is ' + esc(node(st.node).short) + '">Only ' + esc(canName(selSt.id)) + "'s runs (selected)</button>" : "";
    var stBtns = '<button data-st="" aria-pressed="' + (!f.st) + '">All stations</button>' + sts.map(function (s) {
      var m = mine.filter(function (r) { return r.station === s; }), ok = m.filter(function (r) { return r.tracks === "pass"; }).length;
      return '<button data-st="' + s + '" aria-pressed="' + (f.st === s) + '" title="' + esc(canName(s) + " · " + (node(s) ? node(s).line : "")) + '">' + dot(m.length && ok === m.length ? "pass" : ok ? "watch" : "fail") + esc(canName(s)) + ' <span class="muted">' + ok + "/" + m.length + "</span></button>";
    }).join("");
    var head = RCOLS.map(function (c) { return "<th" + (c[0] === "replay_url" ? ' class="nosort"' : ' data-sort="' + c[0] + '"' + (k === c[0] ? ' aria-sort="' + (d > 0 ? "ascending" : "descending") + '"' : "")) + ">" + esc(c[1]) + "</th>"; }).join("");
    var body = shown.map(function (r) {
      var bad = function (v, g) { return v != null && v > g ? ' class="f"' : ""; };
      var rec = r.replay_url ? '<a class="rr" href="' + esc(r.replay_url) + '" target="_blank" rel="noopener" title="' + esc("Opens " + (r.rrd || "") + " in the native Rerun viewer (the bam-replay-link launcher on 127.0.0.1:8771)" + (r.rrd_via === "identical copy" ? "; the recording of a byte-identical copy of this run" : "")) + '">Open in Rerun ↗</a>'
        : '<span class="muted" title="' + esc(r.rrd ? "recorded, but no replay launcher on this machine: " + r.rrd : "no .rrd was built for this run") + '">' + (r.rrd ? "recorded · no launcher" : "no recording yet") + "</span>";
      return "<tr><td>" + link({ view: "", node: r.station, tab: "" }, esc(canName(r.station))) + "</td><td>" + r.fraction + "</td><td>" + degPerS(r.speed_rad_s) + "</td>" +
        "<td>" + esc(r.kind === "held_out" ? "held-out" : r.kind) + '</td><td class="mono" title="' + esc(r.run) + '">' + esc(r.name) + "</td>" +
        "<td" + bad(r.tracking_rms_deg, t.tracking_rms_deg) + ">" + deg(r.tracking_rms_deg) + "</td><td" + bad(r.tracking_peak_deg, t.tracking_peak_deg) + ">" + deg(r.tracking_peak_deg) + "</td>" +
        "<td>" + dot(r.tracks, r.tracks === "pass" ? "meets RMS ≤ " + t.tracking_rms_deg + "° and peak ≤ " + t.tracking_peak_deg + "°" : r.tracks === "fail" ? "misses the tracking goal" : "not judged") + " " + esc(r.tracks === "pass" ? "yes" : r.tracks === "fail" ? "no" : "—") + "</td>" +
        "<td>" + deg(r.sim_tracking_rms_deg) + "</td><td>" + (r.sim_vs_real_deg == null ? '<span class="muted">—</span>' : deg(r.sim_vs_real_deg, 3)) + "</td><td>" + (r.stops == null ? "—" : r.stops) + "</td><td" + (r.fault ? ' class="f"' : "") + ">" + (r.fault ? "fault" : "—") + "</td><td>" + rec + "</td></tr>";
    }).join("");
    el.innerHTML = '<div class="dw-rtop"><h2>Runs · ' + esc(DATA.deployments.filter(function (x) { return x.id === st.dep; })[0].title) + '</h2><div class="dw-seg" role="group" aria-label="Round">' +
      rounds.map(function (r) { return '<button data-rr="' + r + '" aria-pressed="' + (r === rr) + '" title="' + esc("round " + r + (r === 0 ? " · as found, before any fit" : r === nowR ? " · now, scored " + scoredDay("r8") : "")) + '">Round ' + r + (r === 0 ? " · as found" : r === nowR ? " · now" : "") + "</button>"; }).join("") + "</div></div>" +
      '<div class="dw-rsum">' + tile("Runs in round " + rr, String(mine.length), null, "on 6 stations, 6 speed rungs", "") +
      tile("Meet the tracking goal", meets + " of " + judged, meets === judged ? "pass" : null, "RMS ≤ " + t.tracking_rms_deg + "° and peak ≤ " + t.tracking_peak_deg + "°, no fault", "") +
      tile("At the goal's rung (0.9)", at09ok + " of " + at09.length, at09ok === at09.length ? "pass" : null, "runs meeting the tracking goal", "") +
      tile("Median tracking RMS", deg(med), med != null ? (med <= t.tracking_rms_deg ? "pass" : "fail") : null, "GOOD ≤ " + t.tracking_rms_deg + "°", "") +
      tile("Faults", String(faults), faults ? "fail" : "pass", "in this round's runs", "") +
      tile("Rerun recordings", recs + " of " + mine.length, null, recs < mine.length ? "the rest: no recording yet" : "one click each", "") + "</div>" +
      '<div class="dw-rst">' + stBtns + "</div>" +
      '<div class="dw-rfilters"><label>Rung <select data-f="rung"><option value="">all</option>' + [0.2, 0.4, 0.6, 0.8, 0.9, 1].map(function (x) { return '<option value="' + x + '"' + (f.rung === String(x) ? " selected" : "") + ">" + x + " of top speed</option>"; }).join("") + "</select></label>" +
      '<label>Kind <select data-f="kind"><option value="">all</option><option value="repeat"' + (f.kind === "repeat" ? " selected" : "") + '>repeat</option><option value="held_out"' + (f.kind === "held_out" ? " selected" : "") + ">held-out</option></select></label>" +
      '<label><input type="checkbox" data-f="miss"' + (f.miss ? " checked" : "") + "> only runs that miss the goal</label>" +
      '<input type="search" data-f="q" placeholder="Filter by run name…" value="' + esc(st.q) + '" aria-label="Filter runs by name">' + only +
      '<span class="muted">' + shown.length + " of " + mine.length + " runs · click a heading to sort</span></div>" +
      '<table class="dw-rt"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";
    el.querySelectorAll("[data-rr]").forEach(function (b) { b.addEventListener("click", function () { go({ rr: b.dataset.rr }, true); }); });
    // a station picked here is the views' selection too (the tree follows); All stations is the whole deployment
    el.querySelectorAll("[data-st]").forEach(function (b) { b.addEventListener("click", function () { go({ st: b.dataset.st, node: b.dataset.st || FX.root }, true); }); });
    el.querySelectorAll("[data-sort]").forEach(function (th) { th.addEventListener("click", function () { var key = th.dataset.sort; runSort = { key: key, dir: runSort.key === key ? -runSort.dir : 1 }; save("runs.sort", runSort); runs(state()); }); });
    el.querySelectorAll("select[data-f]").forEach(function (s) { s.addEventListener("change", function () { var p = {}; p[s.dataset.f] = s.value; go(p, true); }); });
    var miss = el.querySelector('input[data-f="miss"]'); miss.addEventListener("change", function () { go({ miss: miss.checked ? "1" : "" }, true); });
    var q = el.querySelector('input[data-f="q"]'), timer = null;
    q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { go({ q: q.value }, true); var again = $("dw-runs").querySelector('input[data-f="q"]'); if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); } }, 200); });
  }

  // ---- Obsidian's frame: the ribbon, the sidebar and its toggle, the tooltips, the bar and the trail -------------------------------------
  var tip = document.getElementById("dw-tip"), tipFor = null, tipTimer = null;
  function hideTip() { clearTimeout(tipTimer); tipFor = null; if (tip) tip.hidden = true; }
  function showTip(el) {
    var text = el.getAttribute("data-tip"); if (!tip || !text || !el.isConnected || el.hidden) return;
    var pos = el.getAttribute("data-tip-pos") || "right", r = el.getBoundingClientRect();
    tip.textContent = text; tip.className = "dw-tip mod-" + pos; tip.hidden = false;
    var arrow = document.createElement("span"); arrow.className = "dw-tip-arrow"; tip.appendChild(arrow);
    // WHY right of the icon: Obsidian's ribbon tooltips sit to the right (.tooltip.mod-right), vertically centred, an arrow pointing back
    if (pos === "left") { tip.style.left = (r.left - 8) + "px"; tip.style.top = (r.top + r.height / 2) + "px"; }
    else { tip.style.left = (r.right + 8) + "px"; tip.style.top = (r.top + r.height / 2) + "px"; }
  }
  document.addEventListener("mouseover", function (ev) {
    var el = ev.target.closest && ev.target.closest("[data-tip]");
    if (el === tipFor) return;
    hideTip();
    if (!el) return;
    tipFor = el;
    tipTimer = setTimeout(function () { showTip(el); }, 250);
  });
  document.addEventListener("focusin", function (ev) { var el = ev.target.closest && ev.target.closest("[data-tip]"); hideTip(); if (el && el.matches(":focus-visible")) { tipFor = el; showTip(el); } });
  document.addEventListener("focusout", hideTip);
  document.addEventListener("pointerdown", hideTip);

  function workbenchDeps() { return DATA ? Object.keys(DATA.trees) : []; }
  function ribbon(st, view) {
    var deps = workbenchDeps(), dep = st.dep && DATA.trees[st.dep] ? st.dep : (deps.indexOf(load("last.dep", "")) >= 0 ? load("last.dep", "") : deps[0]);
    var title = dep ? (DATA.deployments.filter(function (d) { return d.id === dep; })[0] || { title: dep }).title : "";
    document.querySelectorAll(".dw-rb").forEach(function (a) {
      var v = a.dataset.v, base = a.dataset.tipBase || (a.dataset.tipBase = a.getAttribute("data-tip"));
      if (v === "home") a.setAttribute("href", location.pathname);
      else if (!dep) a.hidden = true;  // no deployment with a typed tree (its scorecards missing): nothing for the view to open
      else {
        a.hidden = false;
        // from the Deployments list, a view opens the deployment last opened (Obsidian reopens your last workspace)
        a.setAttribute("href", st.dep ? href({ view: v }) : location.pathname + "?d=" + encodeURIComponent(dep) + (v === "page" ? "" : "&view=" + v));
        a.setAttribute("data-tip", st.dep ? base : base + " · opens " + title);
      }
      if (v === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  function sideOpen() { return !!load("side.open", true); }
  function setToggle(b, open, what) {
    b.setAttribute("aria-expanded", String(open));
    var label = (open ? "Collapse the " : "Expand the ") + what;
    b.setAttribute("aria-label", label); b.setAttribute("data-tip", label);
    // Obsidian's sidebar icon: the filled bar inside the frame widens when its sidebar is open (8.33 % closed, 24 % open)
    b.querySelector(".inner").setAttribute("width", open ? "4.3" : "1.6");
  }
  function layoutSide(view) {
    var has = view !== "home", open = has && sideOpen();
    $("dw-left").hidden = !open; $("dw-sashL").hidden = !open;
    $("dw-sidetoggle").hidden = !has;
    setToggle($("dw-sidetoggle"), open, "sidebar");
    host.classList.toggle("side-closed", !open);
  }
  $("dw-sidetoggle").addEventListener("click", function () { save("side.open", !sideOpen()); hideTip(); layoutSide(VIEW); });
  $("dw-unfold").addEventListener("click", function () { hideTip(); setRight(!rightOpen()); });
  function layoutRight(view) {
    var has = view === "scene" || view === "sheet", open = has && rightOpen();
    $("dw-insp").hidden = !open; $("dw-sashT").hidden = !open;
    $("dw-unfold").hidden = !has;
    if (has) setToggle($("dw-unfold"), open, "inspector");
    var dock = view === "sheet";
    $("dw-dock3d").hidden = !dock; $("dw-sashD").hidden = !dock;
    // WHY empty it when it is not shown: a hidden inspector must not answer a query meant for the page in view
    if (!open) $("dw-inspBody").innerHTML = "";
    return open;
  }
  function bar(st, view) {
    var dep = st.dep ? DATA.deployments.filter(function (d) { return d.id === st.dep; })[0] : null;
    var rb = document.querySelector('.dw-rb[data-v="' + view + '"] svg');
    $("dw-vtitle").innerHTML = (rb ? '<span class="ic">' + rb.outerHTML + "</span>" : "") + "<b>" + esc(VIEW_NAME[view]) + "</b>" + (dep ? '<span class="muted"> · ' + esc(dep.title) + "</span>" : "");
    $("dw-depacts").innerHTML = dep ? wandbLinks(dep) : "";  // the open deployment's W&B, in every view; nothing on the list
    var seg = $("dw-round");
    seg.hidden = view === "home" || view === "runs";
    var nowL = "Now" + (rn("r8") ? " · " + rn("r8") : ""), wasL = "As found" + (rn("r0") ? " · " + rn("r0") : "");
    var opts = view === "sheet" ? [["r8", nowL], ["r0", wasL], ["changed", "What changed"]] : [["r0", wasL], ["r8", nowL]];
    var cur = view === "sheet" && st.mode === "changed" ? "changed" : st.round;
    seg.innerHTML = opts.map(function (o) { return '<button data-r="' + o[0] + '" aria-pressed="' + (o[0] === cur) + '" title="' + esc(o[0] === "changed" ? rn("r0") + " → " + rn("r8") + ", every cell that moved" : o[0] === "r0" ? "the controller as found and the twin unfitted (scored " + scoredDay("r0") + ")" : rn("r8") + ", scored " + scoredDay("r8")) + '">' + esc(o[1]) + "</button>"; }).join("");
    seg.querySelectorAll("button").forEach(function (b) { b.addEventListener("click", function () { var r = b.dataset.r; go(r === "changed" ? { mode: "changed", round: "" } : { mode: "", round: r }, true); }); });
    // the site's trail: Home › Deployments › the deployment › the node › the view
    var crumbs = document.querySelector(".trail nav.crumbs");
    if (crumbs) {
      var parts = ['<a href="/">Home</a>', '<a href="' + location.pathname + '"' + (view === "home" ? ' aria-current="page"' : "") + ">Deployments</a>"];
      if (st.dep) {
        parts.push('<a href="' + esc(href({ node: "", tab: "" })) + '">' + esc(dep ? dep.title : st.dep) + "</a>");
        if (view !== "runs" && FX && st.node && st.node !== FX.root && node(st.node)) ancestors(st.node).slice(1).concat([node(st.node)]).forEach(function (a) { parts.push('<a href="' + esc(href({ node: a.id, tab: "" })) + '">' + esc(a.short) + "</a>"); });
        if (view !== "page") parts.push("<span>" + esc(VIEW_NAME[view]) + "</span>");
      }
      crumbs.innerHTML = parts.join(" › ");
      crumbs.querySelectorAll("a").forEach(function (a) { if (a.getAttribute("href").indexOf(location.pathname) === 0) a.setAttribute("data-go", ""); });
    }
  }
  // a pick in the tree keeps the view; in Runs it also filters the runs to the picked station (the deployment: every station)
  function pick(id) {
    if (VIEW === "runs") { var s = stationOf(id); go({ node: id, st: s ? s.id : "" }); }
    else go({ node: id });
  }
  function render() {
    hideTip();
    var st = state();
    var dep = st.dep && DATA.trees[st.dep] ? st.dep : null;
    FX = dep ? DATA.trees[dep] : null;
    byId = {}; Q = {};
    if (FX) { FX.nodes.forEach(function (x) { byId[x.id] = x; }); FX.questions.forEach(function (q) { Q[q.id] = q; }); }
    if (FX && !node(st.node)) st.node = FX.root;
    var view = !dep ? "home" : VIEWS[st.view] || "page";
    VIEW = view; host.dataset.view = view;
    if (dep) save("last.dep", dep);
    $("dw-home").hidden = view !== "home"; $("dw-dep").hidden = view !== "page"; $("dw-scene").hidden = view !== "scene"; $("dw-table").hidden = view !== "sheet"; $("dw-runs").hidden = view !== "runs";
    ribbon(st, view); bar(st, view); layoutSide(view);
    var right = layoutRight(view);
    document.title = (FX ? (view !== "home" && st.node !== FX.root ? node(st.node).short + " · " : "") + (view !== "page" ? VIEW_NAME[view] + " · " : "") + DATA.trees[dep].title + " · " : "") + "Deployments: sim2real";
    if (view === "home") return home();
    if (!treeUI) {
      treeUI = new Tree($("dw-left"), { round: function () { var s2 = state(); return s2.mode === "changed" ? "r8" : s2.round; }, onSelect: pick });
      sash($("dw-sashL"), $("dw-left"), { key: "tree", min: 220, max: 560, dflt: 300 });
      sash($("dw-sashT"), $("dw-insp"), { key: "insp", min: 320, max: 760, dflt: 420, invert: true });
      sash($("dw-sashD"), $("dw-dock3d"), { key: "dock3d", horizontal: true, min: 140, max: 640, dflt: 260 });
    }
    treeUI.select(st.node);
    var x = node(st.node), rid = st.mode === "changed" ? "r8" : st.round;
    if (view === "page") return entity(st);
    if (view === "runs") return runs(st);
    if (view === "scene") scene(st); else table(st);
    if (right) {
      if (view === "sheet") { mount3d($("dw-dock3d")); sync3d(x, rid); }
      var changed = $("dw-inspBody").dataset.node !== x.id;
      inspector(x, rid);
      $("dw-inspBody").dataset.node = x.id;
      if (changed) $("dw-inspBody").scrollTop = 0;
    } else $("dw-inspBody").dataset.node = "";
  }

  fetch(host.dataset.src).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (d) {
    DATA = d;
    render();
    host.dataset.ready = "1";
  }).catch(function (e) {
    host.innerHTML = '<p class="lede" style="padding:16px">The Deployments workbench could not load its data (' + esc(e.message) + '). Every deployment is also at <a href="/deployments/all/">/deployments/all/</a>.</p>';
  });
})();
