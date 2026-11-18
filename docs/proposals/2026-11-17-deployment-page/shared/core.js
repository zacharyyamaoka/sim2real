/* Shared by all five proposals: the fixture, the selection state (in the URL), formatting, the status words, the typed tree,
   the splitters, the five-question and metric renderers, and the speed-ladder plot. Each variant composes these into its own
   layout (each v1..v5 app.js); what differs between proposals is the structure, never the numbers.
   WHY no framework: a proposal page has one tree of 45 nodes; plain DOM keeps every variant openable from file://. */
(function () {
  "use strict";
  var FX = window.S2R_FIXTURE;
  var S2R = (window.S2R = { fx: FX });
  var byId = {};
  FX.nodes.forEach(function (n) { byId[n.id] = n; });
  var Q = {};
  FX.questions.forEach(function (q) { Q[q.id] = q; });
  S2R.Q = Q;
  S2R.node = function (id) { return byId[id] || null; };
  S2R.kids = function (id) { var n = byId[id]; return n ? n.children.map(function (c) { return byId[c]; }) : []; };
  S2R.parent = function (id) { var n = byId[id]; return n && n.parent ? byId[n.parent] : null; };
  S2R.ancestors = function (id) { var out = [], p = S2R.parent(id); while (p) { out.unshift(p); p = S2R.parent(p.id); } return out; };
  S2R.walk = function (fn, id, depth) { id = id || FX.root; depth = depth || 0; var n = byId[id]; fn(n, depth); n.children.forEach(function (c) { S2R.walk(fn, c, depth + 1); }); };
  S2R.stationOf = function (id) { var n = byId[id]; while (n && n.level !== "station") n = n.parent ? byId[n.parent] : null; return n; };
  S2R.round = function (rid) { return FX.rounds.filter(function (r) { return r.id === rid; })[0]; };
  S2R.other = function (rid) { return rid === "r8" ? "r0" : "r8"; };
  S2R.metric = function (node, mid) { return node.metrics.filter(function (m) { return m.id === mid; })[0] || null; };

  // ---- storage (per variant, this browser only; the page reads the same without it) -----------------------------------
  var NS = "s2r.deployment-page." + (document.documentElement.getAttribute("data-variant") || "x") + ".";
  S2R.load = function (k, d) { try { var v = localStorage.getItem(NS + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } };
  S2R.save = function (k, v) { try { if (v == null) localStorage.removeItem(NS + k); else localStorage.setItem(NS + k, JSON.stringify(v)); } catch (e) { /* this visit only */ } };

  // ---- state in the URL: #/  ·  #/d/<deployment>?n=<node>&view=<view>&round=<r0|r8>&cmp=1 ---------------------------
  var listeners = [];
  S2R.state = function () {
    var h = location.hash.replace(/^#/, "") || "/";
    var q = h.indexOf("?"), path = q >= 0 ? h.slice(0, q) : h, params = new URLSearchParams(q >= 0 ? h.slice(q + 1) : "");
    var m = path.match(/^\/d\/([^/?]+)/);
    return { page: m ? "deployment" : "home", dep: m ? decodeURIComponent(m[1]) : null, node: params.get("n") || FX.root,
             view: params.get("view") || "", round: params.get("round") || "r8", cmp: params.get("cmp") === "1",
             q: params.get("q") || "", raw: params };
  };
  S2R.href = function (patch) {
    var s = S2R.state(); var next = Object.assign({}, s, patch || {});
    if (next.page === "home") return "#/";
    var p = new URLSearchParams();
    if (next.node && next.node !== FX.root) p.set("n", next.node);
    if (next.view) p.set("view", next.view);
    if (next.round && next.round !== "r8") p.set("round", next.round);
    if (next.cmp) p.set("cmp", "1");
    if (next.q) p.set("q", next.q);
    // extra keys (a tab, a mode) stay until a patch changes them; null removes one
    var STD = ["page", "dep", "node", "view", "round", "cmp", "q", "n"];
    s.raw.forEach(function (val, k) { if (STD.indexOf(k) < 0 && !(k in (patch || {}))) p.set(k, val); });
    Object.keys(patch || {}).forEach(function (k) { if (STD.indexOf(k) < 0 && patch[k] != null && patch[k] !== "") p.set(k, patch[k]); });
    var qs = p.toString();
    return "#/d/" + encodeURIComponent(next.dep || "one-dof-test-rack") + (qs ? "?" + qs : "");
  };
  S2R.go = function (patch, replace) {
    var h = S2R.href(patch);
    if (h === location.hash) return;
    if (replace) history.replaceState(null, "", h); else history.pushState(null, "", h);
    emit();
  };
  S2R.on = function (fn) { listeners.push(fn); };
  function emit() { var s = S2R.state(); listeners.forEach(function (fn) { fn(s); }); }
  addEventListener("popstate", emit);
  addEventListener("hashchange", emit);
  S2R.start = function () { emit(); };
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href^="#/"]');
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey) return;
    ev.preventDefault();
    if (a.getAttribute("href") !== location.hash) { history.pushState(null, "", a.getAttribute("href")); emit(); }
  });

  // ---- formatting ---------------------------------------------------------------------------------------------------------
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  S2R.esc = esc;
  // a metric's name inside a sentence: first letter lower-cased, codes and units kept (T1, Kt)
  S2R.lc = function (t) { t = String(t || ""); return /^[A-Z][a-z]/.test(t) ? t.charAt(0).toLowerCase() + t.slice(1) : t; };
  function n(x, d) { return (Math.round(x * Math.pow(10, d)) / Math.pow(10, d)).toFixed(d); }
  S2R.fmt = function (m, v) {
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
  };
  S2R.fmtShort = function (m, v) {
    var s = S2R.fmt(m, v);
    return s.replace(" of top speed", "").replace(" rungs", "").replace(" stations", "");
  };
  S2R.gateText = function (m) { return m.gate ? m.gate.text : "no gate"; };
  S2R.WORD = { pass: "pass", fail: "fails", watch: "outside target, not gating", not_observable: "not observable here", not_run: "not run",
               observed: "observed", none: "no gates here" };
  S2R.KIND = { gated: "goal gate", counted: "counted gate (in the 180, not the goal)", shown: "shown, not gating", observed: "observed, no gate",
               not_observable: "not observable on this rack" };
  S2R.dot = function (st, title) { return '<span class="dot ' + esc(st) + '" title="' + esc(title || S2R.WORD[st] || st) + '" aria-label="' + esc(title || S2R.WORD[st] || st) + '"></span>'; };
  S2R.chip = function (st, text) { return '<span class="chip ' + esc(st) + '">' + esc(text == null ? (S2R.WORD[st] || st) : text) + "</span>"; };
  S2R.code = function (m) { return m && m.code ? '<span class="code" title="' + esc(m.name) + '">' + esc(m.code) + "</span>" : ""; };
  // direction of change for a metric between rounds: better, worse or the same
  S2R.change = function (m, rid) {
    var a = m.values[S2R.other(rid)], b = m.values[rid];
    if (!a || !b || a.value == null || b.value == null) return { dir: "na", word: "" };
    var x = a.value, y = b.value;
    if (m.unit === "%") { x = Math.abs(x); y = Math.abs(y); }
    if (Math.abs(x - y) < 1e-9) return { dir: "flat", word: "same" };
    var better = m.better === "higher" ? y > x : y < x;
    if (rid === "r0") better = !better;
    return { dir: better ? "up" : "down", word: better ? "better" : "worse" };
  };
  S2R.was = function (m, rid) {
    var o = S2R.other(rid), v = m.values[o];
    if (!v) return "";
    var c = S2R.change(m, rid);
    var arrow = c.dir === "up" ? "▲" : c.dir === "down" ? "▼" : c.dir === "flat" ? "=" : "";
    return '<span class="was" title="' + esc(S2R.round(o).label + " (" + S2R.round(o).long + ")") + '">' + (o === "r0" ? "was " : "now ") + esc(S2R.fmt(m, v)) +
      (arrow ? ' <span class="delta-' + (c.dir === "up" ? "up" : c.dir === "down" ? "down" : "flat") + '">' + arrow + "</span>" : "") + "</span>";
  };

  // ---- the one answer at the top of a node ------------------------------------------------------------------------------
  S2R.answer = function (node, rid) {
    var v = node.verdict[rid], q = v.first ? Q[v.first] : null, qs = node.questions[rid];
    var lead = q ? S2R.metric(node, qs[q.id].metric) : null, lv = lead ? lead.values[rid] : null;
    var misses = [];
    FX.questions.forEach(function (qq) { (qs[qq.id].missed || []).forEach(function (mid) { misses.push(S2R.metric(node, mid)); }); });
    var missLine = misses.map(function (m) { return S2R.lc(m.name) + " " + S2R.fmt(m, m.values[rid]); }).join(" · ");
    var out = { status: v.status, q: q, metric: lead, head: "", detail: "", misses: missLine };
    if (!node.metrics.length) {
      out.status = "none"; out.head = "No gates of its own"; out.detail = "Judged " + node.judged_at + ".";
      return out;
    }
    if (node.level === "deployment") {
      var goal = S2R.metric(node, "goal_met").values[rid];
      if (goal.value) { out.head = "Campaign goal met"; out.detail = "Every station tracks to 0.9 of top speed and its twin passes at every rung."; return out; }
      var culprits = S2R.kids(node.id).filter(function (k) { return k.level === "station" && k.verdict[rid].status === "fail" && k.verdict[rid].first === v.first; });
      var named = culprits.map(function (k) {
        var km = S2R.metric(k, k.questions[rid][v.first].metric), kv = km.values[rid];
        return k.short + " · " + S2R.lc(km.name) + " " + S2R.fmt(km, kv);
      });
      out.head = "Goal not met · " + q.name + ": " + S2R.fmt(lead, lv);
      out.detail = culprits.length <= 2 ? named.join("; ") + "." : culprits.length + " of 6 stations fail at " + q.name.toLowerCase() + ".";
      out.culprits = culprits.map(function (k) { return k.id; });
      return out;
    }
    if (v.status === "pass") {
      out.head = node.level === "station" ? "Passes the campaign goal" : "Passes what this level can show";
      out.detail = node.level === "station" ? "Tracks and stops ≤ 1 mm up to " + S2R.fmt(S2R.metric(node, "passes_up_to"), S2R.metric(node, "passes_up_to").values[rid]) + "; twin ≤ 1.5× floor at every rung."
        : node.metrics.filter(function (m) { return m.values[rid].status === "pass"; }).map(function (m) { return m.name + " " + S2R.fmt(m, m.values[rid]); }).join(" · ");
      return out;
    }
    if (v.status === "fail" || v.status === "watch") {
      out.head = (v.status === "fail" ? "Fails at " : "Outside target, not gating · ") + q.name + ": " + S2R.lc(lead.name) + " " + S2R.fmt(lead, lv);
      out.detail = "Gate " + S2R.gateText(lead) + (lv.detail ? " · " + lv.detail : "") + ".";
      return out;
    }
    var no = node.metrics.filter(function (m) { return m.values[rid].status === "not_observable"; });
    if (no.length) { out.status = "not_observable"; out.head = "Not observable on this rack"; out.detail = no[0].values[rid].detail; return out; }
    out.status = "not_run"; out.head = "Nothing scored here in this round"; out.detail = node.metrics[0].values[rid].detail || "";
    return out;
  };
  S2R.answerHTML = function (node, rid, opts) {
    opts = opts || {};
    var a = S2R.answer(node, rid);
    return '<div class="answer ' + a.status + '">' + S2R.dot(a.status) + '<div><div class="a-head">' + esc(a.head) + "</div>" +
      '<div class="a-detail">' + esc(a.detail) + (a.misses && opts.misses !== false ? ' <span class="a-miss">Counted, not in the goal: ' + esc(a.misses) + ".</span>" : "") + "</div></div></div>";
  };

  // ---- icons per type -----------------------------------------------------------------------------------------------------
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
  S2R.icon = function (typeId) { return '<span class="ic"><svg viewBox="0 0 16 16">' + (P[typeId] || P.deployment) + "</svg></span>"; };
  S2R.svg = {
    collapse: '<svg viewBox="0 0 16 16"><path d="M4 6l4 3 4-3M4 10l4 3 4-3"/></svg>',
    expand: '<svg viewBox="0 0 16 16"><path d="M4 9l4-3 4 3M4 5l4-3 4 3"/></svg>',
    search: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>',
    twisty: '<svg viewBox="0 0 12 12"><path d="M4 2.5L7.5 6 4 9.5"/></svg>',
    fold: '<svg viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M10 2.5v11"/></svg>',
    table: '<svg viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.2"/><path d="M2 6h12M2 9.5h12M6 6v7.5"/></svg>',
    tree: '<svg viewBox="0 0 16 16"><path d="M3 3h4M5 3v9h4M5 7.5h4"/><rect x="9" y="6" width="5" height="3" rx=".8"/><rect x="9" y="10.5" width="5" height="3" rx=".8"/></svg>',
    cube: '<svg viewBox="0 0 16 16"><path d="M8 1.8l5.5 3v6.4L8 14.2l-5.5-3V4.8z M2.5 4.8L8 7.8l5.5-3M8 7.8v6.4"/></svg>',
    home: '<svg viewBox="0 0 16 16"><path d="M2.5 7.5L8 3l5.5 4.5M4 6.5V13h8V6.5"/></svg>',
    close: '<svg viewBox="0 0 16 16"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    question: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="6"/><path d="M6.4 6.3a1.7 1.7 0 1 1 2.4 1.6c-.6.3-.8.7-.8 1.3M8 11.3v.2"/></svg>',
  };

  // ---- splitter: every panel boundary drags, its size is remembered, double-click restores the default ----------------
  S2R.sash = function (sash, target, opt) {
    var key = "size." + opt.key, horiz = !!opt.horizontal, prop = horiz ? "height" : "width";
    var apply = function (px) { px = Math.max(opt.min || 120, Math.min(opt.max || 1200, px)); target.style[prop] = px + "px"; target.style.flex = "none"; if (opt.onResize) opt.onResize(px); return px; };
    var saved = S2R.load(key, null);
    apply(saved != null ? saved : opt.dflt);
    sash.setAttribute("role", "separator");
    sash.setAttribute("aria-orientation", horiz ? "horizontal" : "vertical");
    sash.title = "Drag to resize · double-click to reset";
    sash.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      var start = horiz ? ev.clientY : ev.clientX, size = target.getBoundingClientRect()[prop];
      sash.setPointerCapture(ev.pointerId);
      sash.classList.add("dragging");
      document.body.classList.add(horiz ? "resizing-h" : "resizing");
      var move = function (e) { var d = (horiz ? e.clientY : e.clientX) - start; apply(size + (opt.invert ? -d : d)); };
      var up = function () {
        sash.removeEventListener("pointermove", move); sash.removeEventListener("pointerup", up);
        sash.classList.remove("dragging"); document.body.classList.remove("resizing", "resizing-h");
        S2R.save(key, Math.round(target.getBoundingClientRect()[prop]));
      };
      sash.addEventListener("pointermove", move); sash.addEventListener("pointerup", up);
    });
    sash.addEventListener("dblclick", function () { S2R.save(key, null); apply(opt.dflt); });
    return { reset: function () { S2R.save(key, null); apply(opt.dflt); } };
  };

  // ---- the typed tree ---------------------------------------------------------------------------------------------------
  // opts: { round(): rid, line(node): text, meta(node, rid): html, onSelect(id), key, title }
  S2R.Tree = function (host, opts) {
    var self = this, selected = null, filter = "";
    var folded = new Set(S2R.load("tree.folded." + (opts.key || "t"), FX.nodes.filter(function (n) { return n.level === "servo" || (n.level === "station" && opts.foldStations); }).map(function (n) { return n.id; })));
    host.classList.add("tree");
    host.innerHTML = '<div class="tree-tools"><span class="ic" style="margin:0 4px 0 6px">' + S2R.svg.tree + '</span><b style="flex:1">' + esc(opts.title || "Typed tree") + "</b>" +
      '<button class="iconbtn" data-t="collapse" title="Collapse all">' + S2R.svg.collapse + '</button><button class="iconbtn" data-t="expand" title="Expand all">' + S2R.svg.expand + "</button></div>" +
      '<label class="tree-find">' + S2R.svg.search + '<input type="search" placeholder="Search parts, types, CAN ids…" aria-label="Search the typed tree"></label>' +
      '<div class="tree-sec"><span>Components</span><span class="cnts"></span></div><div class="tree-body" tabindex="0" role="tree" aria-label="typed component tree"></div><div class="tnone" hidden>No part matches.</div>';
    var body = host.querySelector(".tree-body"), input = host.querySelector("input"), none = host.querySelector(".tnone"), cnts = host.querySelector(".cnts");
    function rid() { return opts.round(); }
    function worse(a, b) { var o = { fail: 4, watch: 2, pass: 1 }; return (o[a] || 0) > (o[b] || 0); }
    function li(node) {
      var r = rid(), v = node.verdict[r].status, kids = node.children.length;
      var open = !folded.has(node.id) || !!filter;
      var below = "";
      if (kids && !open && worse(node.rollup[r], v)) below = '<span class="tmeta" title="something below is worse">' + S2R.dot(node.rollup[r]) + "</span>";
      var line = opts.line ? opts.line(node) : node.type.name;
      if (line && line === node.short) line = node.title.indexOf(" · ") > 0 ? node.title.split(" · ").slice(1).join(" · ") : "";
      var name = esc(node.short);
      if (filter) { var re = new RegExp("(" + filter.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"); name = name.replace(re, "<mark>$1</mark>"); }
      var h = '<li role="treeitem" data-id="' + esc(node.id) + '"' + (kids ? ' aria-expanded="' + open + '"' : "") + ' aria-selected="' + (selected === node.id) + '">' +
        '<div class="trow"><span class="tw"' + (kids ? ' data-tw="1"' : "") + ">" + (kids ? S2R.svg.twisty : "") + "</span>" + S2R.icon(node.type.id) +
        '<span class="tname" title="' + esc(node.title) + '">' + name + '</span><span class="tline">' + esc(line) + "</span>" + (opts.meta ? '<span class="tmeta">' + opts.meta(node, r) + "</span>" : "") + below + S2R.dot(v === "none" ? (node.metrics.length ? "not_observable" : "none") : v) + "</div>";
      if (kids) h += '<ul role="group">' + node.children.map(function (c) { var cn = S2R.node(c); return match(cn) ? li(cn) : ""; }).join("") + "</ul>";
      return h + "</li>";
    }
    function text(nd) { return (nd.short + " " + nd.title + " " + nd.type.name + " " + (nd.unit || "")).toLowerCase(); }
    function match(nd) { if (!filter) return true; if (text(nd).indexOf(filter.toLowerCase()) >= 0) return true; return nd.children.some(function (c) { return match(S2R.node(c)); }); }
    self.render = function () {
      var root = S2R.node(FX.root);
      body.innerHTML = match(root) ? '<ul>' + li(root) + "</ul>" : "";
      none.hidden = !!body.textContent.trim();
      var r = rid(), c = { pass: 0, fail: 0, watch: 0 };
      FX.nodes.forEach(function (nd) { var s = nd.verdict[r].status; if (c[s] != null) c[s] += 1; });
      cnts.innerHTML = '<span class="cnt">' + S2R.dot("pass") + c.pass + '</span><span class="cnt">' + S2R.dot("watch") + c.watch + '</span><span class="cnt">' + S2R.dot("fail") + c.fail + "</span>";
    };
    self.select = function (id, scroll) {
      selected = id;
      S2R.ancestors(id).forEach(function (a) { folded.delete(a.id); });
      self.render();
      var row = body.querySelector('li[data-id="' + CSS.escape(id) + '"] > .trow');
      if (row && scroll !== false) row.scrollIntoView({ block: "nearest" });
    };
    function save() { S2R.save("tree.folded." + (opts.key || "t"), Array.from(folded)); }
    function rows() { return Array.prototype.slice.call(body.querySelectorAll("li")).filter(function (l) { return l.offsetParent !== null; }); }
    body.addEventListener("click", function (ev) {
      var l = ev.target.closest("li"); if (!l) return;
      var id = l.getAttribute("data-id");
      if (ev.target.closest("[data-tw]")) { if (folded.has(id)) folded.delete(id); else folded.add(id); save(); self.render(); return; }
      opts.onSelect(id);
    });
    body.addEventListener("keydown", function (ev) {
      var all = rows(), at = all.findIndex(function (l) { return l.getAttribute("data-id") === selected; });
      var cur = all[at], go = function (l) { if (l) { ev.preventDefault(); opts.onSelect(l.getAttribute("data-id")); } };
      if (ev.key === "ArrowDown") go(all[at + 1]);
      else if (ev.key === "ArrowUp") go(all[at - 1]);
      else if (ev.key === "Home") go(all[0]);
      else if (ev.key === "End") go(all[all.length - 1]);
      else if (ev.key === "ArrowRight" && cur && cur.hasAttribute("aria-expanded")) { ev.preventDefault(); if (folded.has(selected)) { folded.delete(selected); save(); self.render(); } else go(all[at + 1]); }
      else if (ev.key === "ArrowLeft" && cur) { ev.preventDefault(); if (cur.getAttribute("aria-expanded") === "true") { folded.add(selected); save(); self.render(); } else { var p = S2R.parent(selected); if (p) opts.onSelect(p.id); } }
    });
    host.querySelector('[data-t="collapse"]').addEventListener("click", function () { FX.nodes.forEach(function (nd) { if (nd.children.length && nd.id !== FX.root) folded.add(nd.id); }); save(); self.render(); });
    host.querySelector('[data-t="expand"]').addEventListener("click", function () { folded.clear(); save(); self.render(); });
    input.addEventListener("input", function () { filter = input.value.trim(); self.render(); });
    input.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { input.value = ""; filter = ""; self.render(); } });
    self.focus = function () { body.focus(); };
    self.render();
  };

  // ---- the five questions, in order ------------------------------------------------------------------------------------
  S2R.fiveQuestions = function (node, rid, opts) {
    opts = opts || {};
    return '<div class="fq' + (opts.compact ? " compact" : "") + '">' + FX.questions.map(function (q) {
      var s = node.questions[rid][q.id], m = s.metric ? S2R.metric(node, s.metric) : null, v = m ? m.values[rid] : null;
      var st = s.status === "none" ? "none" : s.status;
      var body = m ? '<span class="v">' + esc(m.name) + " " + esc(S2R.fmt(m, v)) + "</span>" + (m.gate ? ' <span class="muted">· gate ' + esc(m.gate.text) + "</span>" : "") +
        (opts.was ? " " + S2R.was(m, rid) : "") + (v && v.detail ? '<div class="d">' + esc(v.detail) + "</div>" : "") +
        (s.misses ? '<div class="d" style="color:var(--warn)">+ ' + s.misses + " counted gate" + (s.misses > 1 ? "s" : "") + " miss: " + s.missed.map(function (x) { var mm = S2R.metric(node, x); return esc(S2R.lc(mm.name) + " " + S2R.fmt(mm, mm.values[rid])); }).join(", ") + "</div>" : "")
        : '<span class="d">' + (q.id === "routines" || q.id === "data" ? "asked at the station" : "no metric at this level") + "</span>";
      return '<div class="fq-row ' + st + '" data-q="' + q.id + '"><span class="fq-n">' + q.n + '</span><div class="fq-name">' + q.name + "<small>" + esc(q.ask) + "</small></div>" +
        '<div class="fq-body">' + S2R.chip(st, st === "none" ? "—" : S2R.WORD[st]) + " " + body + "</div></div>";
    }).join("") + "</div>";
  };

  // ---- all of a node's metrics: value now, before, gate, status, where it is defined -------------------------------------
  S2R.metricTable = function (node, rid, opts) {
    opts = opts || {};
    if (!node.metrics.length) return '<p class="muted">No metrics at this level: ' + esc(node.judged_at) + ".</p>";
    var cols = opts.cols || ["metric", "now", "was", "gate", "kind", "defined"];
    var head = { metric: "Metric", now: S2R.round(rid).label, was: S2R.round(S2R.other(rid)).label, gate: "Gate", kind: "Counts as", defined: "Defined in" };
    var h = '<table class="mt"><thead><tr>' + cols.map(function (c) { return "<th>" + esc(head[c]) + "</th>"; }).join("") + "</tr></thead><tbody>";
    FX.questions.concat([{ id: "verdict", name: "Verdict" }]).forEach(function (q) {
      var ms = node.metrics.filter(function (m) { return m.question === q.id; });
      if (!ms.length) return;
      h += '<tr class="q-head"><td colspan="' + cols.length + '">' + (q.n ? q.n + " · " : "") + esc(q.name) + "</td></tr>";
      ms.forEach(function (m) {
        var v = m.values[rid], o = m.values[S2R.other(rid)], c = S2R.change(m, rid);
        h += '<tr data-m="' + esc(m.id) + '">' + cols.map(function (col) {
          if (col === "metric") return "<td>" + S2R.code(m) + esc(m.name) + (v.detail ? '<div class="muted" style="font-size:12px">' + esc(v.detail) + "</div>" : "") + "</td>";
          if (col === "now") return '<td class="v">' + S2R.dot(v.status) + " " + esc(S2R.fmt(m, v)) + "</td>";
          if (col === "was") return '<td class="v" style="color:var(--was)">' + esc(S2R.fmt(m, o)) + (c.dir === "up" ? ' <span class="delta-up">▲</span>' : c.dir === "down" ? ' <span class="delta-down">▼</span>' : "") + "</td>";
          if (col === "gate") return "<td>" + esc(S2R.gateText(m)) + "</td>";
          if (col === "kind") return '<td class="muted">' + esc(S2R.KIND[m.kind]) + "</td>";
          if (col === "defined") return '<td class="muted mono" style="font-size:11.5px">' + esc(opts.definedIn ? opts.definedIn(m, node) : m.defined) + "</td>";
          return "<td></td>";
        }).join("") + "</tr>";
      });
    });
    return h + "</tbody></table>";
  };

  // ---- the speed ladder plot: one metric up the rungs, the gate as a line, round 0 dashed under round 8 -----------------
  S2R.RUNG_KEYS = {
    tracking_rms_deg: { name: "Tracking RMS", unit: "°", gate: function () { return FX.thresholds.tracking_rms_deg; } },
    tracking_peak_deg: { name: "Tracking peak", unit: "°", gate: function () { return FX.thresholds.tracking_peak_deg; } },
    stop_tool_mm: { name: "Tip stop error", unit: "mm", gate: function () { return FX.thresholds.stop_tool_mm; } },
    twin_ratio: { name: "Twin ÷ floor", unit: "×", gate: function () { return FX.thresholds.sim_vs_real_floor_ratio; } },
  };
  S2R.rungPlot = function (station, key, opts) {
    opts = opts || {};
    var W = opts.w || 300, H = opts.h || 150, L = 38, R = 10, T = 34, B = 26;
    var spec = S2R.RUNG_KEYS[key], gate = spec.gate();
    var rounds = opts.rounds || ["r0", "r8"];
    var vals = [];
    rounds.forEach(function (rid) { station.rungs[rid].forEach(function (r) { if (r[key] != null) vals.push(r[key]); }); });
    var now = station.rungs.r8.map(function (r) { return r[key]; }).filter(function (x) { return x != null; });
    var top = Math.max(gate * 2, (now.length ? Math.max.apply(null, now) : gate) * 1.15);
    var x = function (f) { return L + (f - 0.2) / 0.8 * (W - L - R); }, y = function (v) { return T + (1 - Math.min(v, top) / top) * (H - T - B); };
    var s = '<svg class="rplot" viewBox="0 0 ' + W + " " + H + '" width="' + W + '" height="' + H + '" role="img" aria-label="' + esc(spec.name + " up the speed ladder") + '">';
    s += '<rect x="' + L + '" y="' + y(gate) + '" width="' + (W - L - R) + '" height="' + (H - B - y(gate)) + '" fill="var(--pass)" opacity=".07"/>';
    if (opts.highlight) s += '<rect x="' + (x(+opts.highlight) - 13) + '" y="' + T + '" width="26" height="' + (H - T - B) + '" rx="4" fill="var(--ink)" opacity=".09"/>';
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(gate) + '" y2="' + y(gate) + '" stroke="var(--pass)" stroke-dasharray="4 3" stroke-width="1.2"/>';
    s += '<text x="' + (W - R) + '" y="' + (y(gate) - 4) + '" text-anchor="end" font-size="10.5" fill="var(--pass)">gate ' + gate + (spec.unit === "×" ? "×" : " " + spec.unit) + "</text>";
    [0, top / 2, top].forEach(function (t) { s += '<text x="' + (L - 5) + '" y="' + (y(t) + 3.5) + '" text-anchor="end" font-size="10" fill="var(--ink3)">' + (t < 1 ? t.toFixed(2) : t.toFixed(1)) + "</text>"; });
    [0.2, 0.4, 0.6, 0.8, 0.9, 1.0].forEach(function (f) { s += '<text x="' + x(f) + '" y="' + (H - 9) + '" text-anchor="middle" font-size="10" fill="var(--ink3)">' + f + "</text>"; });
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + (H - B) + '" y2="' + (H - B) + '" stroke="var(--rule)"/>';
    rounds.forEach(function (rid) {
      var pts = station.rungs[rid].filter(function (r) { return r[key] != null; });
      var col = rid === "r8" ? "var(--real)" : "var(--was)";
      if (pts.length > 1) s += '<polyline fill="none" stroke="' + col + '" stroke-width="' + (rid === "r8" ? 2 : 1.4) + '"' + (rid === "r0" ? ' stroke-dasharray="4 3"' : "") + ' points="' + pts.map(function (r) { return x(r.fraction) + "," + y(r[key]); }).join(" ") + '"/>';
      pts.forEach(function (r) {
        var clipped = r[key] > top;
        s += '<circle cx="' + x(r.fraction) + '" cy="' + y(r[key]) + '" r="' + (rid === "r8" ? 3.2 : 2.6) + '" fill="' + (rid === "r8" ? (r[key] <= gate ? col : "var(--fail)") : "var(--bg)") + '" stroke="' + (rid === "r8" && r[key] > gate ? "var(--fail)" : col) + '" stroke-width="1.4"><title>' + esc(S2R.round(rid).label + " · " + r.fraction + " rung · " + r[key] + " " + spec.unit) + "</title></circle>";
        if (clipped) s += '<text x="' + x(r.fraction) + '" y="' + (T - 4) + '" text-anchor="middle" font-size="9.5" fill="var(--was)">↑' + (r[key] < 10 ? r[key].toFixed(1) : Math.round(r[key])) + "</text>";
      });
    });
    s += '<text x="4" y="13" font-size="11.5" font-weight="650" fill="var(--ink)">' + esc(spec.name) + ' <tspan fill="var(--ink3)" font-weight="400">' + esc(spec.unit === "×" ? "× floor" : spec.unit) + "</tspan></text>";
    return s + "</svg>";
  };
  S2R.legend = function () {
    return '<span class="lg"><svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--was)" stroke-dasharray="4 3" stroke-width="1.4"/></svg> ' + esc(S2R.round("r0").label) +
      ' · <svg width="22" height="8"><line x1="0" x2="22" y1="4" y2="4" stroke="var(--real)" stroke-width="2"/></svg> ' + esc(S2R.round("r8").label) + "</span>";
  };

  // ---- the deployments landing, data (each variant draws it its own way) -------------------------------------------------
  S2R.deployments = FX.deployments;
  S2R.media = function (rel) { return "../fixture/" + rel; };
  S2R.roundLabel = function (rid) { var r = S2R.round(rid); return r.label + " · " + r.long; };
  S2R.when = function (rid) { var r = S2R.round(rid); return r.scored_utc.replace("T", " ").replace(/:\d\dZ$/, "Z"); };
})();
