// The host for one <data-dashboard>: which proposal x scale to show, from ?proposal=&scale=, else the reviewer's last
// choice (localStorage), else the build's default (the recommended pick). Switching reloads the page clean.
// WHY a reload instead of swapping the element: each dashboard owns the URL's rails, hash selections and its clock;
// a fresh page is the one state that can never leak from the previous proposal into the next.
import { resolveTokens, toRgb } from '../vendor/data-ui/dist/data-ui.js';
import '../vendor/data-ui/dist/dashboard.js';

// Zach (2026-10-28): "We want to train the eye to know what is real and what is sim. Blue and orange ... leaves green
// and red for elsewhere." Real is data-ui's series slot 1 (blue), sim is slot 2 (orange); green and red are pass/fail only.
// WHY the host resolves the palette: a .base's `style.palette` takes colours, and three.js (the 3D card) cannot read var().
// The build writes slot tokens (`var(--data-series-1)`, so no hex of ours has to pass data-ui's contrast checks in two
// themes); the host swaps in the colours data-ui resolved for the theme on screen and redraws when the theme changes.
const SLOT = /var\(--(data-series-\d)\)/g;
const MIX = /color-mix\((?:[^()]|\([^()]*\))*\)/g;
const nativeFetch = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const response = await nativeFetch(input, init);
  const url = typeof input === 'string' ? input : (input instanceof URL ? input.href : input.url);
  if (!response.ok || !/\.base(?:[?#]|$)/.test(url)) return response;
  const slots = resolveTokens(document.getElementById('dash')).css;
  const text = (await response.text()).replace(SLOT, (_match, name) => slots[name]).replace(MIX, (mix) => toRgb(mix));
  return new Response(text, { status: response.status, statusText: response.statusText, headers: response.headers });
};

const STORE = 'sim2real/switcher';
const manifest = await (await fetch('proposals.json', { cache: 'no-store' })).json();
const params = new URLSearchParams(location.search);
let remembered = {};
try { remembered = JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch { remembered = {}; }
const known = (list, id) => list.some((x) => x.id === id);
const proposalId = [params.get('proposal'), remembered.proposal, manifest.default.proposal].find((id) => id && known(manifest.proposals, id));
const scaleId = [params.get('scale'), remembered.scale, manifest.default.scale].find((id) => id && known(manifest.scales, id));
const proposal = manifest.proposals.find((x) => x.id === proposalId);
const scale = manifest.scales.find((x) => x.id === scaleId);
try { localStorage.setItem(STORE, JSON.stringify({ proposal: proposal.id, scale: scale.id })); } catch { /* private window: no memory */ }
// WHY the URL always names its proposal and scale: a bare URL resolves through localStorage, so after a click-through
// the browser's Back would land on the last choice (Type catalog) instead of the page the reviewer left
if (params.get('proposal') !== proposal.id || params.get('scale') !== scale.id) {
  params.set('proposal', proposal.id);
  params.set('scale', scale.id);
  history.replaceState(history.state, '', `${location.pathname}?${params.toString()}${location.hash}`);
}

const src = `${scale.id}/${proposal.id}.base`;
document.title = `${proposal.title} · ${scale.short} · sim2real`;
document.getElementById('proposal-title').textContent = `${proposal.title}`;
document.getElementById('proposal-axis').textContent = `Axis: ${proposal.axis}. Answers: ${proposal.question}`;
const chip = document.getElementById('scale-chip');
chip.textContent = scale.basis === 'real' ? `${scale.short} · real data` : `${scale.short} · SIM STAND-IN`;
chip.dataset.basis = scale.basis;
document.getElementById('base-link').href = src;

// The run inspector starts on the first run of its tree (a table selection lives in the hash: s.<panel>=<prop>:<value>)
const hash = new URLSearchParams(location.hash.slice(1));
if (proposal.id === '4-run-inspector' && !hash.has('s.runs') && manifest.first_run[scale.id]) {
  hash.set('s.runs', `run:${encodeURIComponent(manifest.first_run[scale.id])}`);
  history.replaceState(history.state, '', `${location.pathname}${location.search}#${hash.toString()}`);
}
const dash = document.createElement('data-dashboard');
dash.id = 'dash';
dash.setAttribute('aria-label', `${proposal.title} · ${scale.short}`);
document.getElementById('page').append(dash);
dash.setAttribute('src', src);  // set after connecting: data-ui reloads on a src change since dd53748 (PEP 0010 P0 #13)
// the system scheme or the page's own theme switch: re-read the .base so its palette is resolved again (rails, selections and the clock stay)
const redraw = () => dash.reload();
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redraw);
new MutationObserver(redraw).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class'] });

// Click-through: a device's badge on Visual home opens its type's block on Type catalog, same scale, device selected.
// WHY in the host and not a `select:` in the .base: a selection filters every panel reading `devices`, which would empty
// the other types' badges and the gauge; the click only has to move the reviewer, and the Type catalog's own device rail
// (`?<type>.device=`) is the page's real selection for the types that have one.
const FROM = 'from';
const FOCUS = 'focus';
const HOME = manifest.default.proposal;
const TARGET = '2-type-catalog';
const through = manifest.click_through[scale.id];
function typeCatalogUrl(device) {
  const next = new URLSearchParams({ proposal: TARGET, scale: scale.id, [FROM]: proposal.id, [FOCUS]: device });
  // the dashboard writes a rail value percent-encoded inside the query value, so write it the same way it reads it
  if (through.rails.includes(through.devices[device])) next.set(`${through.devices[device]}.device`, encodeURIComponent(device));
  return `${location.pathname}?${next.toString()}`;
}
function badgeDevice(target) {
  const card = target instanceof Element ? target.closest('.dv-kpi-card') : null;
  const label = card?.querySelector('.dv-kpi-label')?.textContent?.trim();
  return card && label && Object.hasOwn(through.devices, label) ? { card, device: label } : null;
}
if (proposal.id === HOME) {
  const dashEl = document.getElementById('dash');
  // capture phase: the click leaves the page before data-ui's own handlers see it
  dashEl.addEventListener('click', (event) => {
    const hit = badgeDevice(event.target);
    if (!hit || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) return;
    event.preventDefault();
    event.stopPropagation();
    try { localStorage.setItem(STORE, JSON.stringify({ proposal: TARGET, scale: scale.id })); } catch { /* still navigates */ }
    location.assign(typeCatalogUrl(hit.device));
  }, true);
  dashEl.addEventListener('keydown', (event) => {
    const hit = (event.key === 'Enter' || event.key === ' ') ? badgeDevice(event.target) : null;
    if (hit) { event.preventDefault(); hit.card.click(); }
  });
  // cards are redrawn by data-ui, so every redraw is decorated again (idempotent)
  const decorate = () => {
    for (const card of dashEl.querySelectorAll('.dv-kpi-card')) {
      const hit = badgeDevice(card.querySelector('.dv-kpi-label'));
      if (!hit || card.dataset.s2rLink) continue;
      card.dataset.s2rLink = hit.device;
      card.tabIndex = 0;
      card.setAttribute('role', 'link');
      card.title = `Open ${hit.device} in the Type catalog`;
    }
  };
  new MutationObserver(decorate).observe(dashEl, { childList: true, subtree: true });
}

// The way back, and the arrival: the Type catalog opened from Visual home shows a "← Visual home" link, marks the chosen
// device's badge and scrolls its type's block into view.
const fromProposal = manifest.proposals.find((x) => x.id === params.get(FROM));
if (fromProposal && fromProposal.id !== proposal.id) {
  const back = document.getElementById('back-link');
  back.href = `${location.pathname}?proposal=${encodeURIComponent(fromProposal.id)}&scale=${encodeURIComponent(scale.id)}`;
  back.textContent = `← ${fromProposal.title}`;
  back.hidden = false;
}
const focus = params.get(FOCUS);
if (proposal.id === TARGET && focus && Object.hasOwn(through.devices, focus)) {
  const dashEl = document.getElementById('dash');
  const heading = through.blocks[through.devices[focus]];
  let settled = false;
  let userScrolled = false;
  for (const kind of ['wheel', 'touchmove', 'keydown', 'pointerdown']) addEventListener(kind, () => { userScrolled = true; }, { passive: true, once: true });
  const mark = () => {
    const card = [...dashEl.querySelectorAll('.dv-kpi-label')].find((x) => x.textContent.trim() === focus)?.closest('.dv-kpi-card');
    if (card && !card.dataset.s2rFocus) {
      for (const old of dashEl.querySelectorAll('[data-s2r-focus]')) delete old.dataset.s2rFocus;
      card.dataset.s2rFocus = focus;
      card.setAttribute('aria-current', 'true');
    }
    const block = [...dashEl.querySelectorAll('.dd-panel-text h4')].find((x) => x.textContent.trim() === heading)?.closest('.dd-panel');
    if (card && block && !settled) {
      settled = true;
      block.style.scrollMarginTop = '72px';
      block.scrollIntoView({ block: 'start' });
      // the panels below keep loading (3D, video): once more after the page has settled, unless the reviewer has moved
      setTimeout(() => { if (!userScrolled) block.scrollIntoView({ block: 'start' }); }, 700);
    }
  };
  new MutationObserver(mark).observe(dashEl, { childList: true, subtree: true });
  mark();
}

function fill(select, list, current, label) {
  for (const item of list) {
    const option = document.createElement('option');
    option.value = item.id;
    option.textContent = label(item);
    option.selected = item.id === current;
    select.append(option);
  }
}
const pickProposal = document.getElementById('pick-proposal');
const pickScale = document.getElementById('pick-scale');
fill(pickProposal, manifest.proposals, proposal.id, (p) => `${p.id.split('-')[0]}. ${p.title}${p.id === manifest.default.proposal ? ' (pick)' : ''}`);
fill(pickScale, manifest.scales, scale.id, (s) => `${s.short}${s.basis === 'real' ? '' : ' · stand-in'}`);
function go() {
  const next = { proposal: pickProposal.value, scale: pickScale.value };
  try { localStorage.setItem(STORE, JSON.stringify(next)); } catch { /* still navigates */ }
  location.assign(`${location.pathname}?proposal=${encodeURIComponent(next.proposal)}&scale=${encodeURIComponent(next.scale)}`);
}
pickProposal.addEventListener('change', go);
pickScale.addEventListener('change', go);
