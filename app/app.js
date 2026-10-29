// The sim2real app host: deployments -> one deployment (runs + coverage) -> one run (playback), each a data-ui dashboard.
// Routes are query params so the static server needs nothing: /app/ · /app/?d=<deployment> · /app/?d=<deployment>&run=<run>,
// plus `layer=gates` for the gates layer. WHY the host owns routes and data-ui only draws: data-ui PEP 0010 §8 (navigation is
// split by owner: data-ui the parts, sim2real deployments -> runs -> run and the producers).
import { resolveTokens, toRgb } from '/vendor/data-ui/dist/data-ui.js';
import '/vendor/data-ui/dist/dashboard.js';

const SAFE = /^[\w.~-]+$/;  // a deployment id or run slug, never a path
const params = new URLSearchParams(location.search);
const dep = SAFE.test(params.get('d') || '') ? params.get('d') : null;
const run = dep && SAFE.test(params.get('run') || '') ? params.get('run') : null;
const gates = params.get('layer') === 'gates';
const level = run ? 'run' : dep ? 'deployment' : 'deployments';
const base = level === 'deployments' ? 'deployments.base' : `${level}${gates ? '-gates' : ''}.base`;

// Every .base this page loads is rewritten before data-ui reads it:
// 1. `{deployment}` and `{run}` in its data paths (WHY: data-ui has no per-run dataset template yet, PEP 0010 P3);
// 2. the colour slots: real is data-ui's series slot 1 (blue), every model slot 2 (orange), resolved for the theme on screen,
//    because Vega-Lite and the 3D card cannot read var() (the same hook as dashboards/host.js).
// Zach (2026-10-28): "train the eye to know what is real and what is sim. Blue and orange ... leaves green and red for elsewhere".
const SLOT = /var\(--(data-series-\d)\)/g;
const MIX = /color-mix\((?:[^()]|\([^()]*\))*\)/g;
// WHY hex: a resolved colour lands inside YAML flow mappings ({ value: ... }), where the commas of rgb(r, g, b) split the value
const hex = (css) => {
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?/.exec(toRgb(css) || css);
  if (!m) return css;
  const parts = [m[1], m[2], m[3]].map(Number);
  if (m[4] !== undefined && Number(m[4]) < 1) parts.push(Number(m[4]) * 255);
  return '#' + parts.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
};
// and a bare # starts a YAML comment, so an unquoted value gets quotes
const quoted = (value, before) => (before === "'" || before === '"' ? value : `'${value}'`);
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const response = await nativeFetch(input, init);
  const url = typeof input === 'string' ? input : (input instanceof URL ? input.href : input.url);
  if (!response.ok || !/\.base(?:[?#]|$)/.test(url)) return response;
  const slots = resolveTokens(document.getElementById('dash') || document.body).css;
  const text = (await response.text())
    .replaceAll('{deployment}', dep || '').replaceAll('{run}', run || '')
    .replace(MIX, (mix, at, all) => quoted(hex(mix.replace(SLOT, (_m, name) => slots[name])), all[at - 1]))
    .replace(SLOT, (_match, name, at, all) => quoted(hex(slots[name]), all[at - 1]));
  return new Response(text, { status: response.status, statusText: response.statusText, headers: response.headers });
};

async function json(path) {
  try {
    const response = await nativeFetch(path, { cache: 'no-store' });
    return response.ok ? await response.json() : null;
  } catch { return null; }
}

function link(text, href, current = false) {
  const a = document.createElement(current ? 'span' : 'a');
  if (!current) a.href = href;
  else a.setAttribute('aria-current', 'page');
  a.textContent = text;
  return a;
}

const crumbs = document.getElementById('crumbs');
const deployments = (await json('/app/data/deployments.json'))?.rows || [];
const depRow = deployments.find((row) => row.id === dep);
const runRow = run ? (await json(`/app/data/${dep}/runs/${run}/run.json`))?.rows?.[0] : null;
const trail = [link('Deployments', '/app/', level === 'deployments')];
if (dep) trail.push(link(depRow?.title || dep, `/app/?d=${encodeURIComponent(dep)}${gates ? '&layer=gates' : ''}`, level === 'deployment'));
if (run) trail.push(link(runRow ? `${runRow.device} · ${runRow.title}` : run, location.href, true));
for (const [i, part] of trail.entries()) {
  if (i) crumbs.append(Object.assign(document.createElement('span'), { className: 'sep', textContent: '›', ariaHidden: 'true' }));
  crumbs.append(part);
}
document.title = [run && runRow ? `${runRow.device} · ${runRow.title}` : null, depRow?.title, 'sim2real'].filter(Boolean).join(' · ');

const page = document.getElementById('page');
if (dep && !depRow) {
  page.innerHTML = '<p class="empty">No such deployment. Build the data with tools/build_app.py, or go back to <a href="/app/">Deployments</a>.</p>';
} else if (run && !runRow) {
  page.innerHTML = `<p class="empty">No such run in this deployment. <a href="/app/?d=${encodeURIComponent(dep)}">Back to its runs</a>.</p>`;
} else {
  // The gates layer: a second .base over the same data (playback + gate datasets and views); the switch swaps the file.
  // WHY a reload: a <data-dashboard> ignores a src set after it loaded (data-ui gap #13), and the rails and the clock live in
  // the URL, which the switch keeps.
  const toggle = document.getElementById('layer');
  if (level !== 'deployments') {
    toggle.hidden = false;
    toggle.setAttribute('aria-pressed', String(gates));
    toggle.addEventListener('click', () => {
      const next = new URLSearchParams(location.search);
      if (gates) next.delete('layer'); else next.set('layer', 'gates');
      location.assign(`${location.pathname}?${next.toString()}${location.hash}`);
    });
  }
  const dash = document.createElement('data-dashboard');
  dash.id = 'dash';
  dash.dataset.level = level;
  dash.dataset.layer = gates ? 'gates' : 'playback';
  dash.setAttribute('aria-label', document.title);
  dash.setAttribute('src', `/app/${base}`);  // WHY set before connecting: a src set after load is ignored
  page.append(dash);
  const redraw = () => dash.reload();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
  new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });
}
