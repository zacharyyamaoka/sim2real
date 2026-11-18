/* V2 Sheet: the deployment page IS the nested typed table (RobotDx's Table, sim2real's Typed tree), every row a node, the
   five questions as columns, round 0 and now side by side as columns (no switch to flip). A dock on the right holds the 3D
   (top) and the picked row's inspector (below); both fold. Backend: a flat robot_models/metrics/ folder and a values
   ledger, one row per node x metric x round, which this table reads as it is (BACKEND.md). */
(function () {
  "use strict";
  var S = window.S2R, FX = S.fx, esc = S.esc;
  var $ = function (id) { return document.getElementById(id); };
  var rack = null, filter = "", current = null;
  var folded = new Set(S.load("folded", FX.nodes.filter(function (n) { return n.level === "servo"; }).map(function (n) { return n.id; })));

  function definedIn(m, node) { return "robot_models/metrics/" + node.type.id + ".py · " + (m.code || m.id); }
  function ledger(node) {
    var rows = [];
    FX.rounds.forEach(function (r) {
      node.metrics.forEach(function (m) {
        var v = m.values[r.id];
        rows.push(JSON.stringify({ round: r.round, node: node.id, type: node.type.id, metric: m.code || m.id, value: v.value, unit: m.unit, status: v.status }));
      });
    });
    return rows.join("\n");
  }
  function keyMetric(node, rid) {
    var a = S.answer(node, rid); if (a.metric) return a.metric;
    var pref = { deployment: "gates_passed", station: "passes_up_to", servo: "T2" }[node.level];
    return (pref && S.metric(node, pref)) || node.metrics[0] || null;
  }

  // ---- home: the deployments, as a table too ----------------------------------------------------------------------------
  function home() {
    var rows = FX.deployments.map(function (d) {
      var r0 = d.headline ? d.headline.r0 : null, r8 = d.headline ? d.headline.r8 : null;
      return "<tr" + (d.in_fixture ? ' data-href="#/d/' + d.id + '"' : ' class="off"') + '><td class="c-comp"><span class="nm">' + S.icon("deployment") + "<b>" + esc(d.title) + "</b></span></td><td>" + S.chip(d.kind === "physical" ? "real" : "sim", d.kind) + '</td><td class="muted">' + esc(d.where) + "</td>" +
        (d.in_fixture ? '<td class="bl">' + S.chip(r0.goal_met ? "pass" : "fail", r0.goal_met ? "met" : "not met") + '</td><td class="v was">' + r0.gates_passed + " of " + r0.gates_total + '</td><td class="bl">' + S.chip(r8.goal_met ? "pass" : "fail", r8.goal_met ? "met" : "not met") + '</td><td class="v vd">' + r8.gates_passed + " of " + r8.gates_total + '</td><td class="v"><span class="delta-up">▲ ' + (r8.gates_passed - r0.gates_passed) + "</span></td>"
          : '<td class="bl" colspan="4" class="muted">sysid oracle: ' + esc(d.summary.replace("sysid oracle: ", "")) + ' · <span class="muted">not in this fixture</span></td><td></td>') + "</tr>";
    }).join("");
    $("home").innerHTML = "<h1>Deployments</h1><p>Every deployment as a row; open one for its typed component tree as a table, the 3D beside it.</p>" +
      '<div style="overflow:auto"><table class="sh"><thead><tr><th></th><th></th><th></th><th class="grp" colspan="2"><span>' + esc(S.roundLabel("r0")) + '</span></th><th class="grp" colspan="2"><span>' + esc(S.roundLabel("r8")) + '</span></th><th></th></tr>' +
      "<tr><th>Deployment</th><th>Kind</th><th>Where</th><th>Goal</th><th>Gates</th><th>Goal</th><th>Gates</th><th>Δ</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
    $("home").querySelectorAll("tr[data-href]").forEach(function (tr) { tr.addEventListener("click", function () { location.hash = tr.dataset.href; }); });
  }

  // ---- the sheet -----------------------------------------------------------------------------------------------------------
  function visible(n) {
    if (!filter) return true;
    var hay = (n.short + " " + n.title + " " + n.type.name + " " + (n.unit || "")).toLowerCase();
    if (hay.indexOf(filter) >= 0) return true;
    return n.children.some(function (c) { return visible(S.node(c)); });
  }
  function qcell(n, q, rid) {
    var s = n.questions[rid][q.id], m = s.metric ? S.metric(n, s.metric) : null;
    var st = s.status, text = m ? S.fmtShort(m, m.values[rid]) : "—";
    if (st === "not_observable") text = "not seen";
    if (st === "none") text = "—";
    var title = q.name + " · " + (S.WORD[st] || "") + (m ? " · " + m.name + " " + S.fmt(m, m.values[rid]) + " · gate " + S.gateText(m) : "");
    return '<td class="q ' + st + '" data-q="' + q.id + '" title="' + esc(title) + '"><span class="cell">' + (st === "none" ? "" : S.dot(st)) + esc(text) + (s.misses ? ' <span style="color:var(--warn)" title="counted gates missed">+' + s.misses + "</span>" : "") + "</span></td>";
  }
  function verdictCell(n, rid) {
    var v = n.verdict[rid].status;
    if (v === "none") return '<td class="muted">—</td>';
    return "<td>" + S.chip(v, { pass: "pass", fail: "fail", watch: "watch" }[v]) + "</td>";
  }
  function sheet(st) {
    var rid = "r8", sel = st.node, rows = [];
    S.walk(function (n, depth) {
      for (var p = S.parent(n.id); p; p = S.parent(p.id)) if (folded.has(p.id) && !filter) return;
      if (!visible(n)) return;
      var km = keyMetric(n, rid), c = km ? S.change(km, rid) : { dir: "na" };
      var gp = S.metric(n, "gates_passed");
      rows.push('<tr data-id="' + esc(n.id) + '" class="' + (n.id === sel ? "sel" : "") + '"><td class="c-comp"><span class="nm" style="padding-left:' + depth * 16 + 'px">' +
        '<span class="tw" ' + (n.children.length ? 'data-tw="1"' : 'style="visibility:hidden"') + '><svg viewBox="0 0 12 12" style="transform:rotate(' + (folded.has(n.id) && !filter ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' +
        S.icon(n.type.id) + '<b title="' + esc(n.title) + '">' + esc(n.short) + "</b></span></td>" +
        "<td>" + esc(n.type.name) + "</td>" + verdictCell(n, "r0").replace("<td", '<td class="bl"') + verdictCell(n, "r8") +
        FX.questions.map(function (q, i) { return qcell(n, q, rid).replace('class="q', 'class="q' + (i === 0 ? " bl" : "")); }).join("") +
        '<td class="bl dl">' + (km ? (km.code ? '<span class="code">' + esc(km.code) + "</span>" : "") + esc(km.name) : "") + '</td><td class="v was">' + (km ? esc(S.fmtShort(km, km.values.r0)) : "") + '</td><td class="v vd">' + (km ? esc(S.fmtShort(km, km.values.r8)) : "") + "</td>" +
        '<td class="v">' + (c.dir === "up" ? '<span class="delta-up">▲ better</span>' : c.dir === "down" ? '<span class="delta-down">▼ worse</span>' : c.dir === "flat" ? '<span class="delta-flat">= same</span>' : "") + "</td>" +
        '<td class="v bl">' + (gp ? '<span class="was">' + gp.values.r0.value + "</span> → <b>" + gp.values.r8.value + "</b> of " + gp.values.r8.of : "") + "</td></tr>");
    });
    $("sheet").innerHTML = '<table class="sh"><thead><tr><th></th><th></th><th class="grp" colspan="2"><span>Verdict</span></th><th class="grp" colspan="5"><span>The five questions · ' + esc(S.roundLabel("r8")) + '</span></th><th class="grp" colspan="4"><span>Key metric · round 0 → now</span></th><th></th></tr>' +
      '<tr><th>Component</th><th>Type</th><th class="bl" title="' + esc(S.roundLabel("r0")) + '">Round 0</th><th>Now</th>' + FX.questions.map(function (q, i) { return '<th class="' + (i === 0 ? "bl" : "") + '" title="' + esc(q.ask) + '">' + q.n + " " + q.name + "</th>"; }).join("") +
      '<th class="bl">Metric</th><th style="text-align:right">Round 0</th><th style="text-align:right">Now</th><th style="text-align:right">Δ</th><th class="bl" style="text-align:right">Gates passed</th></tr></thead><tbody>' + rows.join("") + "</tbody></table>" +
      (rows.length ? "" : '<p class="empty">No row matches “' + esc(filter) + "”.</p>");
  }
  $("sheet").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]");
    if (!tr) { if (!S.load("dock.folded", false)) { S.save("dock.folded", true); layout(S.state()); } return; }
    var id = tr.dataset.id;
    if (ev.target.closest("[data-tw]")) { if (folded.has(id)) folded.delete(id); else folded.add(id); S.save("folded", Array.from(folded)); sheet(S.state()); return; }
    var q = ev.target.closest("td[data-q]");
    if (S.load("dock.folded", false)) S.save("dock.folded", false);
    S.go({ node: id, q: q ? q.dataset.q : "" }, true);
  });
  $("find").addEventListener("input", function () { filter = $("find").value.trim().toLowerCase(); sheet(S.state()); });

  // ---- the dock: 3D on top, the picked row below ----------------------------------------------------------------------------
  function inspector(st) {
    var n = S.node(st.node), hq = st.q;
    var rowsHtml = "";
    FX.questions.concat([{ id: "verdict", name: "Verdict" }]).forEach(function (q) {
      var ms = n.metrics.filter(function (m) { return m.question === q.id; });
      if (!ms.length) return;
      rowsHtml += '<tr class="qh"><td colspan="5">' + (q.n ? q.n + " · " : "") + esc(q.name) + "</td></tr>";
      ms.forEach(function (m) {
        var c = S.change(m, "r8");
        rowsHtml += '<tr class="' + (hq === q.id ? "hl" : "") + '"><td>' + S.code(m) + esc(m.name) + '<div class="muted" style="font-size:11.5px">gate ' + esc(S.gateText(m)) + " · " + esc(S.KIND[m.kind]) + '</div></td><td style="color:var(--was)">' + S.dot(m.values.r0.status) + " " + esc(S.fmt(m, m.values.r0)) +
          "</td><td><b>" + S.dot(m.values.r8.status) + " " + esc(S.fmt(m, m.values.r8)) + "</b></td><td>" + (c.dir === "up" ? '<span class="delta-up">▲</span>' : c.dir === "down" ? '<span class="delta-down">▼</span>' : c.dir === "flat" ? "=" : "") + "</td></tr>";
      });
    });
    $("insp").innerHTML = '<div class="head"><div class="grow"><h2>' + S.icon(n.type.id) + esc(n.title) + '</h2><div class="sub">' + esc(n.type.name) + " · judged at " + esc(n.judged_at) + (n.unit ? " · " + esc(n.unit) : "") + '</div></div><button class="iconbtn" id="fold" title="Fold the dock (Esc)">' + S.svg.close + "</button></div>" +
      S.answerHTML(n, "r8") + (n.caveat ? '<div class="caveat" style="margin-top:8px">' + esc(n.caveat) + "</div>" : "") +
      (n.metrics.length ? '<h3>Round 0 → now, every metric</h3><table class="bt"><thead><tr><th>Metric</th><th>Round 0</th><th>Now</th><th>Δ</th></tr></thead><tbody>' + rowsHtml + "</tbody></table>" +
        '<details class="rows"><summary>The ledger rows this page reads (' + n.metrics.length * 2 + ")</summary><pre>" + esc(ledger(n)) + "</pre></details>" +
        '<h3>Defined in</h3><p class="muted mono" style="font-size:12px;margin:0">robot_models/metrics/' + esc(n.type.id) + ".py</p>"
        : '<h3>Facts</h3><p class="muted">' + (n.facts || []).map(function (f) { return esc(f[0]) + ": " + esc(f[1]); }).join(" · ") + "</p>");
    $("fold").addEventListener("click", function () { S.save("dock.folded", true); layout(S.state()); });
  }
  function layout(st) {
    var foldedDock = S.load("dock.folded", false);
    $("dock").hidden = foldedDock; $("sashD").hidden = foldedDock;
    $("dockbtn").setAttribute("aria-pressed", String(!foldedDock));
    if (!foldedDock) {
      if (!rack) rack = new S.Rack3D($("scene"), { labels: "selected", onPick: function (id) { S.go({ node: id, q: "" }, true); }, label: function (sid, r) { var n = S.node(sid); return S.dot(n.verdict[r].status) + esc(n.short); } });
      rack.setRound("r8");
      var changed = current !== st.node;
      rack.select(st.node === FX.root ? null : st.node, changed);
      current = st.node;
      inspector(st);
      if (changed) $("insp").scrollTop = 0;
      rack.resize();
    }
  }
  $("dockbtn").addEventListener("click", function () { S.save("dock.folded", !S.load("dock.folded", false)); layout(S.state()); });
  addEventListener("keydown", function (ev) {
    if (ev.target.tagName === "INPUT") return;
    if (ev.key === "Escape" && !S.load("dock.folded", false)) { S.save("dock.folded", true); layout(S.state()); }
    if (ev.key === "d" || ev.key === "D") { S.save("dock.folded", !S.load("dock.folded", false)); layout(S.state()); }
  });

  S.sash($("sashD"), $("dock"), { key: "dock", min: 320, max: 820, dflt: 440, invert: true, onResize: function () { if (rack) rack.resize(); } });
  S.sash($("sashS"), $("scene"), { key: "scene", horizontal: true, min: 140, max: 600, dflt: 270, onResize: function () { if (rack) rack.resize(); } });
  S.on(function (st) {
    var home_ = st.page === "home";
    $("home").hidden = !home_; $("dep").hidden = home_; $("findbox").hidden = home_; $("dockbtn").hidden = home_;
    $("crumbs").innerHTML = home_ ? "<b>Deployments</b>" : '<a href="#/">Deployments</a><span class="sep">/</span><a href="' + S.href({ node: FX.root, q: "" }) + '">' + esc(FX.deployments[0].title) + "</a>" + (st.node !== FX.root ? '<span class="sep">/</span><b>' + esc(S.node(st.node).short) + "</b>" : "");
    if (home_) return home();
    sheet(st);
    layout(st);
    var tr = $("sheet").querySelector("tr.sel"); if (tr) tr.scrollIntoView({ block: "nearest" });
  });
  S.start();
})();
