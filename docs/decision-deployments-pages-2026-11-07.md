# Decision: every node of every deployment's tree has its page at /deployments/<node id>/, beside the record pages

- **Date:** 2026-11-07. **Status:** accepted on merge (the deployments lane, `claude/w2a-deployments`): `site/deployments_pages.py`,
  `site/ui_shared.py` (landed first, alone, for the run-page lane), `static/deployments.css`, `static/ui-shared.css`. Decided for Zach by the
  lane; his to overrule.
- **Asked by:** Zach, `PROJECT - Sim2Real`, 2026-11-06: "Ok I like organizing this around Deployments. The orcale examples are also
  deployments its just they are 'Virtual' ... Ok now when I click a deployment... I will see the deployment page ... Each sub componet of
  the deployment could basically be its own deployment (in fact it almost is) ... the first level of filtering I think is for the type of
  dpeloyment ... deployments tagged with orcale example. Or perhaps only deployments that use a camera". Built on the frozen contract,
  `type_cards/CONTRACT.md` "Domain model v3" (`docs/decision-domain-model-v3-2026-11-07.md`).

## What was decided

1. **The index** (`/deployments/`) is the workbench's two panes: the left column is data-ui's rail (Kind, then Tags), the results a data-ui
   `<data-views>` of the contract's deployments (`parent == null`), cards first (each its MuJoCo render from the media index, the kind as
   a badge: physical blue, virtual orange, the site's real and sim colours; tags muted), the same rows as a table second. Its rows are the
   site's `data/deployment-cards.json` (data-ui's runtime shape), written beside `search.json`.
2. **A page for every node** at `/deployments/<node id>/` (the contract's path ids are the URL's path): its whole tree in the left column
   (`ui_shared.entity_tree`: the first two levels and the path to it open, itself current), then one calm answer (a deployment's render
   beside it; a station's link in 3D under it, the media lane's `joint-3d` component on its newest replayed run), its sub-deployments, its
   coverage and pinned metrics over all of its runs, the models per entity type, its runs, and links to its other pages.
3. **The record pages stay**: `/one-dof-test-rack/` (gates, why it fails, coverage plots, evidence), each station's page and each oracle
   example's `/sysid/<id>/` keep their tabs and links; each now links its deployment page, and back.
4. **Numbers**: a node's runs are the contract's (the runs whose device is under it; none kept for a virtual node; unknown for a camera),
   and every metric and coverage figure is `sel.compute` over exactly those run ids (memoised per run set: a station and its parts share
   one). A fidelity metric's headline is the model that replayed the most of the runs, then by name: never a label the page singles out,
   never the best value.
5. **Models per entity type**: the type's current model on its ladder (domain v3), and the ones used here: on a virtual deployment
   sysid's fit (its highest rung with an identified parameter, or the selection rule's pick, with the v2 rung named), on a physical one the
   producer's models that replayed its runs, by their own labels (no map from a twin's label to a ladder model exists; none is guessed).

## Criteria, and how the options scored

| criterion (weight) | **/deployments/<id>/ beside the record pages (chosen)** | fold the record page into the v3 page | a v3 tab on each record page |
|---|---|---|---|
| Zach's asks met now: kind and tags on the left, renders, every part openable, runs, models, pinned metrics, coverage (high) | yes | yes | no: adapters, parts, cameras and virtual nodes have no record page |
| nothing that works breaks: the record pages' tabs, their links (#gates, ?node_1= picks, the home's tile) and the site test (high) | yes | no: every link and check of the record page moves | yes |
| one source per number: sel.compute over the contract's runs, no new number (high) | yes | yes | yes |
| reuse: the workbench's panes, data-ui's rail, cards and tables, the media index (medium) | yes | yes | partly: the record frame has no left column |
| calm: one answer first, detail on demand (medium) | yes | yes | no: the answer sits behind a tab |

The cost of the choice: a physical deployment has two pages (its v3 page and its record page), linked both ways.

## What would change this

- Zach wants one page per deployment: the record page's tabs become sections of the v3 page and `/<dep>/` redirects; its own lane, since
  every link and check of the record page moves.
- A producer writes per-run values for the parts' metrics (motor, gearbox, driver, encoder): their "no value yet" lines become tables
  with no page change.
- A map from a producer's twin labels to ladder model ids: "used here" on a physical deployment can name the rung.

## Undo

`git revert` the lane's merge commit: `site/build.py` writes `/deployments/` from `pages.deployments_body` again (kept in `site/pages.py`),
and the record and oracle pages lose their one link each. `site/ui_shared.py` landed on its own (8dbb098) and stays unless reverted apart.
