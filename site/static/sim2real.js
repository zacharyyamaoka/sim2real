/* sim2real: the seams robotparts' shell leaves to a catalog, and the record tabs' dashboards. shell.js and site.js run
   unchanged before this file (catalog-workbench's page: shell.js, site.js, then the catalog's scripts, then the kit).
   - The dashboards: each tab holds a placeholder (.s2r-dash, site/pages.py dashboard()); the first time its tab is shown
     this script makes the <data-dashboard> there. WHY lazy: the coverage set is 35 MB and a run has six tables, so only
     the open tab's are fetched. Only the first tab's dashboard owns the URL (its clock is #t=…); the others get no-url,
     so data-ui never scopes the clock key and an old #t=… link lands on the Playback.
   - Every .base a dashboard loads is rewritten before data-ui reads it, as app/app.js did: {deployment}, {run},
     {station} and {device} from the page's record (#s2r-record), and the colour slots resolved for the theme on screen
     (real is data-ui's series slot 1, blue; every model slot 2, orange; Vega-Lite and the 3D card cannot read var()).
     Zach (2026-10-28): "train the eye to know what is real and what is sim. Blue and orange ... leaves green and red for elsewhere".
   - The search: shell.js submits the bar's box to /search/?q=…; here the words become the list's query (data-ui
     CONTRACT §15), set before the kit upgrades the element. shell.js's typed suggestions and site.js's results line are
     written for parts; here they read as runs, stations and deployments.
   No storage is touched here; Settings stay in shell.js. */
