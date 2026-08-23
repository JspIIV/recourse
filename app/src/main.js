// Recourse, the page.
//
// Open a job with a fee, deliver against it, accept or contest it, and watch the
// escrow empty toward whoever the round ruled for. Reading needs nothing; the
// four writes need a wallet, and opening a job is the one that carries value.
import '@fontsource-variable/inter';
import '@fontsource/jetbrains-mono';
import './style.css';
import {
  RECOURSE, REPO, accept, balanceOf, connect, dispute, deliver, hasWallet, openJob, read, settle,
} from './chain.js';

const el = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const short = (s) => (s ? `${String(s).slice(0, 6)}…${String(s).slice(-4)}` : '');
const gen = (wei) => `${(Number(BigInt(wei || 0)) / 1e18).toFixed(4)} GEN`;

const TONE = {
  OPEN: '', DELIVERED: '', ACCEPTED: 'good', RELEASED: 'good',
  DISPUTED: 'warn', REFUNDED: 'bad',
};

const EXAMPLE = {
  title: 'Summarise the escrow contract',
  asked: 'Read the escrow contract and list, in plain sentences, every path by which money can leave it and who is allowed to trigger each one.',
};

let account = null;
let jobs = [];

async function ensureAccount(say) {
  if (account) return account;
  say('waiting for the wallet…');
  account = await connect();
  await showAccount();
  return account;
}

// The header has to say whether you are connected and with how much, because
// every action on this page either spends money or decides where money goes,
// and finding that out by pressing a button is the wrong moment to learn it.
async function showAccount() {
  const button = el('connect');
  if (!account) {
    button.textContent = hasWallet() ? 'Connect wallet' : 'No wallet found';
    button.disabled = !hasWallet();
    return;
  }
  button.textContent = short(account);
  try {
    const wei = await balanceOf(account);
    button.textContent = `${short(account)} · ${gen(wei)}`;
  } catch { /* the address alone is still worth showing */ }
  await loadJobs();
}

// ------------------------------------------------------------------ rendering

function jobCard(j) {
  const mine = account && account.toLowerCase() === j.client;
  const isWorker = account && account.toLowerCase() === j.worker;
  const holding = BigInt(j.escrow_wei || 0) > 0n;

  return `
    <article class="card job ${TONE[j.status] || ''}" data-id="${j.id}">
      <header>
        <span class="verdict">${esc(j.status)}</span>
        <span class="fee">${gen(j.fee_wei)}</span>
        ${holding ? `<span class="pill open">holding ${gen(j.escrow_wei)}</span>`
    : '<span class="pill">escrow empty</span>'}
      </header>
      <h4>${esc(j.title) || 'untitled'}</h4>
      <p class="asked">${esc(j.asked_for)}</p>
      ${j.delivered ? `<p class="delivered"><b>Delivered:</b> ${esc(j.delivered)}</p>` : ''}
      ${j.complaint ? `<p class="complaint"><b>Contested:</b> ${esc(j.complaint)}</p>` : ''}
      ${j.reason ? `<p class="reason"><b>${esc(j.ruling)}:</b> ${esc(j.reason)}</p>` : ''}
      <footer>
        <span title="${esc(j.client)}">client ${short(j.client)}</span>
        <span title="${esc(j.worker)}">worker ${short(j.worker)}</span>
        ${isWorker && j.status === 'OPEN' ? `<button class="act-deliver" data-id="${j.id}">Deliver</button>` : ''}
        ${mine && j.status === 'DELIVERED' ? `<button class="act-accept" data-id="${j.id}">Accept and pay</button>` : ''}
        ${mine && (j.status === 'DELIVERED' || j.status === 'DISPUTED')
    ? `<button class="act-dispute" data-id="${j.id}">Contest it</button>` : ''}
      </footer>
      <p class="state hint" id="state-${j.id}"></p>
    </article>`;
}

