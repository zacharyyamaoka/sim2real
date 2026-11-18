/* V3 Scene: the deployment in 3D is the page. Every station carries its verdict as a label in space; the typed tree is a
   slim outline; the picked node's card sits on the right; picking a servo or one of its parts explodes that station in 3D
   (motor, gearbox, encoder, driver pulled apart, each tinted by its own status). The nested table is a sheet pulled up from
   the bottom. Before vs now is a time bar under the scene: drag it and the scene, the labels and the card change together.
   Backend: the RobotPart type carries .models, .metrics and .dx side by side (BACKEND.md). */
(function () {
  "use strict";
  var S = window.S2R, FX = S.fx, esc = S.esc;
  var $ = function (id) { return document.getElementById(id); };
  var rack = null, tree = null, current = null;

  function definedIn(m, node) { return "robotparts · types." + node.type.id + ".metrics." + (m.code || m.id); }
  function labelFor(sid, rid) {
    var n = S.node(sid), v = n.verdict[rid], a = S.answer(n, rid);
    var tail = v.status === "pass" ? S.fmtShort(S.metric(n, "passes_up_to"), S.metric(n, "passes_up_to").values[rid]) + " of top speed" : a.metric ? a.q.name + " " + S.fmtShort(a.metric, a.metric.values[rid]) : "";
    return S.dot(v.status) + "<b>" + esc(n.short) + "</b><small>" + esc(tail) + "</small>";
  }

  function home() {
    var tiles = FX.deployments.map(function (d, i) {
      var badge = d.in_fixture ? S.chip(d.headline.r8.goal_met ? "pass" : "fail", (d.headline.r8.goal_met ? "goal met" : "goal not met") + " · " + d.headline.r8.gates_passed + " of " + d.headline.r8.gates_total + " gates")
        : S.chip(d.verdict === "pass" ? "pass" : "fail", "oracle " + d.verdict + " · sim only");
      var inner = '<img src="' + S.media(d.render) + '" alt=""><span class="badge">' + badge + '</span><div class="cap"><b>' + esc(d.title) + " " + S.chip(d.kind === "physical" ? "real" : "sim", d.kind === "physical" ? "real hardware" : "virtual") + "</b><div>" + esc(d.summary) + "</div></div>";
      return d.in_fixture ? '<a class="tile big" href="#/d/' + d.id + '">' + inner + "</a>" : '<div class="tile off" title="not in this fixture">' + inner + "</div>";
    }).join("");
    $("home").innerHTML = '<h1>Deployments</h1><p class="lede">Each machine as you would see it. Open one to walk it in 3D: every station wears its verdict, and every part can be pulled out to see its own.</p><div class="tiles">' + tiles + "</div>";
  }

  function card(st) {
    var n = S.node(st.node), rid = st.round;
    if (S.load("card.folded", false)) { $("card").hidden = true; $("sashC").hidden = true; return; }
    $("card").hidden = false; $("sashC").hidden = false;
    var parts = S.kids(n.id).map(function (k) {
      var a = S.answer(k, rid);
      return '<div class="p" data-go="' + esc(k.id) + '">' + S.dot(a.status === "none" ? (k.metrics.length ? "not_observable" : "none") : a.status) + S.icon(k.type.id) + "<b>" + esc(k.short) + '</b><span class="l">' + esc(a.head) + "</span></div>";
    }).join("");
    var station = S.stationOf(n.id);
    $("card").innerHTML = '<div class="cardbar"><span class="kicker" style="flex:1">' + S.icon(n.type.id) + esc(n.type.name) + (n.gating ? "" : " · shown, not gating") + '</span><button class="iconbtn" id="foldCard" title="Fold the card (Esc)">' + S.svg.close + "</button></div>" +
      "<h2>" + esc(n.title) + '</h2><div class="sub">judged at ' + esc(n.judged_at) + (n.unit ? " · " + esc(n.unit) : "") + "</div>" +
      S.answerHTML(n, rid) + (n.caveat ? '<div class="caveat" style="margin-top:8px">' + esc(n.caveat) + "</div>" : "") +
      (n.metrics.length ? "<h3>Five questions · " + esc(S.round(rid).label) + "</h3>" + S.fiveQuestions(n, rid, { was: true }) : '<h3>Facts</h3><p class="muted">' + (n.facts || []).map(function (f) { return esc(f[0]) + ": " + esc(f[1]); }).join(" · ") + "</p>") +
      (parts ? "<h3>" + (n.level === "servo" ? "Its parts · pulled apart in 3D" : "Under it") + '</h3><div class="parts">' + parts + "</div>" : "") +
      (n.metrics.length ? '<h3>Defined on the part type</h3><p class="muted mono" style="font-size:12px;margin:0">robotparts.types.' + esc(n.type.id) + ".metrics · beside .models and .dx</p>" : "") +
      (station && n.level !== "station" ? '<h3>Back up</h3><div class="parts"><div class="p" data-go="' + station.id + '">' + S.icon(station.type.id) + "<b>" + esc(station.short) + '</b><span class="l">' + esc(S.answer(station, rid).head) + "</span></div></div>" : "");
    $("card").querySelectorAll("[data-go]").forEach(function (el) { el.addEventListener("click", function () { S.go({ node: el.dataset.go }); }); });
    $("foldCard").addEventListener("click", function () { S.save("card.folded", true); card(S.state()); if (rack) rack.resize(); });
  }

  var tfolded = new Set(S.load("sheet.folded", FX.nodes.filter(function (n) { return n.level === "servo"; }).map(function (n) { return n.id; })));
  function sheet(st) {
    var open = S.load("sheet.open", false), rid = st.round;
    $("sheet").classList.toggle("open", open); $("sashB").classList.toggle("off", !open); $("sheetBtn").setAttribute("aria-expanded", String(open));
    var r = FX.nodes[0];
    $("sheetSum").textContent = "· the typed tree, " + FX.nodes.length + " nodes · " + (open ? "drag the edge above to resize" : "click to pull up");
    if (!open) return;
    var rows = [];
    S.walk(function (n, depth) {
      for (var p = S.parent(n.id); p; p = S.parent(p.id)) if (tfolded.has(p.id)) return;
      var a = S.answer(n, rid), m = a.metric || (n.level === "station" ? S.metric(n, "passes_up_to") : n.metrics[0]);
      rows.push('<tr data-id="' + esc(n.id) + '" class="' + (n.id === st.node ? "sel" : "") + '"><td><span class="nm" style="padding-left:' + depth * 16 + 'px"><span class="tw" ' + (n.children.length ? 'data-tw="1"' : 'style="visibility:hidden"') + '><svg viewBox="0 0 12 12" style="transform:rotate(' + (tfolded.has(n.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' + S.icon(n.type.id) + esc(n.short) + "</span></td>" +
        "<td>" + esc(n.type.name) + "</td><td>" + (a.status === "none" ? '<span class="muted">—</span>' : S.chip(a.status, { pass: "pass", fail: "fail", watch: "watch", not_observable: "not seen", not_run: "not run" }[a.status])) + "</td>" +
        "<td>" + FX.questions.map(function (q) { var s = n.questions[rid][q.id].status; return S.dot(s === "none" ? "none" : s, q.name + ": " + (S.WORD[s] || "—")); }).join(" ") + "</td>" +
        '<td class="v">' + (m ? esc(m.name) + " <b>" + esc(S.fmt(m, m.values[rid])) + "</b> " + S.was(m, rid) : "") + "</td></tr>");
    });
    $("sheetBody").innerHTML = '<table class="nt"><thead><tr><th>Component</th><th>Type</th><th>Verdict</th><th>F D R T J</th><th>Lead metric · ' + esc(S.round(rid).label) + "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }
  $("sheetBtn").addEventListener("click", function () { S.save("sheet.open", !S.load("sheet.open", false)); sheet(S.state()); if (rack) rack.resize(); });
  $("sheetBody").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]"); if (!tr) return;
    if (ev.target.closest("[data-tw]")) { var id = tr.dataset.id; if (tfolded.has(id)) tfolded.delete(id); else tfolded.add(id); S.save("sheet.folded", Array.from(tfolded)); sheet(S.state()); return; }
    S.go({ node: tr.dataset.id });
  });

  function timebar(st) {
    var rid = st.round, rack_ = S.node(FX.root);
    $("time").value = rid === "r0" ? "0" : "1";
    var g = S.metric(rack_, "gates_passed").values[rid], tw = S.metric(rack_, "stations_twinned").values[rid], tr = S.metric(rack_, "stations_tracking").values[rid];
    $("tbsum").innerHTML = "<b>" + g.value + " of " + g.of + "</b> gates · <b>" + tr.value + " of 6</b> track to 0.9 · <b>" + tw.value + " of 6</b> twinned";
  }
  $("time").addEventListener("input", function () { S.go({ round: $("time").value === "0" ? "r0" : "r8" }, true); });

  S.sash($("sashO"), $("outline"), { key: "outline", min: 170, max: 460, dflt: 230, onResize: function () { if (rack) rack.resize(); } });
  S.sash($("sashC"), $("card"), { key: "card", min: 300, max: 700, dflt: 400, invert: true, onResize: function () { if (rack) rack.resize(); } });
  S.sash($("sashB"), $("sheet"), { key: "sheet", horizontal: true, min: 120, max: 620, dflt: 280, invert: true, onResize: function () { if (rack) rack.resize(); } });
  tree = new S.Tree($("outline"), { key: "v3", title: "Outline", foldStations: true, round: function () { return S.state().round; }, onSelect: function (id) { S.go({ node: id }); }, line: function () { return ""; } });
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && ev.target.tagName !== "INPUT" && !S.load("card.folded", false)) { S.save("card.folded", true); card(S.state()); if (rack) rack.resize(); } });
  S.on(function (st) {
    var home_ = st.page === "home";
    $("home").hidden = !home_; $("dep").hidden = home_;
    $("crumbs").innerHTML = home_ ? "<b>Deployments</b>" : '<a href="#/">Deployments</a><span class="sep">/</span><a href="' + S.href({ node: FX.root }) + '">' + esc(FX.deployments[0].title) + "</a>" + S.ancestors(st.node).slice(1).map(function (a) { return '<span class="sep">/</span><a href="' + S.href({ node: a.id }) + '">' + esc(a.short) + "</a>"; }).join("") + (st.node !== FX.root ? '<span class="sep">/</span><b>' + esc(S.node(st.node).short) + "</b>" : "");
    if (home_) return home();
    if (!rack) rack = new S.Rack3D($("scene"), { labels: "all", label: labelFor, onPick: function (id) { S.save("card.folded", false); S.go({ node: id }); }, partPick: "exploded", partTint: true });
    if (current !== st.node) S.save("card.folded", S.load("card.folded", false) && current === null ? true : false);
    tree.select(st.node);
    var n = S.node(st.node), station = S.stationOf(n.id);
    rack.explode(n.level !== "station" && station ? station.id : null);
    rack.setRound(st.round);
    var changed = current !== st.node;
    rack.select(st.node === FX.root ? null : st.node, changed);
    current = st.node;
    timebar(st); card(st); sheet(st);
    if (changed) $("card").scrollTop = 0;
    rack.resize();
  });
  S.start();
})();
