/* V5 Ladder: measurement first. Every level opens on its numbers: big KPIs with the round-0 value beside each, then the
   evidence drawn: on the deployment a ladder grid (the nested table, stations × speed rungs, each cell the rung's five gates
   in Zach's order, round 0's under them); on a station its speed-ladder plots with the gate as a band and round 0 dashed;
   on a servo or a part, bullet charts (value against gate, round 0 as a hollow mark). Backend: model-free metric functions
   in a small robot_metrics package over robot_msgs; each type names the ones it is judged by (BACKEND.md). */
(function () {
  "use strict";
  var S = window.S2R, FX = S.fx, esc = S.esc;
  var $ = function (id) { return document.getElementById(id); };
  var rack = null, tree = null, current = null;
  var ORDER = [["target_vs_sim_stop", "sim's tip stop"], ["sim_vs_real", "twin ÷ floor"], ["sim_predicts_tracking", "sim predicts"], ["target_vs_real_tracking", "tracking"], ["target_vs_real_stop", "tip stop"]];
  var gfold = new Set(S.load("grid.folded", FX.nodes.filter(function (n) { return n.level === "station"; }).map(function (n) { return n.id; })));
  function overlay() { return S.load("overlay", true); }
  var FN = { repeat_floor: "floor", rungs_measured: "repeats", oracle_recovery: "oracle_recovery", twin_over_floor: "twin_over_floor", passes_up_to: "speed_ladder", tracking_rms_09: "tracking_rms",
             tracking_peak_09: "tracking_peak", tip_stop_09: "stop_error_at_tool", sim_predicts: "sim_predicts_tracking", sim_stop: "stop_error_at_tool(sim)", tip_tracking_09: "tracking_rms_at_tool", T1: "floor", T2: "twin_over_floor",
             T3: "current_over_scatter", T7: "top_speed_error", T6: "kt_error", T8: "winding_temp_error", T5: "lost_motion", T4: "stop_error_at_output", limiter_share: "limiter_share", homing_repeat: "homing_repeat" };
  function definedIn(m) { return "robot_metrics." + (FN[m.id] || m.id); }

  function home() {
    $("home").innerHTML = "<h1>Deployments</h1><p>How far each deployment is from its gates, round 0 (as found) under now.</p><div class=\"drows\">" + FX.deployments.map(function (d) {
      var right;
      if (d.in_fixture) {
        var h0 = d.headline.r0, h8 = d.headline.r8;
        right = '<div><div class="bar2"><span class="b0" style="width:' + (100 * h0.gates_passed / h0.gates_total) + '%"></span><span class="b8" style="width:' + (100 * h8.gates_passed / h8.gates_total) + '%"></span></div><div class="barlab"><span>round 0: ' + h0.gates_passed + "</span><span><b style=\"color:var(--ink)\">now: " + h8.gates_passed + " of " + h8.gates_total + " gates</b></span></div></div>";
      } else right = '<div class="muted" style="font-size:12.5px">' + S.chip(d.verdict === "pass" ? "pass" : "fail", "oracle " + d.verdict) + " sim only · not in this fixture</div>";
      var inner = '<img src="' + S.media(d.render) + '" alt=""><div><div class="t">' + esc(d.title) + " " + S.chip(d.kind === "physical" ? "real" : "sim", d.kind === "physical" ? "real hardware" : "virtual") + '</div><div class="l">' + esc(d.summary) + "</div></div>" + right;
      return d.in_fixture ? '<a class="drow" href="#/d/' + d.id + '">' + inner + "</a>" : '<div class="drow off">' + inner + "</div>";
    }).join("") + "</div>";
  }

  // ---- the hero: the level's KPIs ----------------------------------------------------------------------------------------
  var KPIS = { deployment: ["gates_passed", "stations_tracking", "stations_twinned", "goal_met"], station: ["passes_up_to", "twin_over_floor", "tip_stop_09", "tracking_rms_09", "gates_passed"] };
  function kpis(n) {
    var ids = KPIS[n.level] || n.metrics.map(function (m) { return m.id; });
    var cards = ids.map(function (id) { return S.metric(n, id); }).filter(Boolean).map(function (m) {
      var v = m.values.r8, st = v.status;
      return '<div class="kpi ' + st + '"><div class="k">' + S.code(m) + esc(m.name) + (m.unit === "of top speed" ? " (of top speed)" : "") + '</div><div class="v">' + S.dot(st) + esc(S.fmtShort(m, v)) + "</div>" + (overlay() ? S.was(m, "r8") : "") + '<div class="g">' + esc(m.gate ? "gate " + m.gate.text : S.KIND[m.kind]) + "</div></div>";
    }).join("");
    $("kpis").innerHTML = "<h1>" + S.icon(n.type.id) + esc(n.title) + '</h1><div class="sub">' + esc(n.type.name) + " · judged at " + esc(n.judged_at) + (n.unit ? " · " + esc(n.unit) : "") + "</div>" +
      S.answerHTML(n, "r8", { misses: n.level !== "deployment" }) + (cards ? '<div class="kgrid">' + cards + "</div>" : "");
  }

  // ---- the ladder grid (deployment) ------------------------------------------------------------------------------------------
  function bars(r) { return ORDER.map(function (g) { return '<i class="' + (r.gates[g[0]] === "not_run" ? "" : r.gates[g[0]]) + '" title="' + esc(g[1] + ": " + (S.WORD[r.gates[g[0]]] || r.gates[g[0]])) + '"></i>'; }).join(""); }
  function grid(sel) {
    var rows = [], rungs = [0.2, 0.4, 0.6, 0.8, 0.9, 1.0];
    S.walk(function (n, depth) {
      if (n.level === "deployment") return;
      for (var p = S.parent(n.id); p; p = S.parent(p.id)) if (gfold.has(p.id)) return;
      var tw = n.children.length ? '<span class="tw" data-tw="1"><svg viewBox="0 0 12 12" style="transform:rotate(' + (gfold.has(n.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' : '<span class="tw" style="visibility:hidden"></span>';
      var name = '<td class="nm" data-id="' + esc(n.id) + '"><div class="in" style="padding-left:' + (depth - 1) * 16 + 'px">' + tw + S.icon(n.type.id) + "<b>" + esc(n.short) + "</b> " + S.dot(n.verdict.r8.status === "none" ? (n.metrics.length ? "not_observable" : "none") : n.verdict.r8.status) + "</div></td>";
      if (n.level === "station") {
        var up = S.metric(n, "passes_up_to"), tw2 = S.metric(n, "twin_over_floor");
        rows.push('<tr class="' + (sel === n.id ? "sel" : "") + '">' + name + rungs.map(function (f, i) {
          return '<td class="cell" data-id="' + esc(n.id) + '" data-rung="' + f + '"><div class="gb">' + bars(n.rungs.r8[i]) + "</div>" + (overlay() ? '<div class="gb r0">' + bars(n.rungs.r0[i]) + "</div>" : "") + "</td>";
        }).join("") + '<td class="v">' + (overlay() ? '<span class="was">' + esc(S.fmtShort(up, up.values.r0)) + " →</span> " : "") + "<b>" + esc(S.fmtShort(up, up.values.r8)) + '</b></td><td class="v">' + (overlay() ? '<span class="was">' + esc(S.fmtShort(tw2, tw2.values.r0)) + " →</span> " : "") + '<b style="color:' + (tw2.values.r8.status === "fail" ? "var(--fail)" : "inherit") + '">' + esc(S.fmtShort(tw2, tw2.values.r8)) + "</b></td></tr>");
      } else {
        var txt = n.metrics.length ? n.metrics.map(function (m) { var v = m.values.r8; return S.dot(v.status) + " " + (m.code ? m.code + " " : "") + esc(m.name.toLowerCase()) + " " + esc(S.fmt(m, v)); }).join(" &nbsp;·&nbsp; ") : '<span class="muted">' + esc((n.facts || []).map(function (f) { return f[0] + " " + f[1]; }).join(" · ")) + "</span>";
        rows.push('<tr class="' + (sel === n.id ? "sel" : "") + '">' + name + '<td class="span" colspan="8">' + txt + "</td></tr>");
      }
    });
    return '<h3>The speed ladder, every station <span class="gkey">each rung: <span class="gb"><i class="pass"></i><i class="pass"></i><i class="pass"></i><i class="pass"></i><i class="pass"></i></span> = ' + ORDER.map(function (g) { return g[1]; }).join(" · ") + (overlay() ? " · the thin row under it is round 0" : "") + "</span></h3>" +
      '<div style="overflow:auto"><table class="lg5"><thead><tr><th class="l">Station · part</th>' + rungs.map(function (f) { return "<th>" + f + "</th>"; }).join("") + "<th>Passes up to</th><th>Twin worst</th></tr><tr><th></th><th colspan=\"6\" style=\"font-weight:400;text-transform:none\">fraction of each station's top speed</th><th></th><th></th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
  }

  // ---- bullet charts (servo, parts) -----------------------------------------------------------------------------------------
  function bullet(m) {
    var v = m.values.r8, o = m.values.r0, g = m.gate;
    if (v.status === "not_observable" || v.status === "not_run") return '<div class="bl no"><div class="n">' + S.code(m) + esc(m.name) + "<small>" + esc(v.detail || S.WORD[v.status]) + '</small></div><div class="track"></div><div class="r muted">' + esc(S.WORD[v.status]) + "</div></div>";
    var x = v.value, x0 = o ? o.value : null, lim = g && typeof g.limit === "number" ? g.limit : null;
    if (m.unit === "%") { x = Math.abs(x); x0 = x0 == null ? null : Math.abs(x0); }
    if (m.unit === "of rows") { x *= 100; x0 = x0 == null ? null : x0 * 100; lim = lim == null ? null : lim * 100; }
    if (g && g.op === "repeats") lim = null;
    var top = Math.max(lim ? lim * 2 : 0, x * 1.15, x0 ? x0 * 1.15 : 0) || 1;
    var pct = function (a) { return Math.min(100, 100 * a / top) + "%"; };
    return '<div class="bl"><div class="n">' + S.code(m) + esc(m.name) + "<small>" + esc(g ? "gate " + g.text : S.KIND[m.kind]) + " · " + esc(definedIn(m)) + '</small></div><div class="track">' + (lim ? '<span class="ok" style="width:' + pct(lim) + '"></span><span class="gate" style="left:' + pct(lim) + '"></span>' : "") +
      '<span class="val ' + v.status + '" style="width:' + pct(x) + '"></span>' + (overlay() && x0 != null ? '<span class="w0" style="left:' + pct(x0) + '" title="round 0: ' + esc(S.fmt(m, o)) + '"></span>' : "") + '</div><div class="r">' + esc(S.fmt(m, v)) + (overlay() ? "<small>" + S.was(m, "r8") + "</small>" : "") + "</div></div>";
  }

  function body(st) {
    var n = S.node(st.node), out = "";
    if (n.level === "deployment") out = grid(st.node);
    else if (n.level === "station") {
      var hl = st.raw.get("rung");
      out = '<h3>Up the speed ladder <span class="gkey">' + (overlay() ? S.legend() : "") + " · the shaded band passes the gate</span></h3>" + (n.caveat ? '<div class="caveat" style="margin-bottom:10px">' + esc(n.caveat) + "</div>" : "") +
        '<div class="plots">' + Object.keys(S.RUNG_KEYS).map(function (k) { return '<div class="pc">' + S.rungPlot(n, k, { w: 340, h: 170, rounds: overlay() ? ["r0", "r8"] : ["r8"], highlight: hl }) + "</div>"; }).join("") + "</div>" +
        "<h3>Its other gates</h3><div class=\"bullets\">" + n.metrics.filter(function (m) { return ["repeat_floor", "rungs_measured", "sim_predicts", "sim_stop", "tip_tracking_09"].indexOf(m.id) >= 0; }).map(bullet).join("") + "</div>" +
        "<h3>Its servo and parts</h3><div class=\"bullets\">" + FX.nodes.filter(function (k) { return k.id.indexOf(n.id + "/") === 0; }).map(function (k) { return k.metrics.map(function (m) { return bullet(Object.assign({}, m, { name: k.short + " · " + m.name })); }).join(""); }).join("") + "</div>";
    } else if (n.metrics.length) out = '<h3>Each metric against its gate <span class="gkey">' + (overlay() ? "hollow mark = round 0" : "") + "</span></h3><div class=\"bullets\">" + n.metrics.map(bullet).join("") + "</div>";
    else out = '<h3>Facts</h3><p class="muted">' + (n.facts || []).map(function (f) { return esc(f[0]) + ": " + esc(f[1]); }).join(" · ") + "</p>";
    $("body").innerHTML = out;
  }
  $("body").addEventListener("click", function (ev) {
    var tw = ev.target.closest("[data-tw]");
    if (tw) { var id = tw.closest("[data-id]").dataset.id; if (gfold.has(id)) gfold.delete(id); else gfold.add(id); S.save("grid.folded", Array.from(gfold)); body(S.state()); return; }
    var c = ev.target.closest("[data-id]"); if (c) S.go({ node: c.dataset.id, rung: c.dataset.rung || null });
  });
  $("overlay").addEventListener("click", function () { S.save("overlay", !overlay()); render(S.state()); });

  function render(st) {
    $("overlay").setAttribute("aria-pressed", String(overlay()));
    var n = S.node(st.node);
    kpis(n); body(st);
    rack.setRound("r8");
    var changed = current !== st.node;
    rack.select(st.node === FX.root ? null : st.node, changed);
    if (changed) $("page").scrollTop = 0;
    current = st.node;
  }
  S.sash($("sashL"), $("left"), { key: "tree", min: 220, max: 520, dflt: 290 });
  S.sash($("sashS"), $("scene"), { key: "scene", min: 240, max: 900, dflt: 420, onResize: function () { if (rack) rack.resize(); } });
  tree = new S.Tree($("left"), { key: "v5", round: function () { return "r8"; }, onSelect: function (id) { S.go({ node: id, rung: null }); }, line: function (n) { return n.type.name; } });
  S.on(function (st) {
    var home_ = st.page === "home";
    $("home").hidden = !home_; $("dep").hidden = home_; $("overlay").hidden = home_;
    $("crumbs").innerHTML = home_ ? "<b>Deployments</b>" : '<a href="#/">Deployments</a><span class="sep">/</span><a href="' + S.href({ node: FX.root, rung: null }) + '">' + esc(FX.deployments[0].title) + "</a>" + (st.node !== FX.root ? '<span class="sep">/</span><b>' + esc(S.node(st.node).short) + "</b>" : "");
    if (home_) return home();
    if (!rack) rack = new S.Rack3D($("scene"), { labels: "selected", onPick: function (id) { S.go({ node: id, rung: null }); }, label: function (sid) { var n = S.node(sid); return S.dot(n.verdict.r8.status) + esc(n.short); } });
    tree.select(st.node);
    render(st);
  });
  S.start();
})();
