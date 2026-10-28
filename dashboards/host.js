// The host for one <data-dashboard>: which proposal x scale to show, from ?proposal=&scale=, else the reviewer's last
// choice (localStorage), else the build's default (the recommended pick). Switching reloads the page clean.
// WHY a reload instead of swapping the element: each dashboard owns the URL's rails, hash selections and its clock;
// a fresh page is the one state that can never leak from the previous proposal into the next.
import '../vendor/data-ui/dist/data-ui.js';
import '../vendor/data-ui/dist/dashboard.js';

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
// WHY created here with its src already set: <data-dashboard> loads on connect; a src set after an upgrade is ignored
const dash = document.createElement('data-dashboard');
dash.id = 'dash';
dash.setAttribute('aria-label', `${proposal.title} · ${scale.short}`);
dash.setAttribute('src', src);
document.getElementById('page').append(dash);

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