async function loadJobs() {
  try {
    const [page, size] = await Promise.all([read('page', ['0', '30']), read('size')]);
    jobs = page.jobs || [];
    el('counts').innerHTML = `
      <span class="stat"><b>${size.jobs}</b><i>jobs</i></span>
      <span class="stat"><b>${gen(size.escrow_held_wei)}</b><i>held in escrow</i></span>
      <span class="stat good"><b>${size.settled_by_round_released}</b><i>ruled release</i></span>
      <span class="stat bad"><b>${size.settled_by_round_refunded}</b><i>ruled refund</i></span>`;

    el('jobs').innerHTML = jobs.length
      ? jobs.slice().reverse().map(jobCard).join('')
      : '<p class="empty">No jobs yet. Open one above.</p>';
    wire();
  } catch (e) {
    el('jobs').innerHTML = `<p class="error">${esc(e.message)}</p>`;
  }
}

// -------------------------------------------------------------------- actions

function wire() {
  document.querySelectorAll('.act-deliver').forEach((b) => {
    b.onclick = () => run(b.dataset.id, async (id, say) => {
      const text = window.prompt('What are you delivering?');
      if (!text) return null;
      const who = await ensureAccount(say);
      say('sending the delivery…');
      return deliver(who, id, text);
    });
  });
  document.querySelectorAll('.act-accept').forEach((b) => {
    b.onclick = () => run(b.dataset.id, async (id, say) => {
      const who = await ensureAccount(say);
      say('paying the worker…');
      return accept(who, id);
    });
  });
  document.querySelectorAll('.act-dispute').forEach((b) => {
    b.onclick = () => run(b.dataset.id, async (id, say) => {
      const text = window.prompt('What is wrong with the delivery?');
      if (!text) return null;
      const who = await ensureAccount(say);
      say('the round is running, this takes a minute or two…');
      return dispute(who, id, text);
    });
  });
}

async function run(id, action) {
  const say = (t) => { const n = el(`state-${id}`); if (n) n.textContent = t; };
  try {
    const hash = await action(id, say);
    if (!hash) return say('');
    const done = await settle(hash, say);
    say(done.ok ? '' : done.reason);
    await loadJobs();
  } catch (e) {
    say(Number(e?.code) === 4001 ? 'Cancelled in the wallet.' : String(e?.message || e));
  }
}

el('open').onsubmit = async (event) => {
  event.preventDefault();
  const say = (t) => { el('openstate').textContent = t; };
  const worker = el('worker').value.trim();
  const title = el('title').value.trim();
  const asked = el('asked').value.trim();
  const feeGen = Number(el('fee').value);

  if (!/^0x[0-9a-fA-F]{40}$/.test(worker)) return say('that is not an address');
  if (asked.length < 20) return say('the brief has to say what is being asked for');
  if (!Number.isFinite(feeGen) || feeGen <= 0) return say('the fee has to be more than zero');

  el('openbtn').disabled = true;
  try {
    const who = await ensureAccount(say);
    const wei = BigInt(Math.round(feeGen * 1e18));
    say(`locking ${feeGen} GEN…`);
    const hash = await openJob(who, worker, title, asked, wei);
    const done = await settle(hash, say);
    say(done.ok ? 'opened' : done.reason);
    await loadJobs();
  } catch (e) {
    say(Number(e?.code) === 4001 ? 'Cancelled in the wallet.' : String(e?.message || e));
  } finally {
    el('openbtn').disabled = false;
  }
};

el('example').onclick = () => {
  el('title').value = EXAMPLE.title;
  el('asked').value = EXAMPLE.asked;
};

el('connect').onclick = async () => {
  try {
    await ensureAccount((t) => { el('connect').textContent = t; });
  } catch (e) {
    el('connect').textContent = Number(e?.code) === 4001 ? 'Cancelled' : 'Connect wallet';
  }
};
showAccount();

el('year').textContent = new Date().getFullYear();
// Plain text, not a link: an explorer that answers "not found" for these
// addresses is worse than sending a reader nowhere.
el('address').textContent = RECOURSE;
el('repo').href = REPO;
if (!hasWallet()) el('openstate').textContent = 'reading works without a wallet; opening a job needs one';

loadJobs();
