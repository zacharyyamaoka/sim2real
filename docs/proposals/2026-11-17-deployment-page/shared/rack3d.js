/* The rack in 3D, shared by all five proposals (three.js 0.186.1 + OrbitControls, sim2real's vendored bundle).
   WHY schematic geometry, labelled as such: the house viewer is viser (live server), too heavy to run five times for a
   proposal round; this scene is drawn from the fixture's station facts (each station's tip length, motor family and load,
   real), with the plates laid out schematically. The real CAD is one click away: "CAD render" shows the MuJoCo render of the
   rack's cad2robot payload (sim2real tools/build_media.py). House taste kept: inline, no logo, a Fusion-style ViewCube.
   Every part is a mesh carrying its typed-tree node id, so a click in 3D selects the same node the tree does. */
(function () {
  "use strict";
  var S2R = window.S2R;
  var THREE = window.THREE;
  var STATIONS = {
    can11: { x: -0.44, y: 0.58, family: "JMC", link: "arm", plate: "a" },
    can12: { x: -0.03, y: 0.47, family: "JMC", link: "hub", plate: "b" },
    can13: { x: 0.07, y: 0.25, family: "JMC", link: "bar", plate: "b" },
    can1: { x: 0.36, y: 0.47, family: "GIM", link: "disc", plate: "c" },
    can14: { x: 0.36, y: 0.25, family: "GIM", link: "disc", plate: "c" },
    can15: { x: 0.50, y: 0.47, family: "GIM", link: "oval", plate: "c" },
  };
  var PLATES = { a: { x: -0.44, w: 0.2, h: 0.66, y: 0.37 }, b: { x: 0.02, w: 0.26, h: 0.5, y: 0.31 }, c: { x: 0.43, w: 0.28, h: 0.5, y: 0.31 } };
  var STATUS_HEX = { pass: 0x4cc06e, fail: 0xf2685c, watch: 0xf0a548, none: 0x8a8d96, not_observable: 0x8a8d96, not_run: 0x8a8d96, observed: 0x8a8d96 };

  function css(name, fallback) { var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim(); return v || fallback; }

  S2R.Rack3D = function (host, opts) {
    opts = opts || {};
    var self = this;
    host.classList.add("scene");
    if (!THREE) { host.innerHTML = '<p class="muted" style="padding:16px">3D needs three.js (vendor/three).</p>'; return; }
    var renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(renderer.domElement);
    var scene = new THREE.Scene();
    var camera = new THREE.PerspectiveCamera(35, 1, 0.01, 20);
    var HOME = { pos: new THREE.Vector3(0.62, 0.78, 1.55), target: new THREE.Vector3(0.0, 0.34, 0.0) };
    camera.position.copy(HOME.pos);
    var controls = new window.OrbitControls(camera, renderer.domElement);
    controls.target.copy(HOME.target);
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.minDistance = 0.18;
    controls.maxDistance = 4;
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8d96, 1.6));
    var sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(1.2, 2.2, 1.6);
    scene.add(sun);
    var grid = new THREE.GridHelper(2.4, 24, 0x7f838c, 0x5a5e66);
    grid.material.opacity = 0.35; grid.material.transparent = true;
    scene.add(grid);

    var M = function (hex, rough, metal) { return new THREE.MeshStandardMaterial({ color: hex, roughness: rough == null ? 0.55 : rough, metalness: metal == null ? 0.2 : metal }); };
    var meshes = [];          // every pickable mesh
    var parts = {};           // node id -> [meshes]
    var stationGroups = {};   // station id -> { group, swing, ring, anchor, partsGroup }
    function tag(mesh, nodeId, station) {
      mesh.userData.nodeId = nodeId; mesh.userData.station = station;
      meshes.push(mesh); (parts[nodeId] = parts[nodeId] || []).push(mesh);
      mesh.userData.baseColor = mesh.material.color.getHex();
      return mesh;
    }
    Object.keys(PLATES).forEach(function (k) {
      var p = PLATES[k];
      var plate = new THREE.Mesh(new THREE.BoxGeometry(p.w, p.h, 0.008), M(0xc3c7ce, 0.45, 0.35));
      plate.position.set(p.x, p.y, 0);
      scene.add(plate);
      var foot = new THREE.Mesh(new THREE.BoxGeometry(p.w, 0.012, 0.12), M(0xa9aeb6, 0.5, 0.3));
      foot.position.set(p.x, 0.006, 0);
      scene.add(foot);
    });
    function cyl(r, len, mat) { var g = new THREE.CylinderGeometry(r, r, len, 40); g.rotateX(Math.PI / 2); return new THREE.Mesh(g, mat); }

    Object.keys(STATIONS).forEach(function (sid) {
      var s = STATIONS[sid], node = S2R.node(sid), tip = node.tip_length_m;
      var g = new THREE.Group(); g.position.set(s.x, s.y, 0); scene.add(g);
      var back = new THREE.Group(); g.add(back);   // the servo: behind the plate
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
      [[gearbox, "/servo/gearbox"], [motor, "/servo/motor"], [encoder, "/servo/encoder"], [driver, "/servo/driver"]].forEach(function (pair) {
        pair[0].userData.home = pair[0].position.z; back.add(tag(pair[0], sid + pair[1], sid));
      });
      // the output: a swing group in front of the plate (rotation about the joint axis, z)
      var swing = new THREE.Group(); swing.position.z = 0.012; g.add(swing);
      var shaft = cyl(0.008, 0.016, M(0xd7dae0, 0.3, 0.8)); shaft.position.z = 0.0; swing.add(tag(shaft, sid + "/servo", sid));
      var linkMat = M(0xb7bcc5, 0.4, 0.55), link;
      if (s.link === "arm") {
        link = new THREE.Mesh(new THREE.BoxGeometry(0.036, tip + 0.03, 0.012), linkMat); link.position.set(0, -tip / 2 + 0.01, 0.012);
        var mass = new THREE.Mesh(new THREE.BoxGeometry(0.06, 0.05, 0.03), M(0x8d939d, 0.5, 0.5)); mass.position.set(0, -tip + 0.04, 0.02);
        swing.add(tag(mass, sid + "/link", sid));
      } else if (s.link === "oval") {
        link = new THREE.Mesh(new THREE.CapsuleGeometry(0.018, tip, 6, 18), linkMat); link.position.set(0, -tip / 2, 0.01);
        var m2 = cyl(0.02, 0.03, M(0x24262c, 0.5, 0.35)); m2.position.set(0, -tip, 0.03); swing.add(tag(m2, sid + "/link", sid));
      } else if (s.link === "bar") {
        link = new THREE.Mesh(new THREE.BoxGeometry(0.02, tip * 2, 0.005), linkMat); link.position.set(0, 0, 0.01);
      } else {
        link = cyl(tip, 0.005, linkMat); link.position.z = 0.01;
        if (s.link === "disc") {
          var tg = new THREE.Mesh(new THREE.PlaneGeometry(tip * 0.9, tip * 0.9), new THREE.MeshBasicMaterial({ color: 0xffffff }));
          tg.position.set(0, 0, 0.0131); swing.add(tg);
          var inner = new THREE.Mesh(new THREE.PlaneGeometry(tip * 0.5, tip * 0.5), new THREE.MeshBasicMaterial({ color: 0x111111 }));
          inner.position.set(0.002, -0.002, 0.0133); swing.add(inner);
        }
      }
      swing.add(tag(link, sid + "/link", sid));
      var tipBall = new THREE.Mesh(new THREE.SphereGeometry(0.006, 16, 12), M(0xd95926, 0.4, 0.1));
      tipBall.position.set(0, s.link === "disc" || s.link === "hub" ? tip : -tip, 0.022); swing.add(tipBall);
      // the status ring at the output: its colour is the station's verdict in the round shown
      var ring = new THREE.Mesh(new THREE.TorusGeometry(s.link === "arm" || s.link === "oval" ? 0.034 : tip + 0.012, 0.0035, 10, 64), new THREE.MeshBasicMaterial({ color: STATUS_HEX.none }));
      ring.position.z = 0.006; g.add(ring);
      var hit = new THREE.Mesh(new THREE.CylinderGeometry(0.075, 0.075, 0.3, 12), new THREE.MeshBasicMaterial({ visible: false }));
      hit.rotation.x = Math.PI / 2; hit.position.z = -0.05; g.add(tag(hit, sid, sid));
      var anchor = new THREE.Vector3(s.x, s.y + Math.max(tip, 0.03) + 0.05, 0.02);
      if (s.link === "arm" || s.link === "oval") anchor.set(s.x, s.y + 0.07, 0.02);
      stationGroups[sid] = { group: g, swing: swing, back: back, ring: ring, anchor: anchor, rest: 0, link: s.link };
    });

    // ---- overlays: chips, labels, the CAD render, the ViewCube -----------------------------------------------------------
    var chips = document.createElement("div"); chips.className = "s-chips";
    chips.innerHTML = '<span class="chip sim" title="Drawn from each station\'s tip length, motor family and load; plate layout schematic">schematic geometry · simulated</span>' +
      (opts.cadToggle === false ? "" : '<button class="btn" data-cad aria-pressed="false" title="The MuJoCo render of the rack\'s cad2robot payload">CAD render</button>');
    host.appendChild(chips);
    var img = document.createElement("div"); img.className = "s-img"; img.hidden = true;
    img.style.backgroundImage = "url(" + S2R.media("media/one-dof-test-rack-full.jpg") + ")";
    host.appendChild(img);
    var cap = document.createElement("div"); cap.className = "s-cap"; cap.textContent = "drag to orbit · scroll to zoom · click a station or a part";
    host.appendChild(cap);
    var cadBtn = chips.querySelector("[data-cad]");
    if (cadBtn) cadBtn.addEventListener("click", function () {
      var on = img.hidden; img.hidden = !on; cadBtn.setAttribute("aria-pressed", String(on));
      cadBtn.textContent = on ? "Back to 3D" : "CAD render";
      cap.textContent = on ? "MuJoCo 3.11 render of the rack's cad2robot payload (sim2real media cache), a still" : "drag to orbit · scroll to zoom · click a station or a part";
    });
    var labelLayer = document.createElement("div"); labelLayer.style.cssText = "position:absolute;inset:0;pointer-events:none;z-index:2";
    host.appendChild(labelLayer);
    var labels = {};
    Object.keys(STATIONS).forEach(function (sid) {
      var el = document.createElement("div"); el.className = "s-label"; el.style.pointerEvents = "auto"; el.dataset.id = sid;
      el.addEventListener("click", function (ev) { ev.stopPropagation(); if (opts.onPick) opts.onPick(sid); });
      labelLayer.appendChild(el); labels[sid] = el;
    });
    var cube = document.createElement("div"); cube.className = "viewcube";
    cube.innerHTML = '<div class="cube">' + [["front", "FRONT", "translateZ(26px)", [0, 0, 1]], ["back", "BACK", "rotateY(180deg) translateZ(26px)", [0, 0, -1]],
      ["right", "RIGHT", "rotateY(90deg) translateZ(26px)", [1, 0, 0]], ["left", "LEFT", "rotateY(-90deg) translateZ(26px)", [-1, 0, 0]],
      ["top", "TOP", "rotateX(90deg) translateZ(26px)", [0, 1, 0.0001]], ["bottom", "BOTTOM", "rotateX(-90deg) translateZ(26px)", [0, -1, 0.0001]]].map(function (f) {
        return '<div class="face" data-dir="' + f[3].join(",") + '" style="transform:' + f[2] + '" title="View from ' + f[1].toLowerCase() + '">' + f[1] + "</div>";
      }).join("") + "</div>";
    host.appendChild(cube);
    var cubeInner = cube.querySelector(".cube");
    cube.addEventListener("click", function (ev) {
      var f = ev.target.closest(".face"); if (!f) return;
      var d = f.dataset.dir.split(",").map(Number), dist = camera.position.distanceTo(controls.target);
      tweenTo(controls.target.clone().add(new THREE.Vector3(d[0], d[1], d[2]).normalize().multiplyScalar(dist)), controls.target.clone());
    });

    // ---- state ---------------------------------------------------------------------------------------------------------
    var selected = null, rid = opts.round || "r8", exploded = null, tween = null, dirty = true, t0 = performance.now();
    function statusOf(id) { return opts.status ? opts.status(id, rid) : (S2R.node(id).verdict[rid].status); }
    function paint() {
      Object.keys(stationGroups).forEach(function (sid) {
        var st = statusOf(sid);
        stationGroups[sid].ring.material.color.setHex(STATUS_HEX[st] || STATUS_HEX.none);
        stationGroups[sid].ring.scale.setScalar(sid === selectedStation() ? 1.18 : 1);
      });
      meshes.forEach(function (m) {
        var on = selected && (m.userData.nodeId === selected || (selected === m.userData.station && m.userData.nodeId !== m.userData.station) || m.userData.nodeId.indexOf(selected + "/") === 0);
        if (m.material.emissive) m.material.emissive.setHex(on ? 0x2a3b55 : 0x000000);
        if (opts.partTint && exploded && m.userData.station === exploded && m.material.color && m.userData.nodeId !== exploded) {
          var st = S2R.node(m.userData.nodeId) ? statusOf(m.userData.nodeId) : "none";
          if (st === "fail" || st === "watch") m.material.emissive.setHex(st === "fail" ? 0x5a1410 : 0x4a3008);
        }
      });
      Object.keys(labels).forEach(function (sid) {
        var el = labels[sid], show = opts.labels === "all" || (opts.labels === "selected" && sid === selectedStation());
        el.hidden = !show || !img.hidden;
        if (show) { el.innerHTML = opts.label ? opts.label(sid, rid) : S2R.dot(statusOf(sid)) + S2R.esc(S2R.node(sid).short); el.classList.toggle("sel", sid === selectedStation()); }
      });
      dirty = true;
    }
    function selectedStation() { var st = selected ? S2R.stationOf(selected) : null; return st ? st.id : null; }
    function tweenTo(pos, target, ms) {
      tween = { from: camera.position.clone(), to: pos, tfrom: controls.target.clone(), tto: target, t: performance.now(), ms: ms || 450 };
    }
    self.select = function (id, focus) {
      selected = id;
      var sid = selectedStation();
      if (focus && sid) {
        var s = STATIONS[sid], st = stationGroups[sid];
        var tip = S2R.node(sid).tip_length_m, cy = st.link === "arm" ? s.y - 0.16 : st.link === "oval" ? s.y - 0.05 : s.y;
        var target = new THREE.Vector3(s.x, cy, 0), dist = st.link === "arm" ? 1.25 : 0.75;
        var dir = camera.position.clone().sub(controls.target).normalize();
        if (exploded === sid) { target.set(s.x, s.y, -0.14); dist = 0.75; dir = new THREE.Vector3(0.85, 0.3, 0.45).normalize(); }
        tweenTo(target.clone().add(dir.multiplyScalar(dist)), target);
      } else if (focus && !sid) tweenTo(HOME.pos.clone(), HOME.target.clone());
      paint();
    };
    self.setRound = function (r) { rid = r; paint(); };
    self.home = function () { tweenTo(HOME.pos.clone(), HOME.target.clone()); };
    self.explode = function (sid) {
      exploded = sid || null;
      Object.keys(stationGroups).forEach(function (k) {
        stationGroups[k].back.children.forEach(function (m, i) {
          var target = m.userData.home - (exploded === k ? 0.05 * (i + 1) : 0);
          m.userData.goal = target;
        });
      });
      paint();
    };
    self.repaint = paint;
    self.canvas = renderer.domElement;

    // ---- picking ---------------------------------------------------------------------------------------------------------
    var ray = new THREE.Raycaster(), ptr = new THREE.Vector2(), down = null;
    renderer.domElement.addEventListener("pointerdown", function (e) { down = [e.clientX, e.clientY]; });
    renderer.domElement.addEventListener("pointerup", function (e) {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      var r = renderer.domElement.getBoundingClientRect();
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      var hits = ray.intersectObjects(meshes, false).filter(function (h) { return h.object.visible || h.object.userData.nodeId === h.object.userData.station; });
      var real = hits.filter(function (h) { return h.object.userData.nodeId !== h.object.userData.station; });
      var h = real[0] || hits[0];
      if (!h) return;
      var id = h.object.userData.nodeId;
      if (!opts.partPick || (opts.partPick === "exploded" && exploded !== h.object.userData.station)) id = h.object.userData.station;
      if (opts.onPick) opts.onPick(id);
    });
    controls.addEventListener("change", function () { dirty = true; });

    // ---- the loop: render when something moved; the picked station swings gently (a pendulum, at rest elsewhere) --------
    var v3 = new THREE.Vector3();
    function resize() {
      var w = host.clientWidth, h = host.clientHeight;
      if (!w || !h) return;
      renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); dirty = true;
    }
    if (window.ResizeObserver) new ResizeObserver(resize).observe(host);
    function bg() { var c = css("--scene-bg", "#111214"); scene.background = new THREE.Color(c); dirty = true; }
    bg();
    if (window.matchMedia) window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", bg);
    function frame(now) {
      requestAnimationFrame(frame);
      if (document.hidden || !host.isConnected || !host.offsetParent) return;
      if (tween) {
        var k = Math.min(1, (now - tween.t) / tween.ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        camera.position.lerpVectors(tween.from, tween.to, e); controls.target.lerpVectors(tween.tfrom, tween.tto, e);
        if (k >= 1) tween = null; dirty = true;
      }
      var sid = selectedStation();
      Object.keys(stationGroups).forEach(function (k) {
        var st = stationGroups[k], goal = opts.swing !== false && k === sid ? Math.sin((now - t0) / 1000 * 2.1) * 0.35 : 0;
        if (Math.abs(st.swing.rotation.z - goal) > 1e-4) { st.swing.rotation.z += (goal - st.swing.rotation.z) * (k === sid ? 1 : 0.15); dirty = true; }
        st.back.children.forEach(function (m) { if (m.userData.goal != null && Math.abs(m.position.z - m.userData.goal) > 1e-4) { m.position.z += (m.userData.goal - m.position.z) * 0.2; dirty = true; } });
      });
      controls.update();
      if (!dirty) return;
      dirty = false;
      renderer.render(scene, camera);
      var w = host.clientWidth, h = host.clientHeight;
      Object.keys(labels).forEach(function (k) {
        if (labels[k].hidden) return;
        v3.copy(stationGroups[k].anchor).project(camera);
        labels[k].style.left = ((v3.x + 1) / 2 * w) + "px"; labels[k].style.top = ((1 - v3.y) / 2 * h) + "px";
        labels[k].style.display = v3.z > 1 ? "none" : "";
      });
      // the ViewCube mirrors the camera: F·R·F, R the camera's world-to-view rotation, F flips y into CSS
      var e = camera.matrixWorldInverse.elements, f = [1, -1, 1], m = [];
      for (var j = 0; j < 3; j++) { for (var i = 0; i < 3; i++) m.push(e[j * 4 + i] * f[i] * f[j]); m.push(0); }
      cubeInner.style.transform = "translateZ(-26px) matrix3d(" + m.concat([0, 0, 0, 1]).join(",") + ")";
    }
    resize(); paint(); requestAnimationFrame(frame);
    self.resize = resize;
    // for the acceptance script: where a station's joint is on screen (client px), so a test can click the mesh itself
    self.screenOf = function (sid) {
      var s = STATIONS[sid], p = new THREE.Vector3(s.x, s.y, 0.02).project(camera), r = renderer.domElement.getBoundingClientRect();
      return { x: r.left + (p.x + 1) / 2 * r.width, y: r.top + (1 - p.y) / 2 * r.height };
    };
    (S2R._racks = S2R._racks || []).push(self);
  };
})();
