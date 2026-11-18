/* V1 Workbench: RobotDx's frame on the typed tree. Icon rail (Deployments · Tree · Table); the tree on the left; the
   picked level's entity page on the right (header, one answer, the 3D strip, tabs: Gates · Metrics · Speed ladder ·
   Definition); RobotDx's Table view with a foldable inspector. Before vs now: one round switch in the bar, every value
   carries the other round beside it ("was 4.27× ▲"). Backend: metrics nested on the ModelFamily (BACKEND.md). */
(function () {
  "use strict";
  var S = window.S2R, FX = S.fx, esc = S.esc;
  var $ = function (id) { return document.getElementById(id); };
  var tree, rack, current = null;

  // ---- the backend this proposal argues for: definitions nested on the ModelFamily ---------------------------------------
  var FAMILY = { deployment: "sim2real.Deployment", pendulum_arm_1dof: "RigidBodyChain", integrated_servo: "IntegratedServo", foc_controller: "FocController",
                 bldc_motor: "BldcMotor", gearbox: "Gearbox", encoder: "Encoder", rigid_link: "RigidBodyChain.link", depth_camera: "DepthCamera" };
  var GENERIC = { floor: "floor", data: "coverage", routines: "oracle", twin: "twin", job: "job" };
  function definedIn(m, node) {
    var fam = FAMILY[node.type.id];
    if (node.level === "deployment") return "sim2real · Deployment.metrics." + m.id + " (roll-up)";
    var own = ["repeat_floor", "rungs_measured", "oracle_recovery", "twin_over_floor", "passes_up_to", "T1", "T2", "T4"].indexOf(m.id) >= 0;
    return "robot_models · " + fam + ".metrics." + (own ? GENERIC[m.question] + " (generic)" : m.id);
  }
  function sketch(node) {
    var GEN = ["repeat_floor", "rungs_measured", "oracle_recovery", "twin_over_floor", "passes_up_to", "T1", "T2", "T4", "homing_repeat"];
    var fam = FAMILY[node.type.id] || "ModelFamily", own = node.metrics.filter(function (m) { return m.kind !== "observed" && GEN.indexOf(m.id) < 0; });
    if (node.level === "deployment") {
      return '<span class="c"># sim2real: a deployment rolls its children up; it defines no metric of its own beyond the goal</span>\n' +
        'values = sim2real.<span class="k">evaluate</span>(deployment, round_dir=<span class="s">".../onedof_2026-11-15/round8"</span>)\n' +
        'values[<span class="s">"can11"</span>][<span class="s">"twin"</span>]           <span class="c"># Value(2.14, "× floor", status="fail")</span>\n' +
        'values.<span class="k">write</span>(<span class="s">"app/data/one-dof-test-rack/values/r8.json"</span>)   <span class="c"># the page reads this file</span>';
    }
    var lines = own.map(function (m) {
      return "        " + (m.code ? m.code.toLowerCase() : m.id) + " = Metric(" + JSON.stringify(m.unit) + ', question="' + m.question + '"' + (m.gate ? ", target=" + JSON.stringify(m.gate.text) : "") + ")" + (m.kind === "not_observable" ? "  # not observable on this rack" : "");
    }).join("\n");
    return '<span class="c"># robot_models/…/' + fam.toLowerCase().replace(/\./g, "_") + '.py: beside the models, model-free, judged at "' + esc(node.judged_at) + '"</span>\n' +
      "class " + fam.split(".")[0] + "(ModelFamily, id=" + JSON.stringify(node.type.id) + "):\n" +
      '    class m3: ...                                   <span class="c"># the models, unchanged (fit lives here)</span>\n' +
      '    class <span class="k">metrics</span>(Metrics, output=' + JSON.stringify(node.judged_at.split(" (")[0]) + "):\n" +
      '        floor, data, routines, twin, job = FIVE      <span class="c"># the generic questions, inherited</span>\n' + (lines ? esc(lines) : '        <span class="c"># nothing of its own: the five generic questions are all it adds</span>') + "\n\n" +
      fam.split(".")[0] + '.metrics.twin               <span class="c"># a Metric: unit, question, default target, compute(log)</span>\n' +
      fam.split(".")[0] + '.metrics.evaluate(logs)     <span class="c"># {metric: Value} for ONE node; sim2real walks the tree</span>';
  }

  // ---- home: the deployments ---------------------------------------------------------------------------------------------
  function home() {
    var phys = FX.deployments.filter(function (d) { return d.kind === "physical"; }), virt = FX.deployments.filter(function (d) { return d.kind === "virtual"; });
    var row = function (d) {
      var head = "";
      if (d.in_fixture) {
        var h = d.headline.r8, h0 = d.headline.r0;
        head = '<div class="head">' + S.chip(h.goal_met ? "pass" : "fail", h.goal_met ? "goal met" : "goal not met") + "<b>" + h.gates_passed + " of " + h.gates_total + ' gates</b><span class="was">was ' + h0.gates_passed + " (round 0)</span></div>";
      } else head = '<div class="head">' + S.chip(d.verdict === "pass" ? "pass" : "fail", "oracle " + d.verdict) + '<div class="m">sim only · not in this fixture</div></div>';
      var inner = '<img src="' + S.media(d.render) + '" alt="">' + '<div><div class="t">' + esc(d.title) + " " + S.chip(d.kind === "physical" ? "real" : "sim", d.kind === "physical" ? "real hardware" : "virtual") + '</div><div class="l">' + esc(d.summary) + '</div><div class="m">' + esc(d.where) + "</div></div>" + head;
      return d.in_fixture ? '<a class="drow" href="#/d/' + d.id + '">' + inner + "</a>" : '<div class="drow off">' + inner + "</div>";
    };
    $("home").innerHTML = "<h1>Deployments</h1><p class=\"lede\">Each deployment is a machine we do sim to real on. Open one for its 3D view and its typed component tree; every node of the tree shows its metrics and gates.</p>" +
      '<div class="dlist"><div class="dsec">Physical · real hardware</div>' + phys.map(row).join("") + '<div class="dsec">Virtual · sysid oracle examples</div>' + virt.map(row).join("") + "</div>";
  }

  // ---- the entity page ---------------------------------------------------------------------------------------------------
  function entity(st) {
    var node = S.node(st.node) || S.node(FX.root), rid = st.round, tab = st.raw.get("tab") || "gates";
    var crumbs = S.ancestors(node.id).map(function (a) { return '<a href="' + S.href({ node: a.id, view: "" }) + '">' + esc(a.short) + "</a>"; }).concat(["<b>" + esc(node.short) + "</b>"]).join(" › ");
    var v = node.verdict[rid].status, word = { pass: "PASS", fail: "FAIL", watch: "WATCH", none: "NO GATES" }[v] || v;
    var health = node.health ? "<b>Unit health · RobotDx</b>faults in this round's runs <b style=\"display:inline;font-size:12.5px;color:var(--ink)\">" + node.health[rid].faults + "</b> · missing plays " + node.health[rid].missing +
      '<div class="muted" style="margin-top:3px">live faults, temperature, last heard: RobotDx (not in this fixture)</div>' : node.unit ? "<b>Unit</b>" + esc(node.unit) + '<div class="muted" style="margin-top:3px">its health is RobotDx\'s, apart from this verdict</div>' : "<b>Unit</b>no physical unit: a composition";
    var facts = (node.facts || []).map(function (f) { return "<span>" + esc(f[0]) + " <b>" + esc(f[1]) + "</b></span>"; }).join("");
    var counts = { gates: node.metrics.length ? 5 : 0, metrics: node.metrics.length };
    var tabs = [["gates", "Gates · five questions"], ["metrics", "Metrics"]];
    if (node.level === "station") tabs.push(["ladder", "Speed ladder"]);
    tabs.push(["def", "Definition"]);
    if (!tabs.some(function (t) { return t[0] === tab; })) tab = "gates";
    var html = '<div class="ent-head"><div class="ent-crumb">' + crumbs + "</div>" +
      '<h1 class="ent-title">' + S.icon(node.type.id) + esc(node.title) + " " + S.chip(v === "none" ? "none" : v, word) + "</h1>" +
      '<div class="ent-sub">' + S.chip("tag", node.type.name) + "<span>judged at " + esc(node.judged_at) + "</span><span>" + esc(S.roundLabel(rid)) + " · scored " + esc(S.when(rid)) + "</span>" + (node.gating ? "" : S.chip("tag", "shown, not gating")) + "</div>" +
      '<div class="ent-grid">' + S.answerHTML(node, rid) + '<div class="health">' + health + "</div></div>" + (facts ? '<div class="facts">' + facts + "</div>" : "") + (node.caveat ? '<div class="caveat" style="margin-top:8px">' + esc(node.caveat) + "</div>" : "") + "</div>" +
      '<div class="scene-wrap" id="sceneWrap"></div><div class="sash h" id="sashS"></div>' +
      '<div class="tabs" role="tablist">' + tabs.map(function (t) { return '<button role="tab" data-tab="' + t[0] + '" aria-selected="' + (t[0] === tab) + '">' + esc(t[1]) + (t[0] === "metrics" ? '<span class="n">' + counts.metrics + "</span>" : "") + "</button>"; }).join("") + "</div>" +
      '<div class="tabbody" id="tabbody"></div>';
    var host = $("entity");
    var keep = rack && rack._host;
    host.innerHTML = html;
    // the 3D strip: one view, kept alive across node changes (it re-parents, it does not rebuild)
    var wrap = $("sceneWrap");
    if (!keep) { keep = document.createElement("div"); rack = new S.Rack3D(keep, { labels: "all", onPick: pick, swing: true, partPick: true, label: function (sid, r) { var n = S.node(sid); return S.dot(n.verdict[r].status) + esc(n.short); } }); rack._host = keep; }
    wrap.appendChild(keep);
    S.sash($("sashS"), wrap, { key: "scene", horizontal: true, min: 140, max: 640, dflt: 300, onResize: function () { if (rack) rack.resize(); } });
    rack.setRound(rid);
    var changed = current !== node.id;
    if (changed) host.scrollTop = 0;
    rack.select(node.id === FX.root ? null : node.id, changed);
    current = node.id;
    host.querySelectorAll("[data-tab]").forEach(function (b) { b.addEventListener("click", function () { S.go({ tab: b.dataset.tab }, true); }); });
    var body = $("tabbody");
    if (tab === "gates") {
      body.innerHTML = S.fiveQuestions(node, rid, { was: true }) + kids(node, rid);
    } else if (tab === "metrics") {
      body.innerHTML = S.metricTable(node, rid, { definedIn: definedIn });
    } else if (tab === "ladder") {
      body.innerHTML = '<div style="display:flex;gap:16px;align-items:center">' + S.legend() + '<span class="muted" style="font-size:12px">each rung is a fraction of that round\'s top speed: ' + esc(S.fmt({ unit: "rad/s" }, { value: null })) + "</span></div>" +
        '<div class="plots">' + Object.keys(S.RUNG_KEYS).map(function (k) { return '<div class="pc">' + S.rungPlot(node, k, { w: 320, h: 160 }) + "</div>"; }).join("") + "</div>";
      body.querySelector(".muted").textContent = "each rung is a fraction of that round's top speed: " + node.omega.r0 + " rad/s in round 0, " + node.omega.r8 + " rad/s now";
    } else {
      body.innerHTML = "<h3>Where this level's metrics are defined (this proposal's backend)</h3><pre class=\"sketch\">" + sketch(node) + "</pre>" +
        '<h3>How the page reads them</h3><p class="muted" style="max-width:80ch">sim2real walks the deployment\'s typed tree, asks each node\'s type for its metrics, computes them on the runs scoped to that node, and writes one file per round. The page only reads <code>values/&lt;round&gt;.json</code>. Fit stays on the Model (<code>Model.score</code>, <code>select_best</code>), health on the unit (RobotDx), the verdict here.</p>';
    }
    body.querySelectorAll("[data-go]").forEach(function (el) { el.addEventListener("click", function () { pick(el.dataset.go); }); });
  }
  function kids(node, rid) {
    if (!node.children.length) return "";
    return '<div class="childs"><h3>Under this ' + esc(node.type.name.toLowerCase()) + (node.level === "station" ? " · shown, not gating (MOC decision 1)" : "") + "</h3>" +
      S.kids(node.id).map(function (k) { var a = S.answer(k, rid); return '<div class="crow" data-go="' + esc(k.id) + '">' + S.dot(a.status === "none" ? (k.metrics.length ? "not_observable" : "none") : a.status) + S.icon(k.type.id) + "<b>" + esc(k.short) + '</b><span class="cl">' + esc(a.head) + "</span></div>"; }).join("") + "</div>";
  }
  function pick(id) { S.go({ node: id }); }

  // ---- the Table view ----------------------------------------------------------------------------------------------------
  var tableFolded = new Set(S.load("table.folded", FX.nodes.filter(function (n) { return n.level === "servo"; }).map(function (n) { return n.id; })));
  function keyMetric(node, rid) {
    var a = S.answer(node, rid); if (a.metric) return a.metric;
    var pref = { deployment: "gates_passed", station: "passes_up_to", servo: "T2" }[node.level];
    return (pref && S.metric(node, pref)) || node.metrics[0] || null;
  }
  function table(st) {
    var rid = st.round, sel = st.node;
    var rows = [];
    S.walk(function (n, depth) {
      for (var p = S.parent(n.id); p; p = S.parent(p.id)) if (tableFolded.has(p.id)) return;
      var a = S.answer(n, rid), km = keyMetric(n, rid);
      var fq = FX.questions.map(function (q) { var s = n.questions[rid][q.id].status; return S.dot(s === "none" ? "none" : s, q.name + ": " + (S.WORD[s] || "—")); }).join("");
      rows.push('<tr data-id="' + esc(n.id) + '" class="' + (n.id === sel ? "sel" : "") + '"><td><span class="nm" style="padding-left:' + depth * 16 + 'px">' +
        '<span class="tw" ' + (n.children.length ? 'data-tw="1"' : "") + ' style="' + (n.children.length ? "" : "visibility:hidden") + '">' + '<svg viewBox="0 0 12 12" style="transform:rotate(' + (tableFolded.has(n.id) ? 0 : 90) + 'deg)"><path d="M4 2.5L7.5 6 4 9.5"/></svg></span>' +
        S.icon(n.type.id) + esc(n.short) + "</span></td><td>" + esc(n.type.name) + '</td><td class="muted">' + esc(n.judged_at) + "</td>" +
        '<td><span class="fqd">' + fq + "</span></td>" + '<td class="msg"><b class="' + a.status + '">' + esc({ pass: "PASS", fail: "FAIL", watch: "WATCH" }[a.status] || "—") + "</b>" + esc(a.head) + "</td>" +
        '<td class="v">' + (km ? (km.code ? km.code + " " : "") + esc(S.fmt(km, km.values[rid])) : "") + '</td><td class="v" style="color:var(--was)">' + (km ? esc(S.fmt(km, km.values[S.other(rid)])) : "") + "</td>" +
        '<td class="muted">' + esc(n.unit || "") + "</td></tr>");
    });
    $("tablewrap").innerHTML = '<table class="dx"><thead><tr><th>Name</th><th>Type</th><th>Judged at</th><th title="Floor · Data · Routines · Twin · Job">F D R T J</th><th>Message</th><th>Key metric</th><th>' + esc(S.round(S.other(rid)).label) + "</th><th>Unit</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
    var folded = S.load("insp.folded", false);
    $("table").classList.toggle("folded", folded);
    $("insp").hidden = folded;
    var node = S.node(sel);
    $("insp").innerHTML = '<div class="insp-head">' + S.icon(node.type.id) + "<b>" + esc(node.title) + '</b><a class="btn" href="' + S.href({ view: "" }) + '">Open page</a><button class="iconbtn" data-fold title="Fold the inspector (Esc)">' + S.svg.close + "</button></div>" +
      '<div class="insp-body">' + S.answerHTML(node, rid) + S.fiveQuestions(node, rid, { was: true, compact: true }) + "</div>";
    $("insp").querySelector("[data-fold]").addEventListener("click", function () { S.save("insp.folded", true); table(S.state()); });
  }
  $("tablewrap").addEventListener("click", function (ev) {
    var tr = ev.target.closest("tr[data-id]");
    if (!tr) { if (!S.load("insp.folded", false)) { S.save("insp.folded", true); table(S.state()); } return; }
    var id = tr.dataset.id;
    if (ev.target.closest("[data-tw]")) { if (tableFolded.has(id)) tableFolded.delete(id); else tableFolded.add(id); S.save("table.folded", Array.from(tableFolded)); table(S.state()); return; }
    S.save("insp.folded", false);
    S.go({ node: id }, true);
  });
  addEventListener("keydown", function (ev) { if (ev.key === "Escape" && S.state().view === "table" && !S.load("insp.folded", false)) { S.save("insp.folded", true); table(S.state()); } });

  // ---- routing -----------------------------------------------------------------------------------------------------------
  S.sash($("sashL"), $("left"), { key: "tree", min: 220, max: 560, dflt: 330 });
  S.sash($("sashT"), $("insp"), { key: "insp", min: 280, max: 700, dflt: 420, invert: true });
  tree = new S.Tree($("left"), { key: "v1", round: function () { return S.state().round; }, onSelect: pick, line: function (n) { return n.type.name; } });
  document.querySelectorAll("#round button").forEach(function (b) { b.addEventListener("click", function () { S.go({ round: b.dataset.r }, true); }); });
  S.on(function (st) {
    var view = st.page === "home" ? "home" : st.view === "table" ? "table" : "tree";
    $("home").hidden = view !== "home"; $("dep").hidden = view !== "tree"; $("table").hidden = view !== "table";
    $("round").hidden = view === "home";
    document.querySelectorAll("#round button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.r === st.round)); });
    document.querySelectorAll(".railbtn").forEach(function (a) { if (a.dataset.v === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    var dep = FX.deployments[0];
    $("crumbs").innerHTML = view === "home" ? "<b>Deployments</b>" : '<a href="#/">Deployments</a><span class="sep">/</span><a href="' + S.href({ node: FX.root, view: "" }) + '">' + esc(dep.title) + "</a>" + (st.node !== FX.root ? '<span class="sep">/</span><b>' + esc(S.node(st.node).short) + "</b>" : "") + (view === "table" ? '<span class="sep">·</span><b>Table</b>' : "");
    if (view === "home") return home();
    tree.select(st.node);
    if (view === "table") return table(st);
    entity(st);
  });
  S.start();
})();
