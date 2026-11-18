/* The Deployments workbench (/deployments/; site/deployments_workbench.py writes its data from sim2real.deployments_page).

   The AI pick of the 2026-11-17 proposal round, spliced (docs/proposals/2026-11-17-deployment-page/): V1 Workbench's frame (the typed tree
   on the left, the picked node's page on the right with tabs, a Table view with a foldable inspector, the 3D), V4's banner, question
   columns and "What changed" mode, V2's round 0 · now · change columns, V3's pulled-apart servo; then, by Zach's "# Ok" (2026-11-17:
   "Performance is what matters at the end of the day ... So performance is first and up center"; "Runs are the atomic unit"), every page
   leads with performance (real vs the target, the goal line drawn) and fidelity (real vs sim) sits under it; a Runs view lists every run
   with its Rerun recording.

   State lives in the URL (?d=<deployment>&n=<node>&view=table|runs&tab=...&round=r0|r8&mode=changed&cols=questions&rr=<round>), so every
   view is a link and Back works. WHY no framework: one tree of 45 nodes and a table of a few hundred runs; plain DOM, like the proposals. */
(function () {
  "use strict";
  var host = document.getElementById("dw");
  if (!host) return;
  var $ = function (id) { return document.getElementById(id); };
  var DATA = null, FX = null, byId = {}, Q = {}, RUNS = null, runsLoading = null;
  var rack3d = null, current = null, treeUI = null;

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
      if (v == null || v === "" || (key === "round" && v === "r8") || (key === "n" && FX && v === FX.root)) p.delete(key); else p.set(key, v);
    });
    if (!p.get("d")) { return location.pathname; }
    var qs = p.toString();
    return location.pathname + (qs ? "?" + qs : "");
  }
  function go(patch, replace) {
    var h = href(patch);
    if (h === location.pathname + location.search) return;
    if (replace) history.replaceState(null, "", h); else history.pushState(null, "", h);
    render();
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
  // round by round (0..8): one line per station at the goal's rung, log scale, the goal line drawn; red points miss it
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
        return '<td class="' + cls + '" data-node="' + esc(st.id) + '" title="' + esc(st.short + " · " + f + " of top speed (" + (r.speed_rad_s != null ? r.speed_rad_s + " rad/s" : "—") + ") · " + g[0] + " " + txt + " · goal ≤ " + gate + " " + g[1] + (worst ? " (not the gate: it reads the median)" : "")) + '">' + esc(txt) + "</td>";
      }).join("") + "</tr>";
    });
    return h + "</tbody></table>";
  }

  // ---- metric tables: Round 0 · Now · Change, by family ------------------------------------------------------------------------------
  function metricTable(x, rid, opts) {
    opts = opts || {};
    if (!x.metrics.length) return '<p class="muted">No metrics at this level: ' + esc(x.judged_at) + ".</p>";
    var r0 = "r0", r8 = "r8";
    var cols = opts.compact ? '<tr><th>Metric</th><th title="round 0, as found">Round 0</th><th title="round 8, now">Now</th><th title="round 0 → now"></th></tr>'
      : '<tr><th>Metric</th><th>' + esc(round(r0).label) + ' <span class="muted" style="text-transform:none;letter-spacing:0">round 0</span></th><th>' + esc(round(r8).label) + ' <span class="muted" style="text-transform:none;letter-spacing:0">round 8</span></th><th>Change</th><th class="gate">Goal</th><th>Counts as</th><th>Defined in</th></tr>';
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
  function Rack3D(el, opts) {
    var self = this, THREE = window.THREE;
    el.classList.add("scene");
    if (!THREE || !window.OrbitControls) { el.innerHTML = '<p class="muted" style="padding:16px">The 3D view needs three.js (static/three-orbit-0.186.1.min.js).</p>'; self.select = self.setRound = self.explode = self.resize = function () {}; return; }
    var renderer;
    try { renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); } catch (err) { el.innerHTML = '<p class="muted" style="padding:16px">No WebGL in this browser: the 3D view is off.</p>'; self.select = self.setRound = self.explode = self.resize = function () {}; return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    el.appendChild(renderer.domElement);
    var scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(35, 1, 0.01, 20);
    var HOME = { pos: new THREE.Vector3(0.62, 0.78, 1.55), target: new THREE.Vector3(0.0, 0.34, 0.0) };
    camera.position.copy(HOME.pos);
    var controls = new window.OrbitControls(camera, renderer.domElement);
    controls.target.copy(HOME.target); controls.enableDamping = true; controls.dampingFactor = 0.12; controls.minDistance = 0.18; controls.maxDistance = 4;
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
    var labels = {};
    Object.keys(groups).forEach(function (sid) {
      var l = document.createElement("div"); l.className = "s-label"; l.style.pointerEvents = "auto"; l.dataset.id = sid;
      l.addEventListener("click", function (ev) { ev.stopPropagation(); opts.onPick(sid); });
      labelLayer.appendChild(l); labels[sid] = l;
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
      tweenTo(controls.target.clone().add(new THREE.Vector3(d[0], d[1], d[2]).normalize().multiplyScalar(dist)), controls.target.clone());
    });
    var selected = null, rid = "r8", exploded = null, tween = null, dirty = true, t0 = performance.now();
    function selectedStation() { var st = selected ? stationOf(selected) : null; return st ? st.id : null; }
    function paint() {
      Object.keys(groups).forEach(function (sid) {
        var st = node(sid).verdict[rid].status;
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
        var l = labels[sid], x = node(sid), v = x.verdict[rid];
        l.hidden = !img.hidden;
        var up = metric(x, "passes_up_to").values[rid];
        l.innerHTML = dot(v.status) + "<b>" + esc(x.short) + "</b><small>" + esc(up.value > 0 ? "to " + n(up.value, 1) : "no rung") + (v.status === "fail" && v.first ? " · " + Q[v.first].name : "") + "</small>";
        l.title = x.title + " · " + oneLine(x, rid);
        l.classList.toggle("sel", sid === selectedStation());
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
        var target = new THREE.Vector3(s.x, cy, 0), dist = gg.link === "arm" ? 1.25 : 0.75;
        var dir = camera.position.clone().sub(controls.target).normalize();
        if (exploded === sid) { target.set(s.x, s.y, -0.14); dist = 0.75; dir = new THREE.Vector3(0.85, 0.3, 0.45).normalize(); }
        tweenTo(target.clone().add(dir.multiplyScalar(dist)), target);
      } else if (focus && !sid) tweenTo(HOME.pos.clone(), HOME.target.clone());
      paint();
    };
    self.setRound = function (r) { rid = r; paint(); };
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
    function resize() { var w = el.clientWidth, hh = el.clientHeight; if (!w || !hh) return; renderer.setSize(w, hh, false); camera.aspect = w / hh; camera.updateProjectionMatrix(); dirty = true; }
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
      var w = el.clientWidth, hh = el.clientHeight;
      Object.keys(labels).forEach(function (k3) {
        if (labels[k3].hidden) return;
        v3.copy(groups[k3].anchor).project(camera);
        labels[k3].style.left = ((v3.x + 1) / 2 * w) + "px"; labels[k3].style.top = ((1 - v3.y) / 2 * hh) + "px"; labels[k3].style.display = v3.z > 1 ? "none" : "";
      });
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
      return d.workbench ? '<a class="dw-drow" data-go href="' + esc(location.pathname + "?d=" + encodeURIComponent(d.id)) + '" data-dep="' + esc(d.id) + '">' + img + t + head + "</a>"
        : '<a class="dw-drow" href="' + esc(d.page) + '" data-dep="' + esc(d.id) + '">' + img + t + head + "</a>";
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
    var el = $("dw-entity"), keep = rack3d && rack3d._host;
    el.innerHTML = html;
    if (!keep) { keep = document.createElement("div"); rack3d = new Rack3D(keep, { onPick: function (id) { go({ node: id, view: "" }); } }); rack3d._host = keep; }
    $("dw-sceneWrap").appendChild(keep);
    sash($("dw-sashS"), $("dw-sceneWrap"), { key: "scene", horizontal: true, min: 140, max: 640, dflt: 280, onResize: function () { if (rack3d) rack3d.resize(); } });
    var station = stationOf(x.id);
    rack3d.explode(x.level === "servo" || x.level === "part" ? (station && x.id.indexOf("/link") < 0 ? station.id : null) : null);
    rack3d.setRound(rid);
    var changed = current !== x.id;
    if (changed) el.scrollTop = 0;
    rack3d.select(x.id === FX.root ? null : x.id, changed);
    current = x.id;
    el.querySelectorAll("[data-tab]").forEach(function (b) { b.addEventListener("click", function () { go({ tab: b.dataset.tab }, true); }); });
    var body = $("dw-tabbody");
    if (tab === "perf") body.innerHTML = x.level === "deployment" ? perfRack(x, rid) : perfStation(x, rid);
    else if (tab === "metrics") body.innerHTML = '<p class="lede">Every metric at this level, performance first, round 0 (as found, before any fit) beside now (round 8) and which way it moved.</p>' + metricTable(x, rid) + children(x, rid);
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
      'Caveat: round 0 was scored against the plan tick, later rounds against the measured target (re-scored the later way, round 0 reads worse, not better), and CAN 11\'s top speed doubled after round 0.</p>' +
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
    var omega = x.omega[o] !== x.omega[rid] ? "each rung is a fraction of that round's top speed: " + x.omega.r0 + " rad/s in round 0, " + x.omega.r8 + " rad/s now" : "top speed " + x.omega[rid] + " rad/s in both rounds";
    return "<h3>Where it stands · " + esc(round(rid).label + ", " + round(rid).long) + "</h3>" + tiles +
      '<h3>Up the speed ladder · the goal line drawn</h3><div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">' + legend(rid) + '<span class="muted" style="font-size:12px">' + esc(omega) + "</span></div>" +
      '<div class="dw-plots">' + Object.keys(RUNG_KEYS).map(function (k) { return '<div class="pc">' + rungPlot(x, k, rid) + "</div>"; }).join("") + "</div>" +
      '<h3>Round by round</h3><div class="dw-plots wide"><div class="pc">' + historyPlot("tracking_rms_09", x.id) + '</div><div class="pc">' + historyPlot("stop_max_09", x.id) + "</div></div>" + children(x, rid);
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

  // ---- the Table view: the nested tree-table; performance columns or the five questions; What changed -------------------------------
  var tableFolded = null;
  function tableCols(st) {
    var rid = st.mode === "changed" ? "r8" : st.round;
    if (st.cols === "questions") {
      return { head: '<tr><th rowspan="2">Typed component tree</th><th rowspan="2">Type</th><th class="grp bl" colspan="5">The five questions, in order</th><th rowspan="2" class="bl">Verdict</th><th class="grp bl" colspan="4">Key metric · round 0 → now</th></tr><tr>' +
        FX.questions.map(function (q, i) { return '<th class="' + (i === 0 ? "bl" : "") + '">' + q.n + " " + q.name + "<small>" + esc(q.ask) + "</small></th>"; }).join("") + '<th class="bl">Metric</th><th>Round 0</th><th>Now</th><th>Change</th></tr>',
        cells: function (x) {
          var c = FX.questions.map(function (q, i) { return qcell(x, q, rid, st.mode, i === 0); }).join("");
          var v = st.mode === "changed" ? dot(lineStatus(x, "r0")) + '<span class="arrow">→</span>' + dot(lineStatus(x, "r8")) : (function () { var s = lineStatus(x, rid); return '<span class="cell">' + dot(s) + esc(s === "none" ? "no gates" : WORD[s] === "fails" ? "fails" : WORD[s]) + (x.verdict[rid].first ? " · " + Q[x.verdict[rid].first].name : "") + "</span>"; })();
          var km = keyMetric(x, rid), ch = km ? change(km, "r8") : { dir: "na" };
          return c + '<td class="q bl ' + (st.mode === "changed" ? "" : lineStatus(x, rid)) + '">' + v + "</td>" +
            '<td class="bl">' + (km ? code(km) + esc(km.name) : "") + '</td><td class="was">' + (km ? esc(fmtShort(km, km.values.r0)) : "") + "</td><td><b>" + (km ? esc(fmtShort(km, km.values.r8)) : "") + "</b></td><td>" + arrow(ch) + "</td>";
        } };
    }
    return { head: '<tr><th rowspan="2">Typed component tree</th><th rowspan="2">Type</th><th class="grp bl" colspan="5">Performance · real vs the target, at 0.9 of top speed</th><th class="grp bl" colspan="2">Fidelity · real vs sim</th></tr><tr>' +
      '<th class="bl">Highest rung tracked<small>goal ≥ 0.9</small></th><th>Tracking RMS<small>GOOD ≤ ' + FX.thresholds.tracking_rms_deg + "°</small></th><th>Tracking peak<small>GOOD ≤ " + FX.thresholds.tracking_peak_deg + "°</small></th><th>Tip stop, median<small>GOOD ≤ " + FX.thresholds.stop_tool_mm + " mm</small></th><th>Worst stop<small>not the gate</small></th>" +
      '<th class="bl">Twin ÷ floor<small>goal ≤ ' + FX.thresholds.sim_vs_real_floor_ratio + "×</small></th><th>Other</th></tr>",
      cells: function (x) {
        function pc(fn, fmtv, gate, isGate) {
          if (x.level !== "station") return '<td class="q none">—</td>';
          var a = fn("r0"), b = fn("r8"), v = fn(rid);
          if (st.mode === "changed") {
            var moved = a !== b;
            return '<td class="q ' + (moved ? "" : "same") + '"><span class="cell"><span class="was">' + esc(fmtv(a)) + '</span><span class="arrow">→</span>' + (isGate && b != null ? dot(b <= gate || (gate === "up" && b >= 0.9) ? "pass" : "fail") : "") + esc(fmtv(b)) + "</span></td>";
          }
          var s = v == null || !isGate ? "observed" : (gate === "up" ? (v >= 0.9 ? "pass" : "fail") : (v <= gate ? "pass" : "fail"));
          return '<td class="q ' + (isGate ? s : "") + '"><span class="cell">' + (isGate && v != null ? dot(s) : "") + esc(fmtv(v)) + "</span></td>";
        }
        var t = FX.thresholds;
        var perf = pc(function (r) { return metric(x, "passes_up_to").values[r].value; }, function (v) { return v == null ? "—" : v > 0 ? n(v, 1) : "none"; }, "up", true).replace('class="q', 'class="q bl') +
          pc(function (r) { return rung(x, r, 0.9).tracking_rms_deg; }, function (v) { return deg(v); }, t.tracking_rms_deg, true) +
          pc(function (r) { return rung(x, r, 0.9).tracking_peak_deg; }, function (v) { return deg(v); }, t.tracking_peak_deg, true) +
          pc(function (r) { return rung(x, r, 0.9).stop_tool_mm; }, function (v) { return mm(v); }, t.stop_tool_mm, true) +
          pc(function (r) { return rung(x, r, 0.9).stop_tool_max_mm; }, function (v) { return mm(v); }, t.stop_tool_mm, false);
        var fm = metric(x, "twin_over_floor") || metric(x, "T2") || metric(x, "stations_twinned");
        var fid = fm ? (function () {
          var a = fm.values.r0, b = fm.values.r8, v = fm.values[rid], sv = fm.kind === "shown" && v.status === "fail" ? "watch" : v.status;
          if (st.mode === "changed") return '<td class="q bl ' + (fmt(fm, a) === fmt(fm, b) ? "same" : "") + '"><span class="cell"><span class="was">' + esc(fmtShort(fm, a)) + '</span><span class="arrow">→</span>' + dot(fm.kind === "shown" && b.status === "fail" ? "watch" : b.status) + esc(fmtShort(fm, b)) + "</span></td>";
          return '<td class="q bl ' + sv + '"><span class="cell">' + dot(sv) + esc(fmtShort(fm, v)) + "</span></td>";
        })() : '<td class="q bl none">—</td>';
        var others = x.metrics.filter(function (m) { return m.family !== "evidence" && m !== fm && ["passes_up_to", "tracking_rms_09", "tracking_peak_09", "tip_stop_09", "tip_stop_worst_09", "tip_tracking_09", "gates_passed", "perf_gates", "sim_stop", "sim_predicts", "goal_met", "stations_tracking"].indexOf(m.id) < 0; });
        var oth = others.length ? '<td class="ty" title="' + esc(others.map(function (m) { return (m.code ? m.code + " " : "") + m.name + " " + fmt(m, m.values[rid]); }).join(" · ")) + '">' + others.map(function (m) { var s = m.kind === "shown" && m.values[rid].status === "fail" ? "watch" : m.values[rid].status; return dot(s) + " " + esc((m.code || "") + " " + fmtShort(m, m.values[rid])); }).join(" &nbsp;") + "</td>" : '<td class="muted">—</td>';
        return perf + fid + oth;
      } };
  }
  function qcell(x, q, rid, mode, first) {
    var s = x.questions[rid][q.id], cls = "q" + (first ? " bl" : "");
    if (mode === "changed") {
      var a = x.questions.r0[q.id], b = x.questions.r8[q.id], m = b.metric ? metric(x, b.metric) : null;
      if (b.status === "none") return '<td class="' + cls + ' none">—</td>';
      var moved = a.status !== b.status || (m && JSON.stringify(m.values.r0.value) !== JSON.stringify(m.values.r8.value));
      return '<td class="' + cls + " " + (moved ? "" : "same") + '"><span class="cell">' + dot(a.status) + '<span class="was">' + (m ? esc(fmtShort(m, m.values.r0)) : "") + '</span><span class="arrow">→</span>' + dot(b.status) + (m ? esc(fmtShort(m, m.values.r8)) : "") + "</span></td>";
    }
    var mm2 = s.metric ? metric(x, s.metric) : null;
    if (s.status === "none") return '<td class="' + cls + ' none">' + (s.via && s.via.length ? "" : "—") + "</td>";
    var text = s.status === "not_observable" ? "not observable" : mm2 ? fmtShort(mm2, mm2.values[rid]) : "";
    return '<td class="' + cls + " " + s.status + '" title="' + esc(q.name + " at " + x.short + ": " + (WORD[s.status] || "") + (s.via && s.via.length ? " (via " + s.via.map(function (id) { return node(id).short; }).join(", ") + ")" : "")) + '"><span class="cell">' + dot(s.status) + esc(text) + (s.misses ? '<span class="misses" title="counted gates that miss (in the 180, not the goal)">+' + s.misses + "</span>" : "") + "</span></td>";
  }
  function keyMetric(x, rid) {
    var v = x.verdict[rid]; if (v.first) return metric(x, x.questions[rid][v.first].metric);
    var pref = { deployment: "perf_gates", station: "passes_up_to", servo: "T2" }[x.level];
    return (pref && metric(x, pref)) || x.metrics[0] || null;
  }
  function table(st) {
    if (!tableFolded) tableFolded = new Set(load("table.folded", FX.nodes.filter(function (x) { return x.level === "servo"; }).map(function (x) { return x.id; })));
    var rid = st.mode === "changed" ? "r8" : st.round, sel = st.node, cols = tableCols(st), rows = [];
    walk(function (x, depth) {
      for (var p = parent(x.id); p; p = parent(p.id)) if (tableFolded.has(p.id)) return;
      var moved = st.mode !== "changed" || FX.questions.some(function (q) { var a = x.questions.r0[q.id], b = x.questions.r8[q.id]; return a.status !== b.status; }) || x.metrics.some(function (m) { return JSON.stringify(m.values.r0.value) !== JSON.stringify(m.values.r8.value); });
      rows.push('<tr data-id="' + esc(x.id) + '" class="' + (x.id === sel ? "sel" : "") + (moved ? "" : " same") + '"><td><span class="nm" style="padding-left:' + depth * 16 + 'px">' +
        '<span class="tw" ' + (x.children.length ? 'data-tw="1"' : 'style="visibility:hidden"') + '><svg viewBox="0 0 12 12" style="transform:rotate(' + (tableFolded.has(x.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' +
        icon(x.type.id) + '<b title="' + esc(x.title) + '">' + esc(x.short) + '</b> <span class="muted" style="font-size:12px">' + esc(x.level === "station" ? x.line : "") + '</span></span></td><td class="ty" title="' + esc(x.type.name) + '">' + esc(x.type.name) + "</td>" + cols.cells(x) + "</tr>");
    });
    var colSwitch = '<span class="lab">Columns</span><div class="dw-seg" role="group" aria-label="Columns"><button data-cols="perf" aria-pressed="' + (st.cols !== "questions") + '">Performance</button><button data-cols="questions" aria-pressed="' + (st.cols === "questions") + '">Five questions</button></div>';
    var fold = load("insp.folded", false);
    $("dw-tablewrap").innerHTML = '<div class="dw-ttools">' + colSwitch + '<span class="lab">' + esc(st.mode === "changed" ? "Each cell: round 0 → round 8; rows that did not move are dimmed" : round(rid).label + " · " + round(rid).long) + "</span>" +
      (fold ? '<span class="dw-grow"></span><button class="dw-btn" id="dw-unfold" title="Show the inspector">' + SVG.side + " Inspector</button>" : "") + "</div>" +
      '<table class="dw-tt"><thead>' + cols.head + "</thead><tbody>" + rows.join("") + "</tbody></table>";
    $("dw-tablewrap").querySelectorAll("[data-cols]").forEach(function (b) { b.addEventListener("click", function () { go({ cols: b.dataset.cols === "questions" ? "questions" : "" }, true); }); });
    var uf = $("dw-unfold"); if (uf) uf.addEventListener("click", function () { save("insp.folded", false); table(state()); });
    $("dw-table").classList.toggle("folded", fold);
    $("dw-insp").hidden = fold;
    var x = node(sel) || node(FX.root);
    $("dw-insp").innerHTML = '<div class="dw-insp-head">' + icon(x.type.id) + '<b title="' + esc(x.title) + '">' + esc(x.title) + '</b>' + link({ view: "", tab: "" }, "Open page", "dw-btn") + '<button class="dw-iconbtn" data-fold title="Fold the inspector (Esc)">' + SVG.close + "</button></div>" +
      '<div class="dw-insp-body">' + answerHTML(x, rid) + (x.metrics.length ? "<h3>Every metric · round 0 → now</h3>" + metricTable(x, rid, { compact: true }) : "") + (x.metrics.length ? "<h3>Five questions</h3>" + fiveQuestions(x, rid, true) : "") + "</div>";
    $("dw-insp").querySelector("[data-fold]").addEventListener("click", function () { save("insp.folded", true); table(state()); });
    $("dw-insp").querySelectorAll(".dw-answer [data-node]").forEach(function (b) { b.addEventListener("click", function () { go({ node: b.dataset.node }, true); }); });
    var tr = $("dw-tablewrap").querySelector("tr.sel"); if (tr && tr.scrollIntoView) tr.scrollIntoView({ block: "nearest" });
  }
  $("dw-tablewrap").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]"); if (!tr) return;
    var id = tr.dataset.id;
    if (ev.target.closest("[data-tw]")) { if (tableFolded.has(id)) tableFolded.delete(id); else tableFolded.add(id); save("table.folded", Array.from(tableFolded)); table(state()); return; }
    if (node(id) && node(id).level === "servo" && tableFolded.has(id)) { tableFolded.delete(id); save("table.folded", Array.from(tableFolded)); }
    save("insp.folded", false);
    go({ node: id }, true);
  });
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && state().view === "table" && !load("insp.folded", false) && ev.target.tagName !== "INPUT") { save("insp.folded", true); table(state()); } });

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
    var rr = st.rr != null && st.rr !== "" && rounds.indexOf(+st.rr) >= 0 ? +st.rr : rounds[rounds.length - 1];
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
    var stBtns = '<button data-st="" aria-pressed="' + (!f.st) + '">All stations</button>' + sts.map(function (s) {
      var m = mine.filter(function (r) { return r.station === s; }), ok = m.filter(function (r) { return r.tracks === "pass"; }).length;
      return '<button data-st="' + s + '" aria-pressed="' + (f.st === s) + '" title="' + esc(canName(s) + " · " + (node(s) ? node(s).line : "")) + '">' + dot(m.length && ok === m.length ? "pass" : ok ? "watch" : "fail") + esc(canName(s)) + ' <span class="muted">' + ok + "/" + m.length + "</span></button>";
    }).join("");
    var head = RCOLS.map(function (c) { return "<th" + (c[0] === "replay_url" ? ' class="nosort"' : ' data-sort="' + c[0] + '"' + (k === c[0] ? ' aria-sort="' + (d > 0 ? "ascending" : "descending") + '"' : "")) + ">" + esc(c[1]) + "</th>"; }).join("");
    var body = shown.map(function (r) {
      var bad = function (v, g) { return v != null && v > g ? ' class="f"' : ""; };
      var rec = r.replay_url ? '<a class="rr" href="' + esc(r.replay_url) + '" target="_blank" rel="noopener" title="' + esc("Opens " + (r.rrd || "") + " in the native Rerun viewer (the bam-replay-link launcher on 127.0.0.1:8771)" + (r.rrd_via === "identical copy" ? "; the recording of a byte-identical copy of this run" : "")) + '">Open in Rerun ↗</a>'
        : '<span class="muted" title="' + esc(r.rrd ? "recorded, but no replay launcher on this machine: " + r.rrd : "no .rrd was built for this run") + '">' + (r.rrd ? "recorded · no launcher" : "no recording yet") + "</span>";
      return "<tr><td>" + link({ view: "", node: r.station, tab: "" }, esc(canName(r.station))) + "</td><td>" + r.fraction + "</td><td>" + (r.speed_rad_s == null ? "—" : n(r.speed_rad_s, 2) + " rad/s <span class=\"muted\">(" + Math.round(r.speed_rad_s * 180 / Math.PI) + " °/s)</span>") + "</td>" +
        "<td>" + esc(r.kind === "held_out" ? "held-out" : r.kind) + '</td><td class="mono" title="' + esc(r.run) + '">' + esc(r.name) + "</td>" +
        "<td" + bad(r.tracking_rms_deg, t.tracking_rms_deg) + ">" + deg(r.tracking_rms_deg) + "</td><td" + bad(r.tracking_peak_deg, t.tracking_peak_deg) + ">" + deg(r.tracking_peak_deg) + "</td>" +
        "<td>" + dot(r.tracks, r.tracks === "pass" ? "meets RMS ≤ " + t.tracking_rms_deg + "° and peak ≤ " + t.tracking_peak_deg + "°" : r.tracks === "fail" ? "misses the tracking goal" : "not judged") + " " + esc(r.tracks === "pass" ? "yes" : r.tracks === "fail" ? "no" : "—") + "</td>" +
        "<td>" + deg(r.sim_tracking_rms_deg) + "</td><td>" + (r.sim_vs_real_deg == null ? '<span class="muted">—</span>' : deg(r.sim_vs_real_deg, 3)) + "</td><td>" + (r.stops == null ? "—" : r.stops) + "</td><td" + (r.fault ? ' class="f"' : "") + ">" + (r.fault ? "fault" : "—") + "</td><td>" + rec + "</td></tr>";
    }).join("");
    el.innerHTML = '<div class="dw-rtop"><h2>Runs · ' + esc(DATA.deployments.filter(function (x) { return x.id === st.dep; })[0].title) + '</h2><div class="dw-seg" role="group" aria-label="Round">' +
      rounds.map(function (r) { return '<button data-rr="' + r + '" aria-pressed="' + (r === rr) + '" title="' + esc("round " + r + (r === 0 ? " · as found, before any fit" : r === rounds[rounds.length - 1] ? " · now" : "")) + '">Round ' + r + (r === 0 ? " · as found" : r === rounds[rounds.length - 1] ? " · now" : "") + "</button>"; }).join("") + "</div></div>" +
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
      '<input type="search" data-f="q" placeholder="Filter by run name…" value="' + esc(st.q) + '" aria-label="Filter runs by name">' +
      '<span class="muted">' + shown.length + " of " + mine.length + " runs · click a heading to sort</span></div>" +
      '<table class="dw-rt"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";
    el.querySelectorAll("[data-rr]").forEach(function (b) { b.addEventListener("click", function () { go({ rr: b.dataset.rr }, true); }); });
    el.querySelectorAll("[data-st]").forEach(function (b) { b.addEventListener("click", function () { go({ st: b.dataset.st }, true); }); });
    el.querySelectorAll("[data-sort]").forEach(function (th) { th.addEventListener("click", function () { var key = th.dataset.sort; runSort = { key: key, dir: runSort.key === key ? -runSort.dir : 1 }; save("runs.sort", runSort); runs(state()); }); });
    el.querySelectorAll("select[data-f]").forEach(function (s) { s.addEventListener("change", function () { var p = {}; p[s.dataset.f] = s.value; go(p, true); }); });
    var miss = el.querySelector('input[data-f="miss"]'); miss.addEventListener("change", function () { go({ miss: miss.checked ? "1" : "" }, true); });
    var q = el.querySelector('input[data-f="q"]'), timer = null;
    q.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { go({ q: q.value }, true); var again = $("dw-runs").querySelector('input[data-f="q"]'); if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); } }, 200); });
  }

  // ---- the bar, the trail, routing -----------------------------------------------------------------------------------------------------
  function bar(st, view) {
    document.querySelectorAll(".dw-view").forEach(function (a) {
      var v = a.dataset.v;
      a.hidden = v !== "home" && !st.dep;
      if (st.dep && v !== "home") a.setAttribute("href", href({ view: v === "page" ? "" : v }));
      if (v === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    var seg = $("dw-round");
    seg.hidden = view === "home" || view === "runs";
    var opts = view === "table" ? [["r8", "Now · round 8"], ["r0", "As found · round 0"], ["changed", "What changed"]] : [["r0", "As found · round 0"], ["r8", "Now · round 8"]];
    var cur = view === "table" && st.mode === "changed" ? "changed" : st.round;
    seg.innerHTML = opts.map(function (o) { return '<button data-r="' + o[0] + '" aria-pressed="' + (o[0] === cur) + '" title="' + esc(o[0] === "changed" ? "round 0 → round 8, every cell that moved" : o[0] === "r0" ? "the controller as found and the twin unfitted (scored 2026-11-15)" : "round 8, scored 2026-11-17") + '">' + esc(o[1]) + "</button>"; }).join("");
    seg.querySelectorAll("button").forEach(function (b) { b.addEventListener("click", function () { var r = b.dataset.r; go(r === "changed" ? { mode: "changed", round: "" } : { mode: "", round: r }, true); }); });
    // the site's trail: Home › Deployments › the deployment › the node
    var crumbs = document.querySelector(".trail nav.crumbs");
    if (crumbs) {
      var parts = ['<a href="/">Home</a>', '<a href="' + location.pathname + '"' + (view === "home" ? ' aria-current="page"' : "") + ">Deployments</a>"];
      if (st.dep) {
        var dep = DATA.deployments.filter(function (d) { return d.id === st.dep; })[0];
        parts.push('<a href="' + esc(href({ node: "", view: "", tab: "" })) + '">' + esc(dep ? dep.title : st.dep) + "</a>");
        if (view !== "runs" && FX && st.node && st.node !== FX.root && node(st.node)) ancestors(st.node).slice(1).concat([node(st.node)]).forEach(function (a) { parts.push('<a href="' + esc(href({ node: a.id, view: "", tab: "" })) + '">' + esc(a.short) + "</a>"); });
        if (view === "table") parts.push("<span>Table</span>"); else if (view === "runs") parts.push("<span>Runs</span>");
      }
      crumbs.innerHTML = parts.join(" › ");
      crumbs.querySelectorAll("a").forEach(function (a) { if (a.getAttribute("href").indexOf(location.pathname) === 0) a.setAttribute("data-go", ""); });
    }
  }
  function render() {
    var st = state();
    var dep = st.dep && DATA.trees[st.dep] ? st.dep : null;
    FX = dep ? DATA.trees[dep] : null;
    byId = {}; Q = {};
    if (FX) { FX.nodes.forEach(function (x) { byId[x.id] = x; }); FX.questions.forEach(function (q) { Q[q.id] = q; }); }
    if (FX && !node(st.node)) st.node = FX.root;
    var view = !dep ? "home" : st.view === "table" ? "table" : st.view === "runs" ? "runs" : "page";
    $("dw-home").hidden = view !== "home"; $("dw-dep").hidden = view !== "page"; $("dw-table").hidden = view !== "table"; $("dw-runs").hidden = view !== "runs";
    bar(st, view);
    document.title = (FX ? (view === "page" && st.node !== FX.root ? node(st.node).short + " · " : "") + DATA.trees[dep].title + " · " : "") + "Deployments: sim2real";
    if (view === "home") return home();
    if (!treeUI) {
      treeUI = new Tree($("dw-left"), { round: function () { return state().round; }, onSelect: function (id) { go({ node: id, view: "" }); } });
      sash($("dw-sashL"), $("dw-left"), { key: "tree", min: 220, max: 560, dflt: 330 });
      sash($("dw-sashT"), $("dw-insp"), { key: "insp", min: 320, max: 760, dflt: 470, invert: true });
    }
    if (view === "page") { treeUI.select(st.node); return entity(st); }
    if (view === "table") return table(st);
    return runs(st);
  }

  fetch(host.dataset.src).then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); }).then(function (d) {
    DATA = d;
    render();
    host.dataset.ready = "1";
  }).catch(function (e) {
    host.innerHTML = '<p class="lede" style="padding:16px">The Deployments workbench could not load its data (' + esc(e.message) + '). Every deployment is also at <a href="/deployments/all/">/deployments/all/</a>.</p>';
  });
})();
