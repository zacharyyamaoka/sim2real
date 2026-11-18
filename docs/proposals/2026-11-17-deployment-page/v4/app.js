/* V4 Questions: the page is the question matrix. Rows are the typed tree, columns the five questions in their order
   (Floor → Data → Routines → Twin → Job); a cell is that question answered at that level, with the number that decides it.
   A banner names the one thing that stops the goal; a click on any cell opens its evidence (every metric behind it, per
   speed rung on a station, where it is defined); a click on a row name opens the level as a ladder of the five questions,
   the first failing one marked as the cause. Before vs now: Now · As found · What changed (each cell as before → after).
   Backend: sim2real owns the verdict; each type's own metrics are a card (BACKEND.md). */
(function () {
  "use strict";
  var S = window.S2R, FX = S.fx, esc = S.esc;
  var $ = function (id) { return document.getElementById(id); };
  var rack = null, current = null;
  var folded = new Set(S.load("folded", FX.nodes.filter(function (n) { return n.level === "servo"; }).map(function (n) { return n.id; })));
  var CARD = { deployment: "sim2real/verdicts.py (roll-up)", pendulum_arm_1dof: "sim2real/cards/pendulum_arm.py", integrated_servo: "sim2real/cards/servo_gates.py", foc_controller: "sim2real/cards/servo_gates.py",
               bldc_motor: "sim2real/cards/servo_gates.py", gearbox: "sim2real/cards/servo_gates.py", encoder: "sim2real/cards/encoder.py", rigid_link: "—", depth_camera: "sim2real/cards/camera.py" };
  function mode() { var m = S.state().raw.get("mode"); return m === "changed" ? "changed" : S.state().round; }

  function cellHTML(n, q, rid, md) {
    var s = n.questions[rid][q.id];
    if (md === "changed") {
      var a = n.questions.r0[q.id], b = n.questions.r8[q.id], m = b.metric ? S.metric(n, b.metric) : null;
      if (b.status === "none") return { cls: "none", html: "—", moved: false };
      var moved = a.status !== b.status || (m && JSON.stringify(m.values.r0.value) !== JSON.stringify(m.values.r8.value));
      return { cls: b.status, moved: moved, html: '<span class="t">' + S.dot(a.status) + '<span style="color:var(--was)">' + (m ? esc(S.fmtShort(m, m.values.r0)) : "") + '</span><span class="arrow">→</span>' + S.dot(b.status) + (m ? esc(S.fmtShort(m, m.values.r8)) : "") + "</span>" };
    }
    var mm = s.metric ? S.metric(n, s.metric) : null;
    if (s.status === "none") return { cls: "none", html: "—" };
    var text = s.status === "not_observable" ? "not observable" : mm ? S.fmtShort(mm, mm.values[rid]) : "";
    return { cls: s.status, html: '<span class="t">' + S.dot(s.status) + esc(text) + (s.misses ? '<span class="misses" title="counted gates that miss (in the 180, not the goal)">+' + s.misses + "</span>" : "") + "</span>" };
  }

  // ---- home: deployments × questions ------------------------------------------------------------------------------------
  function home() {
    var rows = FX.deployments.map(function (d) {
      if (d.in_fixture) {
        var n = S.node(d.root);
        return '<tr data-href="#/d/' + d.id + '"><td class="nm"><div class="in">' + S.icon("deployment") + "<b>" + esc(d.title) + "</b> " + S.chip("real", "real") + "</div></td>" +
          FX.questions.map(function (q) { var c = cellHTML(n, q, "r8", "r8"); return '<td class="c ' + c.cls + '">' + c.html + "</td>"; }).join("") + '<td class="c vd ' + n.verdict.r8.status + '">' + S.dot(n.verdict.r8.status) + " goal not met</td></tr>";
      }
      return '<tr><td class="nm"><div class="in" style="cursor:default">' + S.icon("deployment") + "<b>" + esc(d.title) + "</b> " + S.chip("sim", "virtual") + "</div></td>" +
        FX.questions.map(function (q) { return q.id === "routines" ? '<td class="c ' + (d.verdict === "pass" ? "pass" : "fail") + '" title="' + esc(d.summary) + '"><span class="t">' + S.dot(d.verdict === "pass" ? "pass" : "fail") + esc(d.summary.replace("sysid oracle: ", "").split(",")[0].replace(" hidden parameters recovered", " recovered")) + "</span></td>" : '<td class="c none" title="sim only: no real floor, twin or job">—</td>'; }).join("") + '<td class="c none">sim only</td></tr>';
    }).join("");
    $("home").innerHTML = "<h1>Deployments</h1><p>Every deployment answers the same five questions, in order. A virtual deployment can only answer Routines (its sysid oracle); a real one answers all five.</p>" +
      '<div style="overflow:auto"><table class="mx"><thead><tr><th>Deployment</th>' + FX.questions.map(function (q) { return "<th>" + q.n + " " + q.name + "<small>" + esc(q.ask) + "</small></th>"; }).join("") + "<th>Verdict</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
    $("home").querySelectorAll("tr[data-href]").forEach(function (tr) { tr.style.cursor = "pointer"; tr.addEventListener("click", function () { location.hash = tr.dataset.href; }); });
  }

  // ---- the banner: the one thing that stops the goal ---------------------------------------------------------------------
  function cause(st) {
    var rid = mode() === "changed" ? "r8" : mode(), root = S.node(FX.root), a = S.answer(root, rid);
    var target = null;
    if (a.culprits && a.culprits.length === 1) target = { node: a.culprits[0], q: root.verdict[rid].first };
    var head = a.status === "pass" ? "The goal is met" : (a.culprits && a.culprits.length === 1 ? "One thing stops the goal: " + S.node(a.culprits[0]).short + " · " + a.q.name : a.head);
    var detail = a.culprits && a.culprits.length === 1 ? (function () { var k = S.node(a.culprits[0]), km = S.metric(k, k.questions[rid][a.q.id].metric), kv = km.values[rid]; return km.name + " " + S.fmt(km, kv) + " · gate " + S.gateText(km) + " · " + kv.detail; })() : a.detail;
    $("cause").className = "cause " + a.status;
    $("cause").innerHTML = S.dot(a.status) + "<span><b>" + esc(head) + '</b><span class="d">' + esc(detail) + (target ? " · click for the evidence" : "") + "</span></span>";
    $("cause").onclick = target ? function () { S.go({ node: target.node, q: target.q }); } : function () { S.go({ node: FX.root, q: "" }); };
  }

  // ---- the matrix ------------------------------------------------------------------------------------------------------
  function matrix(st) {
    var md = mode(), rid = md === "changed" ? "r8" : md, rows = [];
    S.walk(function (n, depth) {
      for (var p = S.parent(n.id); p; p = S.parent(p.id)) if (folded.has(p.id)) return;
      var cells = FX.questions.map(function (q) {
        var c = cellHTML(n, q, rid, md);
        return '<td class="c ' + c.cls + (st.node === n.id && st.q === q.id ? " selc" : "") + '" data-q="' + q.id + '" title="' + esc(q.name + " at " + n.short + ": " + (S.WORD[n.questions[rid][q.id].status] || "")) + '">' + c.html + "</td>";
      });
      var moved = md === "changed" && FX.questions.some(function (q) { return cellHTML(n, q, rid, md).moved; });
      var v = n.verdict[rid].status;
      var vd = md === "changed" ? S.dot(n.verdict.r0.status) + '<span class="arrow">→</span>' + S.dot(n.verdict.r8.status) : S.dot(v === "none" ? "none" : v) + " " + (v === "none" ? "no gates" : { pass: "pass", fail: "fails", watch: "watch" }[v]);
      rows.push('<tr data-id="' + esc(n.id) + '" class="' + (st.node === n.id ? "sel" : "") + (md === "changed" && !moved ? " same" : "") + '"><td class="nm"><div class="in" style="padding-left:' + depth * 16 + 'px"><span class="tw" ' + (n.children.length ? 'data-tw="1"' : 'style="visibility:hidden"') + '><svg viewBox="0 0 12 12" style="transform:rotate(' + (folded.has(n.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' +
        S.icon(n.type.id) + '<b title="' + esc(n.title) + '">' + esc(n.short) + '</b><span class="muted ty" title="' + esc(n.type.name) + '">' + esc(n.type.name) + "</span></div></td>" + cells.join("") + '<td class="c vd ' + (v === "none" ? "none" : v) + '" data-q="">' + vd + "</td></tr>");
    });
    $("matrix").innerHTML = '<table class="mx"><thead><tr><th>Typed component tree</th>' + FX.questions.map(function (q) { return "<th>" + q.n + " " + q.name + "<small>" + esc(q.ask) + "</small></th>"; }).join("") + "<th>Verdict</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }
  $("matrix").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]"); if (!tr) return;
    var id = tr.dataset.id;
    if (ev.target.closest("[data-tw]")) { if (folded.has(id)) folded.delete(id); else folded.add(id); S.save("folded", Array.from(folded)); matrix(S.state()); return; }
    var td = ev.target.closest("td[data-q]");
    S.save("insp.folded", false);
    S.go({ node: id, q: td ? td.dataset.q : "" });
  });

  // ---- the inspector: a cell's evidence, or the level's ladder --------------------------------------------------------------
  function rungTable(n, qid, rid) {
    var cols = { floor: [["floor_deg", "floor °"], ["repeats", "repeats"]], data: [["repeats", "repeats"], ["held_out", "held-out"]],
                 twin: [["floor_deg", "floor °"], ["sim_vs_real_deg", "sim vs real °"], ["twin_ratio", "÷ floor"]],
                 job: [["tracking_rms_deg", "RMS °"], ["tracking_peak_deg", "peak °"], ["stop_tool_mm", "tip mm"]] }[qid];
    if (!cols || !n.rungs) return "";
    var gate = { twin_ratio: FX.thresholds.sim_vs_real_floor_ratio, tracking_rms_deg: FX.thresholds.tracking_rms_deg, tracking_peak_deg: FX.thresholds.tracking_peak_deg, stop_tool_mm: FX.thresholds.stop_tool_mm, repeats: 5, held_out: 2 };
    var o = S.other(rid), key = cols[cols.length - 1][0];
    var body = n.rungs[rid].map(function (r, i) {
      var r0 = n.rungs[o][i];
      return "<tr><td>" + r.fraction + ' <span class="muted">(' + (r.speed_rad_s == null ? "—" : r.speed_rad_s) + " rad/s)</span></td>" + cols.map(function (c) {
        var x = r[c[0]], bad = x != null && gate[c[0]] != null && ((c[0] === "repeats" || c[0] === "held_out") ? x < gate[c[0]] : x > gate[c[0]]);
        return '<td class="' + (bad ? "f" : "") + '">' + (x == null ? "—" : typeof x === "number" ? (Math.abs(x) < 1 && x !== 0 ? x.toFixed(3) : String(Math.round(x * 100) / 100)) : x) + "</td>";
      }).join("") + '<td class="o">' + (r0[key] == null ? "—" : (Math.round(r0[key] * 1000) / 1000)) + "</td></tr>";
    }).join("");
    return "<h3>Per speed rung · " + esc(S.round(rid).label) + '</h3><table class="ev"><thead><tr><th>rung (speed)</th>' + cols.map(function (c) { return "<th>" + esc(c[1]) + "</th>"; }).join("") + "<th>" + esc(S.round(o).label) + "</th></tr></thead><tbody>" + body + "</tbody></table>" +
      (n.caveat ? '<div class="caveat" style="margin-top:8px">' + esc(n.caveat) + "</div>" : "");
  }
  function ladder(n, rid, q) {
    var first = n.verdict[rid].first;
    return '<div class="ladder">' + FX.questions.map(function (qq) {
      var s = n.questions[rid][qq.id], m = s.metric ? S.metric(n, s.metric) : null;
      return '<div class="step ' + s.status + (first === qq.id && n.verdict[rid].status === "fail" ? " first" : "") + '" data-q="' + qq.id + '"><span class="n">' + qq.n + '</span><div class="q"><b>' + qq.name + "</b>" + (first === qq.id && n.verdict[rid].status === "fail" ? '<span class="cause-tag">the cause</span>' : "") +
        '<div class="d">' + (m ? esc(m.name) + " <b>" + esc(S.fmt(m, m.values[rid])) + "</b> · gate " + esc(S.gateText(m)) + " " + S.was(m, rid) : esc(s.status === "none" ? "asked at another level" : S.WORD[s.status])) + "</div></div></div>";
    }).join("") + "</div>";
  }
  function inspector(st) {
    if (S.load("insp.folded", false)) { $("insp").hidden = true; $("sashR").hidden = true; return; }
    $("insp").hidden = false; $("sashR").hidden = false;
    var md = mode(), rid = md === "changed" ? "r8" : md, n = S.node(st.node), q = st.q ? S.Q[st.q] : null;
    var h = '<div class="top"><span class="k">' + (q ? "Question " + q.n + " at a level" : "A level, question by question") + '</span><button class="iconbtn" id="foldI" title="Fold (Esc)">' + S.svg.close + "</button></div>";
    if (q) {
      var s = n.questions[rid][q.id], ms = n.metrics.filter(function (m) { return m.question === q.id; });
      h += "<h2>" + q.n + " · " + q.name + " at " + esc(n.short) + '</h2><div class="sub">' + esc(q.ask) + "</div>" + S.chip(s.status === "none" ? "none" : s.status, s.status === "none" ? "asked at another level" : S.WORD[s.status]) +
        (ms.length ? '<h3>The metrics behind it</h3><table class="mt"><thead><tr><th>Metric</th><th>' + esc(S.round(rid).label) + "</th><th>" + esc(S.round(S.other(rid)).label) + "</th><th>Gate</th></tr></thead><tbody>" + ms.map(function (m) {
          return "<tr><td>" + S.code(m) + esc(m.name) + '<div class="muted" style="font-size:11.5px">' + esc(S.KIND[m.kind]) + (m.values[rid].detail ? " · " + esc(m.values[rid].detail) : "") + '</div></td><td class="v">' + S.dot(m.values[rid].status) + " " + esc(S.fmt(m, m.values[rid])) + '</td><td class="v" style="color:var(--was)">' + esc(S.fmt(m, m.values[S.other(rid)])) + "</td><td>" + esc(S.gateText(m)) + "</td></tr>";
        }).join("") + "</tbody></table>" : '<p class="muted">No metric at this level answers it; ' + (q.id === "data" || q.id === "routines" ? "the station asks it for its whole joint." : "it is asked above or below.") + "</p>") +
        rungTable(n, q.id, rid) +
        "<h3>Defined in</h3><p class=\"muted mono\" style=\"font-size:12px;margin:0\">" + esc(CARD[n.type.id]) + " · the five questions themselves: sim2real/verdicts.py</p>" +
        '<h3>This level, all five</h3>' + ladder(n, rid, q.id);
    } else {
      h += "<h2>" + esc(n.title) + '</h2><div class="sub">' + esc(n.type.name) + " · judged at " + esc(n.judged_at) + (n.gating ? "" : " · shown, not gating") + "</div>" + S.answerHTML(n, rid) +
        (n.metrics.length ? "<h3>Five questions, in order: the first that fails names the cause</h3>" + ladder(n, rid) : '<h3>Facts</h3><p class="muted">' + (n.facts || []).map(function (f) { return esc(f[0]) + ": " + esc(f[1]); }).join(" · ") + "</p>") +
        (n.children.length ? "<h3>Its children " + (n.level === "station" ? "(shown, not gating)" : "") + "</h3>" + S.kids(n.id).map(function (k) { var a = S.answer(k, rid); return '<div class="step ' + a.status + '" data-go="' + esc(k.id) + '" style="grid-template-columns:16px 1fr"><span>' + S.dot(a.status === "none" ? "none" : a.status) + '</span><div class="q"><b>' + esc(k.short) + '</b><div class="d">' + esc(a.head) + "</div></div></div>"; }).join("") : "");
    }
    $("insp").innerHTML = h;
    $("foldI").addEventListener("click", function () { S.save("insp.folded", true); inspector(S.state()); });
    $("insp").querySelectorAll(".step[data-q]").forEach(function (el) { el.addEventListener("click", function () { S.go({ q: el.dataset.q }, true); }); });
    $("insp").querySelectorAll("[data-go]").forEach(function (el) { el.addEventListener("click", function () { S.go({ node: el.dataset.go, q: "" }); }); });
  }

  function rule() {
    $("rule").innerHTML = "<h3>How a level passes</h3><ol><li>Each level answers the same five questions, in this order.</li><li>A parent passes at its <b>own output</b> and only with its children; on this rack the servo's rows are shown, not gating (MOC decision 1).</li><li>The first question that fails names the cause.</li></ol>" +
      '<div class="key">' + S.dot("pass") + "<span>passes its gate</span>" + S.dot("fail") + "<span>a goal gate fails</span>" + S.dot("watch") + "<span>outside a target that does not gate</span>" + S.dot("not_observable") + "<span>not observable on this rack, or not run</span>" + S.dot("none") + "<span>asked at another level</span></div>";
  }

  S.sash($("sashL"), $("side"), { key: "side", min: 220, max: 620, dflt: 260, onResize: function () { if (rack) rack.resize(); } });
  S.sash($("sashS"), $("scene"), { key: "scene", horizontal: true, min: 160, max: 640, dflt: 300, onResize: function () { if (rack) rack.resize(); } });
  S.sash($("sashR"), $("insp"), { key: "insp", min: 300, max: 720, dflt: 340, invert: true });
  document.querySelectorAll("#mode button").forEach(function (b) {
    b.addEventListener("click", function () { var m = b.dataset.m; S.go(m === "changed" ? { mode: "changed", round: "r8" } : { mode: null, round: m }, true); });
  });
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && ev.target.tagName !== "INPUT" && !S.load("insp.folded", false)) { S.save("insp.folded", true); inspector(S.state()); } });
  S.on(function (st) {
    var home_ = st.page === "home";
    $("home").hidden = !home_; $("dep").hidden = home_; $("mode").hidden = home_;
    var md = mode();
    document.querySelectorAll("#mode button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.m === md)); });
    $("crumbs").innerHTML = home_ ? "<b>Deployments</b>" : '<a href="#/">Deployments</a><span class="sep">/</span><a href="' + S.href({ node: FX.root, q: "" }) + '">' + esc(FX.deployments[0].title) + "</a>" + (st.node !== FX.root ? '<span class="sep">/</span><b>' + esc(S.node(st.node).short) + "</b>" : "") + (st.q ? '<span class="sep">·</span><b>' + esc(S.Q[st.q].name) + "</b>" : "");
    if (home_) return home();
    if (!rack) { rack = new S.Rack3D($("scene"), { labels: "selected", onPick: function (id) { S.save("insp.folded", false); S.go({ node: id, q: "" }); }, label: function (sid, r) { var n = S.node(sid); return S.dot(n.verdict[r].status) + esc(n.short); } }); rule(); }
    var rid = md === "changed" ? "r8" : md;
    rack.setRound(rid);
    var changed = current !== st.node;
    rack.select(st.node === FX.root ? null : st.node, changed);
    current = st.node;
    cause(st); matrix(st); inspector(st);
    if (changed) $("insp").scrollTop = 0;
  });
  S.start();
})();
