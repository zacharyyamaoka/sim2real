# three.js 0.186.1 + OrbitControls, one IIFE bundle

`three-orbit-0.186.1.min.js` sets `window.THREE` and `window.OrbitControls`. It is inlined into the gripper gallery
page (`docs/build_report_gripper_gallery.py`) so the page works offline from file://.

Built 2026-11-11 with esbuild from data-ui's `node_modules/three` (0.186.1, MIT):

    entry.js:  import * as THREE from 'three'; import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
               window.THREE = THREE; window.OrbitControls = OrbitControls;
    NODE_PATH=/home/bam/data-ui/node_modules /home/bam/data-ui/node_modules/.bin/esbuild entry.js --bundle --minify --format=iife --outfile=three-orbit-0.186.1.min.js
