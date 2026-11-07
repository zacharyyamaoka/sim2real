# Decision: the media are build outputs served at /media/, and the site shows them as components scoped to an entity

- **Date:** 2026-11-07. **Status:** accepted (landed on `main` with the media lane).
- **Asked by:** Zach, 2026-11-07: "I would like the runs to be a bit more media rich ... video data saved so I could quickly see it ... we
  can basically always have a 3D view ... in these cards I was hoping to see an image of the actual deployment." The coordinator, the same
  day, for the run page's next redesign (an entity tree on the left, the selected level's dashboard on the right): "build your 3D view,
  the video and the 'what you're looking at' text as components scoped to an entity (a joint, a camera, an arm) ... Don't hard-wire them
  into one flat page."

## What was decided

1. **Media are build outputs, never git.** `tools/build_media.py` (bam_rack_twin's venv: MuJoCo, OpenCV, ffmpeg) writes renders, link
   models, link poses and clips into `~/.cache/sim2real/media`; `site/build.py` links it at `/media/`; the desktop app's channels proxy
   `/media/` to a process over that folder, as they do the run data. 385 MB today; the repo holds only the builder.
2. **Components are scoped to an entity.** `site/components.py`: `joint_3d`, `camera_clip` and `joint_render` are data-ui `.base`
   fragments whose every dataset is a run's and filtered to its entity (`{station}` / `{device}` for a joint, `{camera}` for a camera);
   `what_joint` / `what_camera` are the words. `compose()` drops one into a page; `views/components/<name>.base` is the same component
   as a dashboard of its own (its own clock over its entity's samples), its entity in the URL's query. The run page is composed of the
   same views; `/components/` mounts each alone for a real entity.
3. **The camera and the render sit side by side, never overlaid.** The render is the joint's own frame, not the camera's calibrated
   pinhole (the as-built camera poses are valid only before 2026-10-21 18:00), so an onion or a wipe would lay unregistered pictures on
   each other.

## Criteria, and how the options scored

| criterion (weight) | cache + components (chosen) | media in git | one flat run page |
|---|---|---|---|
| git stays small (high) | yes: only the builder | no: ~0.4 GB and growing per run | either |
| a page per entity level can reuse it (high: the next redesign) | yes: fragments + standalone `.base` | either | no: the next lane re-cuts the page |
| one source of truth for each view (medium) | yes: the run page is composed of the components' own views (the site test compares them) | either | copies drift |
| the site still builds without the media (medium) | yes: no render, robot or clip, every page as before | yes | either |

## Consequences

- A new run gets its link poses and, where its session filmed it, its clips the next time `tools/build_media.py` runs (only what changed).
- An arm is `joint_3d` with its links (the GLB's nodes, the links table's `<link>_` columns) once a producer writes them; a new entity kind
  is a new fragment with its own entity filter, checked by `site/tests/test_site_flow.py`'s `component_checks`.
- Undo: revert the media lane's commits; the site builds as before.