(function () {
  "use strict";
  var record = {};
  try { record = JSON.parse((document.getElementById("s2r-record") || {}).textContent || "{}"); } catch (e) { record = {}; }

  // ---- the search page: ?q= becomes the list's query --------------------------------------------------------------
  var views = document.getElementById("parts-views");
  var words = new URLSearchParams(location.search).get("q");
  if (views && words && !views.hasAttribute("query")) views.setAttribute("query", words);

  // ---- the nouns: robotparts' words -> sim2real's ------------------------------------------------------------------
  var NOUNS = [
    [/^Categories and brands$/, "Deployments and stations"],
    [/^Parts$/, "Runs"],
    [/^Category · ([\d,]+) parts$/, "Deployment · $1 runs"],
    [/^Brand · (.*) · ([\d,]+) parts$/, "Station · $1 · $2 runs"],
    [/ · level 1\b/, " · with models"],
    [/ · level 0\b/, " · real only"],
    [/^No part, brand or category has /, "No run, station or deployment has "],
  ];
  function relabel(el) {
    var text = el.textContent, next = text;
    NOUNS.forEach(function (rule) { next = next.replace(rule[0], rule[1]); });
    if (next !== text) el.textContent = next;
  }
  var typed = document.querySelector("#sm .sm-typed");
  if (typed && window.MutationObserver) {
    new MutationObserver(function () {
      Array.prototype.forEach.call(typed.querySelectorAll(".sm-h, .sg small, .none"), function (el) { if (el.children.length === 0) relabel(el); });
    }).observe(typed, { childList: true, subtree: true });
  }
  var shown = document.getElementById("shown");
  if (views && shown) {
    views.addEventListener("data-views-change", function () {
      var model = views.model;
      if (!model) return;
      var n = function (x) { return x.toLocaleString("en-US"); };
      shown.textContent = model.matched === model.total ? n(model.total) + (model.total === 1 ? " run" : " runs")
        : n(model.matched) + " of " + n(model.total) + " runs";
    });
  }

  // ---- the dashboards ---------------------------------------------------------------------------------------------
  var slots = Array.prototype.slice.call(document.querySelectorAll(".s2r-dash[data-src]"));
  if (!slots.length) return;
  var KIT = "/static/data-ui/";
  var SLOT = /var\(--(data-series-\d)\)/g;
  var MIX = /color-mix\((?:[^()]|\([^()]*\))*\)/g;
  var ready = Promise.all([import(KIT + "data-ui.js"), import(KIT + "dashboard.js")]).then(function (mods) {
    var kit = mods[0];
    // WHY hex: a resolved colour lands inside YAML flow mappings ({ value: ... }), where the commas of rgb(r, g, b) split it
    var hex = function (css) {
      var m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?/.exec(kit.toRgb(css) || css);
      if (!m) return css;
      var parts = [m[1], m[2], m[3]].map(Number);
      if (m[4] !== undefined && Number(m[4]) < 1) parts.push(Number(m[4]) * 255);
      return "#" + parts.map(function (v) { return Math.round(v).toString(16).padStart(2, "0"); }).join("");
    };
    // and a bare # starts a YAML comment, so an unquoted value gets quotes
    var quoted = function (value, before) { return before === "'" || before === '"' ? value : "'" + value + "'"; };
    // The page's record, then the .base URL's query (?deployment=…, the home's matrix), fill {name}. WHY an empty field is
    // left alone: on a page that is no run, `{run}` is data-ui's own per-pick placeholder (CONTRACT §33), filled from the
    // runs table's pick. A number (a gate's limit) replaces its quotes too, so YAML reads a number; null draws no limit.
    var fill = function (text, url) {
      var values = {};
      Object.keys(record).forEach(function (k) { values[k] = record[k]; });
      try { new URL(url, location.href).searchParams.forEach(function (v, k) { values[k] = v; }); } catch (e) { /* keep the record's */ }
      Object.keys(values).forEach(function (k) {
        var v = values[k], token = "{" + k + "}";
        if (v === "" || v === undefined) return;
        if (v === null || typeof v === "number") {
          var literal = v === null ? "null" : String(v);
          text = text.split("'" + token + "'").join(literal).split('"' + token + '"').join(literal).split(token).join(literal);
        } else {
          text = text.split(token).join(String(v));
        }
      });
      return text;
    };
    var nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
      return nativeFetch(input, init).then(function (response) {
        var url = typeof input === "string" ? input : (input instanceof URL ? input.href : input.url);
        if (!response.ok || !/\.base(?:[?#]|$)/.test(url) || url.indexOf("/views/") === -1) return response;
        return response.text().then(function (text) {
          var slotsCss = kit.resolveTokens(document.querySelector("data-dashboard") || document.body).css;
          var out = fill(text, url)
            .replace(MIX, function (mix, at, all) { return quoted(hex(mix.replace(SLOT, function (_m, name) { return slotsCss[name]; })), all[at - 1]); })
            .replace(SLOT, function (_m, name, at, all) { return quoted(hex(slotsCss[name]), all[at - 1]); });
          return new Response(out, { status: response.status, statusText: response.statusText, headers: response.headers });
        });
      });
    };
    return kit;
  });

  var mounted = [];
  function visible(el) { return el.getClientRects().length > 0; }
  function mount(slot) {
    slot.setAttribute("data-mounted", "");
    ready.then(function () {
      var dash = document.createElement("data-dashboard");
      if (!slot.hasAttribute("data-own-url")) dash.setAttribute("no-url", "");
      dash.setAttribute("aria-label", slot.getAttribute("aria-label") || "");
      slot.textContent = "";
      slot.appendChild(dash);
      dash.setAttribute("src", slot.getAttribute("data-src"));
      mounted.push(dash);
    });
  }
  function scan() { slots.forEach(function (slot) { if (!slot.hasAttribute("data-mounted") && visible(slot)) mount(slot); }); }
  new MutationObserver(scan).observe(document.querySelector(".panels") || document.body, { attributes: true, attributeFilter: ["hidden"], subtree: true });
  scan();
  addEventListener("load", scan);
  // the colours are resolved per theme: a theme change redraws every dashboard
  var redraw = function () { mounted.forEach(function (dash) { if (dash.reload) dash.reload(); }); };
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", redraw);
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
})();
