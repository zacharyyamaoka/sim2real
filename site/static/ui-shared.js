/* sim2real's shared UI behaviour (site/ui_shared.py): the status tree (ui_shared.status_tree, the run page's entity tree).
   - Each node with children folds (its twisty, or ← / → on its row); Collapse all and Expand all fold every one; the rows a reader folded
     are remembered per tree (localStorage, this browser only; the page reads the same without it).
   - The search box shows the nodes it matches and their ancestors, nothing else; Escape clears it.
   - A click on a node (or Enter) picks it: the page shows the level section whose data-entity is the node (section.s2r-level), hides the
     others, and names the node in the URL (?entity=<node id>, a history entry, so Back returns to the level before); the body's
     data-entity-kind says which kind of level is shown (static/run-page.css hides the station's tabs on any other). A deep link opens its
     level at load; the tree's default (data-default, the run's station) keeps a clean URL. Any ?entity= link on the page does the same.
   - ↑ / ↓ move between the rows shown, Home / End to the first and last.
   WHY no framework: one tree of a few rows per page, drawn by the build (no JavaScript: every row is a link, every level section shows). */
(function () {
  "use strict";
  var tree = document.querySelector(".s2r-tree[data-etree]");
  if (!tree) return;
  var KEY = "sim2real.tree-folded." + (tree.getAttribute("data-etree") || location.pathname);
  var list = tree.querySelector("[role=tree]");
  var search = tree.querySelector("[data-etree-search]");
  var none = tree.querySelector("[data-etree-none]");
  var fallback = tree.getAttribute("data-default") || "";
  var items = function () { return Array.prototype.slice.call(list.querySelectorAll("[role=treeitem]")); };
  var item = function (id) { return items().filter(function (li) { return li.getAttribute("data-entity") === id; })[0] || null; };
  var parentOf = function (li) { var up = li.parentElement && li.parentElement.closest("[role=treeitem]"); return list.contains(up) ? up : null; };
  var foldable = function (li) { return li.hasAttribute("aria-expanded"); };
  var rowShown = function (li) { var row = li.querySelector(":scope > .s2r-etree-row"); return !!row && row.getClientRects().length > 0; };

  // ---- folding, remembered -------------------------------------------------------------------------------------------------------------
  function read() { try { return JSON.parse(localStorage.getItem(KEY) || "[]") || []; } catch (e) { return []; } }
  function save() {
    var folded = items().filter(function (li) { return li.getAttribute("aria-expanded") === "false"; }).map(function (li) { return li.getAttribute("data-entity"); });
    try { if (folded.length) localStorage.setItem(KEY, JSON.stringify(folded)); else localStorage.removeItem(KEY); } catch (e) { /* this visit only */ }
  }
  function fold(li, open) { if (foldable(li)) li.setAttribute("aria-expanded", open ? "true" : "false"); }
  read().forEach(function (id) { var li = item(id); if (li) fold(li, false); });
  tree.addEventListener("click", function (ev) {
    var tw = ev.target.closest("[data-etree-toggle]");
    if (tw && tree.contains(tw)) {
      var li = tw.closest("[role=treeitem]");
      fold(li, li.getAttribute("aria-expanded") === "false");
      save();
      return;
    }
    if (ev.target.closest("[data-etree-collapse]")) { items().forEach(function (li) { fold(li, false); }); save(); return; }
    if (ev.target.closest("[data-etree-expand]")) { items().forEach(function (li) { fold(li, true); }); save(); }
  });

  // ---- search ----------------------------------------------------------------------------------------------------------------------
  function find(words) {
    var terms = String(words || "").toLowerCase().split(/\s+/).filter(Boolean);
    var all = items();
    if (!terms.length) {
      tree.classList.remove("s2r-tree-finding");
      all.forEach(function (li) { li.hidden = false; });
      if (none) none.hidden = true;
      return;
    }
    var hit = function (li) { var hay = li.getAttribute("data-find") || ""; return terms.every(function (t) { return hay.indexOf(t) >= 0; }); };
    var keep = new Set();
    all.forEach(function (li) { if (hit(li)) for (var x = li; x; x = parentOf(x)) keep.add(x); });
    tree.classList.add("s2r-tree-finding");
    all.forEach(function (li) { li.hidden = !keep.has(li); });
    if (none) none.hidden = keep.size > 0;
  }
  if (search) {
    search.addEventListener("input", function () { find(search.value); });
    search.addEventListener("keydown", function (ev) { if (ev.key === "Escape" && search.value) { search.value = ""; find(""); ev.stopPropagation(); } });
  }

  // ---- picking a level -------------------------------------------------------------------------------------------------------------
  var panes = Array.prototype.slice.call(document.querySelectorAll("section.s2r-level[data-entity]"));
  function pause(root) {
    if (!root) return;
    Array.prototype.forEach.call(root.querySelectorAll("data-dashboard"), function (d) { try { if (d.clock && d.clock.playing) d.clock.pause(); } catch (e) { /* not started */ } });
  }
  function hrefFor(id) {
    var u = new URL(location.href);
    if (id && id !== fallback) u.searchParams.set("entity", id); else u.searchParams.delete("entity");
    return u.pathname + u.search + u.hash;
  }
  function select(id, how) {
    var li = item(id) || item(fallback);
    if (!li) return;
    id = li.getAttribute("data-entity");
    items().forEach(function (x) { x.setAttribute("aria-selected", x === li ? "true" : "false"); });
    for (var up = parentOf(li); up; up = parentOf(up)) fold(up, true);
    var pane = panes.filter(function (p) { return p.getAttribute("data-entity") === id; })[0];
    if (pane) {
      var kind = pane.getAttribute("data-entity-kind") || "";
      panes.forEach(function (p) { if (p === pane) p.hidden = false; else if (!p.hidden) { pause(p); p.hidden = true; } });
      if (kind !== "station") pause(document.querySelector(".panels"));
      document.body.setAttribute("data-entity", id);
      document.body.setAttribute("data-entity-kind", kind);
    }
    if (how === "push" || how === "replace") {
      var next = hrefFor(id);
      if (next !== location.pathname + location.search + location.hash) history[how === "push" ? "pushState" : "replaceState"](history.state, "", next);
    }
    if (how === "push" && pane) {
      // the picked level's top in view: the right pane scrolls on its own beside the tree (two panes), the page on a phone
      var right = document.getElementById("pane");
      if (right && right.scrollHeight > right.clientHeight && getComputedStyle(right).overflowY !== "visible") right.scrollTop = 0;
      else pane.scrollIntoView({ block: "start" });
    }
  }
  function fromUrl() { return new URLSearchParams(location.search).get("entity") || fallback; }
  select(fromUrl(), "none");
  addEventListener("popstate", function () { select(fromUrl(), "none"); });
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest && ev.target.closest('a[href^="?entity="]');
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var id = new URLSearchParams(a.getAttribute("href").slice(1)).get("entity");
    if (!item(id)) return;
    ev.preventDefault();
    select(id, "push");
  });

  // ---- the keyboard (WAI-ARIA tree view: ↑ ↓ move, → opens or steps in, ← folds or steps out, Home / End) -----------------------
  list.addEventListener("keydown", function (ev) {
    var li = ev.target.closest("[role=treeitem]");
    if (!li) return;
    var shown = items().filter(rowShown);
    var at = shown.indexOf(li);
    var go = function (x) { if (x) { var a = x.querySelector(":scope > .s2r-etree-row a"); if (a) a.focus(); ev.preventDefault(); } };
    if (ev.key === "ArrowDown") go(shown[at + 1]);
    else if (ev.key === "ArrowUp") go(shown[at - 1]);
    else if (ev.key === "Home") go(shown[0]);
    else if (ev.key === "End") go(shown[shown.length - 1]);
    else if (ev.key === "ArrowRight") {
      if (foldable(li) && li.getAttribute("aria-expanded") === "false") { fold(li, true); save(); ev.preventDefault(); } else if (foldable(li)) go(shown[at + 1]);
    } else if (ev.key === "ArrowLeft") {
      if (foldable(li) && li.getAttribute("aria-expanded") === "true") { fold(li, false); save(); ev.preventDefault(); } else go(parentOf(li));
    }
  });
})();
