// Reid's OPTCG collection. Plain JS, no build step.
// Data lives as JSON in the GitHub repo; edits save back as commits using a
// fine-grained token kept in this browser only.

const REPO = 'reidsord/optcg';
const BRANCH = 'main';
const API = 'https://api.github.com';
const LOCAL = ['localhost', '127.0.0.1'].includes(location.hostname);
const SAVE_DELAY = 2000;
const HISTORY_LIMIT = 1000;
const NEW_DAYS = 45;
const PAGE = 60;

const $ = (sel, root = document) => root.querySelector(sel);
const money = (n) => '$' + (n || 0).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const count = (n) => (n || 0).toLocaleString('en-US');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch {} },
};

const S = {
  sets: [], setByCode: new Map(), cards: [], byId: new Map(),
  orders: [], notes: '', history: [], meta: {},
  priceHist: new Map(), valueHist: [], range: store.get('range') || '365', chartCleanup: null,
  packLog: (() => { try { return JSON.parse(store.get('pack-log') || '[]'); } catch { return []; } })(),
  homeQ: '', token: store.get('gh-token'), login: null, canEdit: false,
  decks: [], deckSel: 0,
  pendingCards: {}, pendingOrders: false, pendingNotes: false, pendingDecks: false,
  saving: false, saveTimer: null, error: null,
};

// ---------- Card rules (match the old workbook) ----------

const kind = (c) => (c.alt === true ? 'alt' : c.alt === false ? 'base' : 'other');
const isSealed = (c) => !c.cardId;
const isBoosterSet = (code) => /^(OP|EB)\d+$/.test(code);
// Buy list: base cards from main and extra boosters below their target (four copies).
const buyNeed = (c) =>
  kind(c) === 'base' && isBoosterSet(c.set) && !isSealed(c) && c.rarity !== 'DON!!' && c.qty < c.target ? c.target - c.qty : 0;
const isNew = (c) => c.added && Date.now() - Date.parse(c.added) < NEW_DAYS * 864e5;
const image = (c) => `https://tcgplayer-cdn.tcgplayer.com/product/${c.productId}_200w.jpg`;
const bigImage = (c) => `https://tcgplayer-cdn.tcgplayer.com/product/${c.productId}_in_1000x1000.jpg`;
const tcgLink = (c) => `https://www.tcgplayer.com/product/${c.productId}`;

function setGroup(code) {
  if (/^OP\d+$/.test(code)) return 'Booster sets';
  if (/^(EB|PRB)\d+$/.test(code)) return 'Extra and premium boosters';
  if (/^(ST|SD)/.test(code)) return 'Starter decks';
  if (/PR\b|PRE|Prerelease/i.test(code)) return 'Pre-release and event cards';
  return 'Promos and other';
}
const GROUP_ORDER = ['Booster sets', 'Extra and premium boosters', 'Starter decks', 'Pre-release and event cards', 'Promos and other'];

// Each set gets its own color on Home; the golden angle keeps neighbouring sets far apart.
const setHue = (code) => Math.round(((S.setByCode.get(code)?.index || 0) * 137.5 + 150) % 360);

// ---------- Price trends ----------
// price-history.json keeps a point only when a price moves, so a card's price on a
// day is its latest point on or before that day.

const isoDay = (t = Date.now()) => new Date(t).toISOString().slice(0, 10);
const daysAgo = (n) => isoDay(Date.now() - n * 864e5);

function priceOn(c, day) {
  let price = null;
  for (const [d, v] of S.priceHist.get(c.productId) || []) { if (d > day) break; price = v; }
  return price;
}

function weekChange(c) {
  const was = priceOn(c, daysAgo(7));
  if (c.price == null || !was) return null;
  return { was, d: c.price - was, pct: (c.price - was) / was };
}

// Badge only for moves worth noticing, so cheap cards jumping a few cents stay quiet.
function changeBadge(c, always = false) {
  const ch = weekChange(c);
  if (!ch || (!always && (Math.abs(ch.pct) < 0.1 || Math.abs(ch.d) < 0.25)) || ch.d === 0) return '';
  const up = ch.d > 0;
  return `<span class="chg ${up ? 'up' : 'down'}" title="Over 7 days, from ${money(ch.was)}">${up ? '▲' : '▼'} ${Math.round(Math.abs(ch.pct) * 100)}%</span>`;
}

function niceTicks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  for (let v = Math.floor(lo / step) * step; v <= hi + step * 0.001; v += step) ticks.push(+v.toFixed(10));
  if (ticks[ticks.length - 1] < hi) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

const shortMoney = (v) => (Math.abs(v) >= 1000 ? '$' + (v / 1000).toLocaleString('en-US', { maximumFractionDigits: 1 }) + 'k' : money(v).replace(/\.00$/, ''));
const dayLabel = (d, year) => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', ...(year ? { year: 'numeric' } : {}), timeZone: 'UTC' });

// One-series line chart with a hover crosshair. points: [{ d: 'YYYY-MM-DD', v }].
// step: the value holds until the next point (prices); otherwise points join directly.
function lineChart(el, points, { height = 220, step = false } = {}) {
  const draw = () => {
    const W = Math.max(el.clientWidth, 200), H = height, L = 52, R = 10, T = 40, B = 24;
    const xs = points.map((p) => Date.parse(p.d));
    const x0 = xs[0], x1 = Math.max(xs[xs.length - 1], x0 + 864e5);
    const vs = points.map((p) => p.v);
    const ticks = niceTicks(Math.min(...vs), Math.max(...vs));
    const y0 = ticks[0], y1 = ticks[ticks.length - 1];
    const X = (t) => L + ((t - x0) / (x1 - x0)) * (W - L - R);
    const Y = (v) => T + (1 - (v - y0) / (y1 - y0 || 1)) * (H - T - B);
    let path = '';
    points.forEach((p, i) => {
      const x = X(xs[i]).toFixed(1), y = Y(p.v).toFixed(1);
      if (!i) path = `M${x},${y}`;
      else path += step ? `H${x}V${y}` : `L${x},${y}`;
    });
    const area = `${path}V${H - B}H${X(xs[0]).toFixed(1)}Z`;
    const years = new Date(x0).getUTCFullYear() !== new Date(x1).getUTCFullYear();
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Line chart from ${esc(dayLabel(points[0].d, true))} to ${esc(dayLabel(points[points.length - 1].d, true))}">
      ${ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(t)}" y2="${Y(t)}"/><text class="axis" x="${L - 8}" y="${Y(t) + 4}" text-anchor="end">${shortMoney(t)}</text>`).join('')}
      <path class="area" d="${area}"/><path class="line" d="${path}"/>
      <text class="axis" x="${L}" y="${H - 6}">${dayLabel(points[0].d, years)}</text>
      <text class="axis" x="${W - R}" y="${H - 6}" text-anchor="end">${dayLabel(points[points.length - 1].d, years)}</text>
      <g class="hover" visibility="hidden"><line class="cross" y1="${T}" y2="${H - B}"/><circle r="4.5"/></g>
      <rect class="hit" x="${L}" y="0" width="${W - L - R}" height="${H}"/>
    </svg><div class="tip" hidden></div>`;
    const svg = el.querySelector('svg'), g = el.querySelector('.hover'), tip = el.querySelector('.tip');
    const show = (e) => {
      const r = svg.getBoundingClientRect();
      const t = x0 + ((e.clientX - r.left) * (W / r.width) - L) / (W - L - R) * (x1 - x0);
      let i = 0;
      if (step) { while (i < xs.length - 1 && xs[i + 1] <= t) i++; }
      else xs.forEach((x, j) => { if (Math.abs(x - t) < Math.abs(xs[i] - t)) i = j; });
      const px = step ? X(Math.min(Math.max(t, x0), x1)) : X(xs[i]);
      g.setAttribute('visibility', 'visible');
      g.querySelector('line').setAttribute('x1', px); g.querySelector('line').setAttribute('x2', px);
      g.querySelector('circle').setAttribute('cx', px); g.querySelector('circle').setAttribute('cy', Y(points[i].v));
      tip.hidden = false;
      tip.innerHTML = `<b>${money(points[i].v)}</b><span>${dayLabel(step ? isoDay(Math.min(Math.max(t, x0), x1)) : points[i].d, true)}</span>`;
      const left = (px / W) * r.width;
      tip.style.left = Math.min(Math.max(left, 60), r.width - 60) + 'px';
    };
    svg.addEventListener('pointermove', show);
    svg.addEventListener('pointerdown', show);
    svg.addEventListener('pointerleave', () => { g.setAttribute('visibility', 'hidden'); tip.hidden = true; });
  };
  draw();
  let w = el.clientWidth;
  const ro = new ResizeObserver(() => { if (el.clientWidth !== w) { w = el.clientWidth; draw(); } });
  ro.observe(el);
  return () => ro.disconnect();
}

function cardPriceSeries(c) {
  const pts = (S.priceHist.get(c.productId) || []).map(([d, v]) => ({ d, v }));
  if (c.price != null && (!pts.length || pts[pts.length - 1].d < isoDay())) pts.push({ d: isoDay(), v: c.price });
  return pts;
}

// ---------- GitHub ----------

async function gh(path, { method = 'GET', body, accept } = {}) {
  const headers = { Accept: accept || 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
  if (S.token) headers.Authorization = `Bearer ${S.token}`;
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(API + path, { method, headers, body: body ? JSON.stringify(body) : undefined, cache: 'no-store' });
  if (!res.ok) {
    const err = new Error(`GitHub said ${res.status}${res.status === 401 ? ' (token not accepted)' : ''}`);
    err.status = res.status;
    throw err;
  }
  const isText = accept && (accept.includes('raw') || accept.endsWith('.sha'));
  return isText ? res.text() : res.json();
}

async function latestSha() {
  if (LOCAL) return 'local';
  try { return (await gh(`/repos/${REPO}/commits/${BRANCH}`, { accept: 'application/vnd.github.sha' })).trim(); }
  catch { return BRANCH; } // rate limited: fall back to the branch (may be a few minutes behind)
}

// Files pinned to a commit are never served stale.
const dataUrl = (path, ref) => (LOCAL ? `../${path}` : `https://raw.githubusercontent.com/${REPO}/${ref}/${path}`);

async function getJson(path, ref) {
  const res = await fetch(dataUrl(path, ref), { cache: LOCAL ? 'no-store' : 'default' });
  if (!res.ok) throw new Error(`Could not load ${path} (${res.status})`);
  return res.json();
}

// Same layout the Python scripts write: one compact object per line.
const dumpRows = (rows) => (rows.length ? '[\n' + rows.map((r) => JSON.stringify(r)).join(',\n') + '\n]\n' : '[]\n');
const dumpJson = (v) => JSON.stringify(v, null, 2) + '\n';

async function readAt(path, sha) {
  try { return await gh(`/repos/${REPO}/contents/${path}?ref=${sha}`, { accept: 'application/vnd.github.raw+json' }); }
  catch (e) { if (e.status === 404) return null; throw e; }
}

// Commit several files at once. Each updater gets the file's latest text so a
// price update that landed in between is kept, not overwritten.
async function commitFiles(updaters, message) {
  for (let attempt = 0; ; attempt++) {
    const ref = await gh(`/repos/${REPO}/git/ref/heads/${BRANCH}`);
    const head = ref.object.sha;
    const commit = await gh(`/repos/${REPO}/git/commits/${head}`);
    const tree = [];
    for (const [path, update] of Object.entries(updaters)) {
      tree.push({ path, mode: '100644', type: 'blob', content: update(await readAt(path, head)) });
    }
    const newTree = await gh(`/repos/${REPO}/git/trees`, { method: 'POST', body: { base_tree: commit.tree.sha, tree } });
    const newCommit = await gh(`/repos/${REPO}/git/commits`, { method: 'POST', body: { message, tree: newTree.sha, parents: [head] } });
    try {
      await gh(`/repos/${REPO}/git/refs/heads/${BRANCH}`, { method: 'PATCH', body: { sha: newCommit.sha } });
      return newCommit.sha;
    } catch (e) {
      if (e.status !== 422 || attempt >= 3) throw e; // 422: someone else pushed first, try again on top
    }
  }
}

// ---------- Loading ----------

async function load() {
  const sha = await latestSha();
  const [sets, orders, notes, history, meta] = await Promise.all([
    getJson('data/sets.json', sha), getJson('data/orders.json', sha), getJson('data/notes.json', sha),
    getJson('data/history.json', sha), getJson('data/meta.json', sha),
  ]);
  const optional = (path) => getJson(path, sha).catch(() => []);
  const [priceHist, valueHist, decks] = await Promise.all([optional('data/price-history.json'), optional('data/value-history.json'), optional('data/decks.json')]);
  S.decks = decks;
  S.priceHist = new Map(priceHist.map((r) => [r.p, r.h]));
  S.valueHist = valueHist;
  const files = await Promise.all(sets.map((s) => getJson(`data/cards/${s.file}`, sha)));
  S.sets = sets;
  S.setByCode = new Map(sets.map((s, i) => [s.code, { ...s, index: i }]));
  S.cards = [];
  sets.forEach((s, i) => files[i].forEach((c) => S.cards.push({ ...c, set: s.code, setIndex: i, file: s.file })));
  S.byId = new Map(S.cards.map((c) => [c.id, c]));
  S.orders = orders;
  S.notes = notes.text || '';
  S.history = history;
  S.meta = meta;
  restorePending();
}

// ---------- Editing and saving ----------

function restorePending() {
  try {
    const saved = JSON.parse(store.get('pending') || 'null');
    if (!saved) return;
    for (const [id, p] of Object.entries(saved.cards || {})) {
      const c = S.byId.get(id);
      if (!c) continue;
      S.pendingCards[id] = { before: c.qty, qty: p.qty, t: p.t };
      c.qty = p.qty;
    }
    if (saved.orders) { S.orders = saved.orders; S.pendingOrders = true; }
    if (saved.decks) { S.decks = saved.decks; S.pendingDecks = true; }
    if (saved.notes != null) { S.notes = saved.notes; S.pendingNotes = true; }
  } catch {}
}

function persistPending() {
  const has = hasPending();
  store.set('pending', has ? JSON.stringify({
    cards: Object.fromEntries(Object.entries(S.pendingCards).map(([id, p]) => [id, { qty: p.qty, t: p.t }])),
    orders: S.pendingOrders ? S.orders : null,
    decks: S.pendingDecks ? S.decks : null,
    notes: S.pendingNotes ? S.notes : null,
  }) : null);
}

const hasPending = () => Object.keys(S.pendingCards).length > 0 || S.pendingOrders || S.pendingNotes || S.pendingDecks;

function setQty(c, qty) {
  qty = Math.max(0, Math.min(999, qty | 0));
  if (qty === c.qty) return;
  const rising = qty > c.qty, wasComplete = rising && setProgress(c.set).pct >= 100;
  const p = S.pendingCards[c.id];
  const before = p ? p.before : c.qty;
  c.qty = qty;
  if (qty === before) delete S.pendingCards[c.id];
  else S.pendingCards[c.id] = { before, qty, t: new Date().toISOString() };
  changed();
  if (rising && !wasComplete && setProgress(c.set).pct >= 100) {
    confetti();
    toast(`${c.set} complete! Every card is at its target.`);
  }
}

function confetti() {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const cv = document.createElement('canvas');
  cv.className = 'confetti';
  cv.width = innerWidth * devicePixelRatio; cv.height = innerHeight * devicePixelRatio;
  document.body.append(cv);
  const ctx = cv.getContext('2d');
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const colors = ['#5fd3a8', '#d9b44a', '#f08a5d', '#7aa7ff', '#e86fa8'];
  const bits = Array.from({ length: 140 }, () => ({
    x: innerWidth / 2, y: innerHeight / 3, vx: (Math.random() - 0.5) * 14, vy: Math.random() * -12 - 4,
    r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.3, w: 6 + Math.random() * 6, c: colors[Math.floor(Math.random() * colors.length)],
  }));
  const start = performance.now();
  const frame = (now) => {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    for (const b of bits) {
      b.vy += 0.35; b.x += b.vx; b.y += b.vy; b.r += b.vr; b.vx *= 0.99;
      ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.r); ctx.fillStyle = b.c; ctx.fillRect(-b.w / 2, -b.w / 4, b.w, b.w / 2); ctx.restore();
    }
    if (now - start < 2600) requestAnimationFrame(frame); else cv.remove();
  };
  requestAnimationFrame(frame);
}

function changed() {
  persistPending();
  renderStats();
  renderSaveStatus();
  clearTimeout(S.saveTimer);
  if (hasPending()) S.saveTimer = setTimeout(save, SAVE_DELAY);
}

async function save() {
  if (S.saving || !hasPending() || !S.canEdit) { renderSaveStatus(); return; }
  S.saving = true;
  S.error = null;
  renderSaveStatus();
  const cards = S.pendingCards, orders = S.pendingOrders ? S.orders.slice() : null, notes = S.pendingNotes ? S.notes : null;
  const decks = S.pendingDecks ? S.decks.slice() : null;
  S.pendingCards = {}; S.pendingOrders = false; S.pendingNotes = false; S.pendingDecks = false;

  const updaters = {};
  const byFile = {};
  for (const [id, p] of Object.entries(cards)) (byFile[S.byId.get(id).file] ||= {})[id] = p.qty;
  for (const [file, qtys] of Object.entries(byFile)) {
    updaters[`data/cards/${file}`] = (text) => {
      const rows = JSON.parse(text || '[]');
      for (const r of rows) if (r.id in qtys) r.qty = qtys[r.id];
      return dumpRows(rows);
    };
  }
  const entries = Object.entries(cards).map(([id, p]) => {
    const c = S.byId.get(id);
    return { t: p.t, id, set: c.set, name: c.name, before: p.before, after: p.qty };
  }).sort((a, b) => b.t.localeCompare(a.t));
  if (entries.length) {
    updaters['data/history.json'] = (text) => dumpRows([...entries, ...JSON.parse(text || '[]')].slice(0, HISTORY_LIMIT));
  }
  if (orders) updaters['data/orders.json'] = () => dumpJson(orders);
  if (notes != null) updaters['data/notes.json'] = () => dumpJson({ text: notes });
  if (decks) updaters['data/decks.json'] = () => dumpJson(decks);

  const parts = [];
  if (entries.length) parts.push(entries.length === 1 ? `${entries[0].name} ${entries[0].before}→${entries[0].after}` : `${entries.length} quantities`);
  if (orders) parts.push('orders');
  if (notes != null) parts.push('notes');
  if (decks) parts.push('decks');

  try {
    await commitFiles(updaters, `Update ${parts.join(', ')}`);
    S.history = [...entries, ...S.history].slice(0, HISTORY_LIMIT);
    S.lastSaved = new Date();
  } catch (e) {
    // Put the changes back (newer edits made while saving win) and retry later.
    for (const [id, p] of Object.entries(cards)) {
      if (S.pendingCards[id]) S.pendingCards[id].before = p.before;
      else S.pendingCards[id] = p;
    }
    if (orders && !S.pendingOrders) S.pendingOrders = true;
    if (notes != null && !S.pendingNotes) S.pendingNotes = true;
    if (decks && !S.pendingDecks) S.pendingDecks = true;
    S.error = e.message;
    if (e.status === 401 || e.status === 403) S.canEdit = false;
  }
  S.saving = false;
  persistPending();
  renderSaveStatus();
  if (S.view === 'history') render();
  if (hasPending()) {
    clearTimeout(S.saveTimer);
    S.saveTimer = setTimeout(save, S.error ? 15000 : SAVE_DELAY);
  }
}

function renderSaveStatus() {
  const el = $('#save-status');
  if (!S.canEdit && !hasPending()) { el.hidden = true; return; }
  el.hidden = false;
  el.className = 'pill';
  if (S.error) { el.classList.add('err'); el.textContent = 'Not saved, retrying'; el.title = S.error; }
  else if (S.saving) el.textContent = 'Saving…';
  else if (hasPending()) el.textContent = S.canEdit ? 'Unsaved changes' : 'Sign in to save';
  else { el.classList.add('ok'); el.textContent = 'All changes saved'; el.title = ''; }
}

window.addEventListener('beforeunload', (e) => { if (hasPending()) { save(); e.preventDefault(); } });
document.addEventListener('visibilitychange', () => { if (document.hidden && hasPending()) save(); });

// ---------- Account ----------

async function checkToken() {
  if (!S.token) { S.canEdit = false; S.login = null; return; }
  try {
    const repo = await gh(`/repos/${REPO}`);
    S.canEdit = !!repo.permissions?.push;
    try { S.login = (await gh('/user')).login; } catch { S.login = null; }
  } catch (e) {
    S.canEdit = false;
    if (e.status === 401) { S.token = null; store.set('gh-token', null); toast('Your saved token stopped working. Sign in again to edit.'); }
  }
}

function openAccount() {
  const d = $('#account-dialog');
  if (S.canEdit) {
    d.innerHTML = `
      <h2>Editing${S.login ? ` as ${esc(S.login)}` : ''}</h2>
      <p>Changes save to GitHub a couple of seconds after you make them. Prices: ${esc(S.meta.priceSource || 'TCGplayer')}, updated ${esc(fmtDate(S.meta.pricesUpdatedAt))}. New cards and sets are added automatically each day.</p>
      <div class="dialog-actions">
        <button class="btn danger" data-act="signout">Sign out on this device</button>
        <span class="spacer"></span>
        <button class="btn" data-act="backup">Download backup</button>
        <button class="btn primary" data-act="close">Done</button>
      </div>`;
  } else {
    const url = `https://github.com/settings/personal-access-tokens/new?name=${encodeURIComponent('OPTCG site')}&description=${encodeURIComponent('Lets the OPTCG inventory site save edits')}&target_name=${REPO.split('/')[0]}&expires_in=366&contents=write`;
    d.innerHTML = `
      <h2>Sign in to edit</h2>
      <p>Editing uses a GitHub token that can only change this one repository. It stays in this browser and is never sent anywhere except GitHub.</p>
      <ol>
        <li><a href="${url}" target="_blank" rel="noopener">Create a fine-grained token</a>.</li>
        <li>Under <b>Repository access</b>, choose <b>Only select repositories</b> and pick <b>${esc(REPO)}</b>.</li>
        <li>Under <b>Permissions</b>, set <b>Contents</b> to <b>Read and write</b>.</li>
        <li>Generate it, copy it, and paste it here.</li>
      </ol>
      <label for="token-input">Token</label>
      <input id="token-input" type="password" autocomplete="off" spellcheck="false" placeholder="github_pat_…">
      <p class="err-text" id="token-err"></p>
      <div class="dialog-actions">
        <button class="btn" data-act="backup">Download backup</button>
        <span class="spacer"></span>
        <button class="btn" data-act="close">Cancel</button>
        <button class="btn primary" data-act="signin">Sign in</button>
      </div>`;
  }
  d.showModal();
}

$('#account-dialog').addEventListener('click', async (e) => {
  const act = e.target.closest('[data-act]')?.dataset.act;
  const d = $('#account-dialog');
  if (e.target === d || act === 'close') d.close();
  if (act === 'backup') downloadBackup();
  if (act === 'signout') { S.token = null; store.set('gh-token', null); await checkToken(); d.close(); afterAuth(); }
  if (act === 'signin') {
    const value = $('#token-input').value.trim();
    if (!value) return;
    e.target.disabled = true;
    S.token = value;
    await checkToken();
    e.target.disabled = false;
    if (S.canEdit) { store.set('gh-token', value); d.close(); afterAuth(); toast('Signed in. Your edits now save to GitHub.'); }
    else { S.token = store.get('gh-token'); $('#token-err').textContent = `That token can't write to ${REPO}. Check the repository and the Contents permission.`; }
  }
});

function afterAuth() {
  $('#account-btn').textContent = S.canEdit ? 'Editing' : 'Sign in';
  renderSaveStatus();
  render();
  if (S.canEdit && hasPending()) save();
}

// ---------- Downloads ----------

function download(name, text, type) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function downloadBackup() {
  const cards = S.cards.map(({ setIndex, file, ...c }) => c);
  download(`optcg-backup-${new Date().toISOString().slice(0, 10)}.json`,
    JSON.stringify({ exportedAt: new Date().toISOString(), sets: S.sets, cards, orders: S.orders, notes: S.notes, history: S.history, meta: S.meta }, null, 1),
    'application/json');
}

function exportCsv(list) {
  const cols = ['set', 'cardId', 'name', 'rarity', 'variant', 'qty', 'target', 'price', 'value'];
  const q = (v) => (/[",\n]/.test(String(v ?? '')) ? `"${String(v).replace(/"/g, '""')}"` : (v ?? ''));
  const lines = [cols.join(',')].concat(list.map((c) =>
    [c.set, c.cardId, c.name, c.rarity, kind(c), c.qty, c.target, c.price ?? '', ((c.qty || 0) * (c.price || 0)).toFixed(2)].map(q).join(',')));
  download(`optcg-cards-${new Date().toISOString().slice(0, 10)}.csv`, lines.join('\n') + '\n', 'text/csv');
}

// ---------- Views ----------

let toastTimer;
function toast(msg, action) {
  const t = $('#toast');
  t.innerHTML = `<span>${esc(msg)}</span>` + (action ? `<button type="button">${esc(action.label)}</button>` : '');
  if (action) t.querySelector('button').onclick = () => { action.run(); t.hidden = true; };
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), action ? 6000 : 3500);
}

function fmtDate(iso, withTime = false) {
  if (!iso) return 'never';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return withTime
    ? d.toLocaleString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
    : d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function totals(list = S.cards) {
  let value = 0, copies = 0, owned = 0;
  for (const c of list) { if (c.qty > 0) { owned++; copies += c.qty; value += c.qty * (c.price || 0); } }
  return { value, copies, owned };
}

function renderStats() {
  const t = totals();
  $('#stat-value').textContent = money(t.value);
  $('#stat-copies').textContent = count(t.copies);
  $('#stat-owned').textContent = count(t.owned);
  $('#stat-prices').textContent = fmtDate(S.meta.pricesUpdatedAt);
  $('#stat-prices').title = S.meta.priceSource || '';
  $('#foot-source').textContent = `Prices: ${S.meta.priceSource || 'TCGplayer'}`;
}

function setProgress(code) {
  let target = 0, have = 0, value = 0, baseT = 0, baseH = 0, altT = 0, altH = 0, n = 0;
  for (const c of S.cards) {
    if (c.set !== code) continue;
    n++;
    const h = Math.min(c.qty, c.target);
    target += c.target; have += h; value += c.qty * (c.price || 0);
    if (kind(c) === 'base') { baseT += c.target; baseH += h; }
    if (kind(c) === 'alt') { altT += c.target; altH += h; }
  }
  return { target, have, value, baseT, baseH, altT, altH, n, pct: target ? Math.round((have / target) * 100) : 0 };
}

function renderHome(main) {
  const buy = S.cards.filter((c) => buyNeed(c) > 0);
  const buyCopies = buy.reduce((n, c) => n + buyNeed(c), 0);
  const buyCost = buy.reduce((n, c) => n + buyNeed(c) * (c.price || 0), 0);
  const fresh = S.cards.filter(isNew);
  const freshSets = [...new Set(fresh.map((c) => c.set))];
  const top = S.cards.filter((c) => c.qty > 0).sort((a, b) => (b.price || 0) - (a.price || 0))[0];

  const groups = new Map(GROUP_ORDER.map((g) => [g, []]));
  for (const s of S.sets) groups.get(setGroup(s.code)).push(s);
  const naturalSort = (a, b) => a.code.localeCompare(b.code, 'en', { numeric: true });

  main.innerHTML = `
    <div class="home-search">
      <label class="search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
        <input id="home-q" type="search" placeholder="Find a card: name, card ID, or set" value="${esc(S.homeQ)}" aria-label="Find a card" autocomplete="off"></label>
      <div id="home-results" aria-live="polite"></div>
    </div>
    <div class="trends">
      <section class="callout chart-card">
        <div class="chart-head">
          <div><h3>Collection value</h3><div class="big" id="value-now"></div><div class="muted small" id="value-change"></div></div>
          <div class="chips" role="group" aria-label="Time range">
            ${RANGES.map(([v, l]) => `<button type="button" class="chip" data-range="${v}" aria-pressed="${S.range === v}">${l}</button>`).join('')}
          </div>
        </div>
        <div class="chart" id="value-chart"></div>
        <p class="muted small chart-note" id="value-note"></p>
      </section>
      <section class="callout movers">
        <h3>Biggest movers this week</h3>
        <div id="movers"></div>
      </section>
    </div>
    <div class="callouts">
      <a class="callout tile" href="#cards?preset=buy">
        <h3>Buy list</h3>
        <div class="big">${money(buyCost)}</div>
        <div class="muted">${count(buyCopies)} copies across ${count(buy.length)} cards to finish your playsets</div>
      </a>
      ${fresh.length ? `
      <a class="callout tile" href="#cards?preset=new">
        <h3>New in the last ${NEW_DAYS} days</h3>
        <div class="big">${count(fresh.length)} cards</div>
        <div class="muted">${esc(freshSets.slice(0, 4).join(', '))}${freshSets.length > 4 ? ` and ${freshSets.length - 4} more` : ''}</div>
      </a>` : ''}
      ${top ? `
      <a class="callout tile" href="#cards?preset=top">
        <h3>Most valuable card</h3>
        <div class="big">${money(top.price)}</div>
        <div class="muted">${esc(top.name)}</div>
      </a>` : ''}
      <div class="callout">
        <h3>Notes</h3>
        ${S.canEdit
          ? `<textarea id="notes" aria-label="Notes">${esc(S.notes)}</textarea>`
          : `<p class="notes-view">${esc(S.notes) || '<span class="muted">No notes</span>'}</p>`}
      </div>
    </div>
    ${[...groups].filter(([, sets]) => sets.length).map(([name, sets]) => `
      <div class="section-head"><h2>${esc(name)}</h2><span class="hint">${name === 'Booster sets' ? 'Base cards: four copies. DON!! cards: ten. Alternate arts, promos and sealed: one each.' : ''}</span></div>
      <div class="tiles">
        ${sets.slice().sort(naturalSort).reverse().map((s) => {
          const p = setProgress(s.code);
          return `<a class="tile${p.pct >= 100 ? ' complete' : ''}" href="#cards?set=${encodeURIComponent(s.code)}" style="--set-hue:${setHue(s.code)}">
            <div class="code">${esc(s.code)}</div>
            <div class="name">${esc(s.name)}</div>
            <div class="value">${money(p.value)}</div>
            <div class="bar"><i style="width:${p.pct}%"></i></div>
            <div class="sub"><span>${count(p.have)} / ${count(p.target)} copies · ${p.pct}%</span></div>
            <div class="sub"><span>Base ${p.baseH}/${p.baseT}</span><span>Alt ${p.altH}/${p.altT}</span></div>
          </a>`;
        }).join('')}
      </div>`).join('')}`;

  const notes = $('#notes', main);
  if (notes) notes.addEventListener('input', () => { S.notes = notes.value; S.pendingNotes = true; changed(); });

  renderValueChart();
  main.querySelectorAll('[data-range]').forEach((b) => (b.onclick = () => {
    S.range = b.dataset.range;
    store.set('range', S.range);
    main.querySelectorAll('[data-range]').forEach((x) => x.setAttribute('aria-pressed', x === b));
    renderValueChart();
  }));
  renderMovers();

  const input = $('#home-q', main);
  let typing;
  input.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(() => { S.homeQ = input.value; renderHomeResults(); }, 120); });
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && input.value.trim()) location.hash = '#cards?q=' + encodeURIComponent(input.value.trim()); });
  renderHomeResults();
}

const RANGES = [['30', '1M'], ['90', '3M'], ['365', '1Y'], ['all', 'All']];

function valueSeries() {
  const live = { d: isoDay(), v: totals().value };
  const pts = S.valueHist.filter((r) => r.date < live.d).map((r) => ({ d: r.date, v: r.value, backfill: r.backfill }));
  pts.push(live);
  return S.range === 'all' ? pts : pts.filter((p) => p.d >= daysAgo(+S.range));
}

function renderValueChart() {
  const el = $('#value-chart');
  if (!el) return;
  S.chartCleanup?.();
  const pts = valueSeries();
  const now = pts[pts.length - 1].v;
  $('#value-now').textContent = money(now);
  const first = pts[0];
  const change = $('#value-change'), note = $('#value-note');
  if (pts.length < 2) {
    change.textContent = '';
    el.innerHTML = `<p class="chart-empty">The chart fills in as the daily price update runs.</p>`;
    note.textContent = '';
    return;
  }
  const d = now - first.v;
  change.innerHTML = `<span class="${d >= 0 ? 'delta-up' : 'delta-down'}">${d >= 0 ? '▲ +' : '▼ −'}${money(Math.abs(d))} (${first.v ? Math.abs(Math.round((d / first.v) * 1000) / 10) : 0}%)</span> since ${esc(dayLabel(first.d, true))}`;
  S.chartCleanup = lineChart(el, pts);
  const firstReal = S.valueHist.find((r) => !r.backfill);
  note.textContent = pts.some((p) => p.backfill) && firstReal
    ? `Before ${dayLabel(firstReal.date, true)}, values price today's cards at that week's lowest listed prices.`
    : '';
}

function renderMovers() {
  const el = $('#movers');
  if (!el) return;
  const moves = S.cards
    .filter((c) => c.qty > 0)
    .map((c) => ({ c, ch: weekChange(c) }))
    .filter((m) => m.ch && m.ch.d)
    .sort((a, b) => Math.abs(b.c.qty * b.ch.d) - Math.abs(a.c.qty * a.ch.d))
    .slice(0, 6);
  el.innerHTML = moves.length
    ? `<ul class="mover-list">${moves.map(({ c, ch }) => {
        const up = ch.d > 0, total = c.qty * ch.d;
        return `<li data-id="${esc(c.id)}"><button type="button" class="mover" data-open>
          <span class="mover-name"><b>${esc(c.name)}</b><span class="muted">${esc(c.set)}${c.cardId ? ' · ' + esc(c.cardId) : ''} · ${c.qty} owned · ${money(ch.was)} → ${money(c.price)}</span></span>
          <span class="mover-amt ${up ? 'delta-up' : 'delta-down'}">${up ? '▲ +' : '▼ −'}${money(Math.abs(total))}</span>
        </button></li>`;
      }).join('')}</ul>`
    : '<p class="muted small">No price moves yet. This fills in after a week of daily price updates.</p>';
}

// Quick lookup on Home: closest matches first, with price and quantity buttons.
const HOME_RESULTS = 12;
function renderHomeResults() {
  const box = $('#home-results');
  if (!box) return;
  const q = S.homeQ.trim();
  if (!q) { box.innerHTML = ''; return; }
  const f = { ...readQuery(), q, preset: 'all', set: '', own: '', variant: '', rarity: '', sort: '' };
  const lower = q.toLowerCase();
  const rank = (c) => (c.cardId.toLowerCase() === lower ? 0 : c.name.toLowerCase().startsWith(lower) ? 1 : 2) * 2 + (c.qty > 0 ? 0 : 1);
  const list = filterCards(f).map((c, i) => [rank(c), i, c]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((r) => r[2]);
  const all = '#cards?q=' + encodeURIComponent(q);
  box.innerHTML = list.length
    ? `<div class="list">${list.slice(0, HOME_RESULTS).map((c) => cardHtml(c, f, 'list')).join('')}</div>
       ${list.length > HOME_RESULTS ? `<a class="more-link" href="${all}">See all ${count(list.length)} matches in Cards</a>` : ''}`
    : '<p class="empty small">No cards match.</p>';
}

// Cards view state lives in the URL hash so links like #cards?set=OP01 work.
const PRESETS = [
  ['all', 'All cards'], ['owned', 'Owned'], ['buy', 'Buy list'], ['top', 'Most valuable'], ['missing', 'Not owned'], ['new', 'New'],
];
const SORTS = [['set', 'Set order'], ['price-desc', 'Price: high to low'], ['price-asc', 'Price: low to high'], ['value', 'Value owned'], ['name', 'Name'], ['qty', 'Quantity']];

function readQuery() {
  const q = new URLSearchParams(location.hash.split('?')[1] || '');
  return {
    q: q.get('q') || '', preset: q.get('preset') || 'all', set: q.get('set') || '', own: q.get('own') || '',
    variant: q.get('variant') || '', rarity: q.get('rarity') || '', sort: q.get('sort') || '',
    view: q.get('view') || store.get('cards-view') || 'grid',
  };
}

function writeQuery(f) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v && !(k === 'preset' && v === 'all') && k !== 'view') q.set(k, v);
  history.replaceState(null, '', '#cards' + (q.toString() ? '?' + q : ''));
}

function filterCards(f) {
  const words = f.q.toLowerCase().split(/\s+/).filter(Boolean);
  let list = S.cards.filter((c) => {
    if (f.set && c.set !== f.set) return false;
    if (f.own === 'owned' && !(c.qty > 0)) return false;
    if (f.own === 'none' && c.qty > 0) return false;
    if (f.own === 'short' && !(c.qty < c.target)) return false;
    if (f.own === 'extra' && !(c.qty > c.target)) return false;
    if (f.variant === 'base' && kind(c) !== 'base') return false;
    if (f.variant === 'alt' && kind(c) !== 'alt') return false;
    if (f.variant === 'sealed' && !isSealed(c)) return false;
    if (f.variant === 'other' && (kind(c) !== 'other' || isSealed(c))) return false;
    if (f.rarity && c.rarity !== f.rarity) return false;
    if (f.preset === 'owned' && !(c.qty > 0)) return false;
    if (f.preset === 'missing' && c.qty > 0) return false;
    if (f.preset === 'buy' && !buyNeed(c)) return false;
    if (f.preset === 'top' && !(c.qty > 0)) return false;
    if (f.preset === 'new' && !isNew(c)) return false;
    if (words.length) {
      const hay = `${c.name} ${c.cardId} ${c.set} ${S.setByCode.get(c.set)?.name || ''} ${c.rarity}`.toLowerCase();
      if (!words.every((w) => hay.includes(w))) return false;
    }
    return true;
  });
  const sort = f.sort || (f.preset === 'top' ? 'price-desc' : 'set');
  const by = {
    'price-desc': (a, b) => (b.price || 0) - (a.price || 0),
    'price-asc': (a, b) => (a.price || 0) - (b.price || 0),
    value: (a, b) => b.qty * (b.price || 0) - a.qty * (a.price || 0),
    name: (a, b) => a.name.localeCompare(b.name),
    qty: (a, b) => b.qty - a.qty,
  }[sort];
  if (by) list.sort(by);
  if (f.preset === 'top') list = list.slice(0, 20);
  return list;
}

function qtyControl(c) {
  if (!S.canEdit) return `<span class="qty-ro">${c.qty} owned</span>`;
  return `<span class="stepper"><button type="button" data-step="-1" aria-label="Remove one ${esc(c.name)}">−</button><output>${c.qty}</output><button type="button" data-step="1" aria-label="Add one ${esc(c.name)}">+</button></span>`;
}

const RARITIES = ['C', 'UC', 'R', 'SR', 'SEC', 'L', 'SP', 'TR', 'P', 'DON!!'];
const rarityTag = (c) => (c.rarity ? `<span class="rar" data-r="${esc(RARITIES.includes(c.rarity) ? c.rarity : 'other')}">${esc(c.rarity)}</span>` : '');

function cardInfo(c, f) {
  const bits = [isSealed(c) && !c.rarity ? 'Sealed' : ''];
  if (f.preset === 'buy') bits.push(`Need ${buyNeed(c)}`);
  else if (c.qty < c.target && c.qty > 0) bits.push(`${c.qty}/${c.target}`);
  if (kind(c) === 'alt') bits.push('Alt');
  return bits.filter(Boolean).join(' · ');
}

function cardHtml(c, f, view) {
  const img = `<img src="${image(c)}" alt="" loading="lazy" decoding="async" data-fallback="${esc(c.name)}">`;
  if (view === 'list') {
    return `<div class="row" data-id="${esc(c.id)}">
      <a href="${tcgLink(c)}" target="_blank" rel="noopener" data-open aria-label="Details for ${esc(c.name)}">${img}</a>
      <div><div class="title" data-open>${esc(c.name)}</div><div class="info">${rarityTag(c)} ${esc(c.set)}${c.cardId ? ' · ' + esc(c.cardId) : ''}${cardInfo(c, f) ? ' · ' + esc(cardInfo(c, f)) : ''}</div></div>
      <span class="price">${c.price != null ? money(c.price) : '–'}${changeBadge(c)}</span>
      ${qtyControl(c)}
    </div>`;
  }
  return `<article class="card" data-id="${esc(c.id)}">
    <a class="art" href="${tcgLink(c)}" target="_blank" rel="noopener" data-open aria-label="Details for ${esc(c.name)}">
      ${img}
      ${isNew(c) ? '<span class="badge new">New</span>' : ''}
      <span class="badge${c.qty > 0 ? ' owned' : ''}">${c.qty > 0 ? `${c.qty} owned` : 'Not owned'}</span>
    </a>
    <div class="body">
      <div class="meta">${esc(c.set)}${c.cardId ? ' · ' + esc(c.cardId) : ''}</div>
      <div class="title" data-open>${esc(c.name)}</div>
      <div class="info">${rarityTag(c)} ${esc(cardInfo(c, f))}</div>
      <div class="foot-row"><span class="price">${c.price != null ? money(c.price) : '–'}${changeBadge(c)}</span>${qtyControl(c)}</div>
    </div>
  </article>`;
}

function options(list, selected) {
  return list.map(([v, label]) => `<option value="${esc(v)}"${v === selected ? ' selected' : ''}>${esc(label)}</option>`).join('');
}

function renderCards(main) {
  const f = readQuery();
  const rarities = [...new Set(S.cards.map((c) => c.rarity).filter(Boolean))].sort();
  main.innerHTML = `
    <div class="toolbar">
      <div class="search-row">
        <label class="search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
          <input id="q" type="search" placeholder="Search name, card ID, or set" value="${esc(f.q)}" aria-label="Search cards"></label>
        <button class="icon-btn" id="view-toggle" type="button" title="Switch grid or list" aria-label="Switch grid or list view">
          <svg viewBox="0 0 24 24" aria-hidden="true">${f.view === 'list' ? '<rect x="4" y="4" width="7" height="7"/><rect x="13" y="4" width="7" height="7"/><rect x="4" y="13" width="7" height="7"/><rect x="13" y="13" width="7" height="7"/>' : '<path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"/>'}</svg>
        </button>
        <button class="icon-btn" id="export" type="button" title="Export this list as CSV" aria-label="Export this list as CSV">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>
        </button>
      </div>
      <div class="chips" role="group" aria-label="Shortcuts">
        ${PRESETS.map(([v, l]) => `<button type="button" class="chip" data-preset="${v}" aria-pressed="${f.preset === v}">${l}</button>`).join('')}
      </div>
      <div class="filters">
        <select class="select" id="f-set" aria-label="Set"><option value="">All sets</option>${options(S.sets.map((s) => [s.code, `${s.code} · ${s.name}`]), f.set)}</select>
        <select class="select" id="f-own" aria-label="Ownership">${options([['', 'Any ownership'], ['owned', 'Owned'], ['none', 'Not owned'], ['short', 'Below target'], ['extra', 'Extras over target']], f.own)}</select>
        <select class="select" id="f-variant" aria-label="Variant">${options([['', 'All variants'], ['base', 'Base'], ['alt', 'Alternate art'], ['sealed', 'Sealed product'], ['other', 'Other']], f.variant)}</select>
        <select class="select" id="f-rarity" aria-label="Rarity"><option value="">All rarities</option>${options(rarities.map((r) => [r, r]), f.rarity)}</select>
        <select class="select" id="f-sort" aria-label="Sort">${options(SORTS, f.sort || (f.preset === 'top' ? 'price-desc' : 'set'))}</select>
        <button class="link-btn" id="clear" type="button">Clear</button>
      </div>
    </div>
    <div class="summary" id="summary"></div>
    ${f.preset === 'buy' ? '<p class="rule">Base cards from main and extra booster sets you have fewer than four of. Cost uses the copies still needed at the lowest listed price.</p>' : ''}
    <div id="results"></div>`;

  const list = filterCards(f);
  const sum = $('#summary', main);
  if (f.preset === 'buy') {
    const need = list.reduce((n, c) => n + buyNeed(c), 0);
    const cost = list.reduce((n, c) => n + buyNeed(c) * (c.price || 0), 0);
    sum.innerHTML = `<span>${count(list.length)} cards</span><span>${count(need)} copies needed · ${money(cost)} estimated · <button class="link-btn" id="buy-copy" type="button">Copy for TCGplayer</button></span>`;
    $('#buy-copy', sum).onclick = () => copyForTcgplayer(list.map((c) => massEntryLine(buyNeed(c), c)), `${list.length} buy list ${list.length === 1 ? 'card' : 'cards'}`);
  } else {
    const t = totals(list);
    sum.innerHTML = `<span>${count(list.length)} ${list.length === 1 ? 'card' : 'cards'}${f.preset === 'top' ? ' · ranked by single-card price' : ''}</span><span>${count(t.copies)} copies · ${money(t.value)} owned</span>`;
  }

  const results = $('#results', main);
  if (!list.length) { results.innerHTML = '<p class="empty">No cards match.</p>'; }
  else {
    const wrap = document.createElement('div');
    wrap.className = f.view === 'list' ? 'list' : 'grid';
    results.append(wrap);
    let shown = 0;
    const more = () => {
      wrap.insertAdjacentHTML('beforeend', list.slice(shown, shown + PAGE).map((c) => cardHtml(c, f, f.view)).join(''));
      shown += PAGE;
      if (shown >= list.length) observer.disconnect();
    };
    const sentinel = document.createElement('div');
    sentinel.className = 'sentinel';
    results.append(sentinel);
    const observer = new IntersectionObserver((e) => e[0].isIntersecting && more(), { rootMargin: '800px' });
    more();
    observer.observe(sentinel);
    S.cleanup = () => observer.disconnect();
  }

  const update = (patch) => { writeQuery({ ...f, ...patch }); render(); };
  let typing;
  $('#q', main).addEventListener('input', (e) => { clearTimeout(typing); typing = setTimeout(() => { writeQuery({ ...f, q: e.target.value }); renderCardsKeepFocus(); }, 150); });
  main.querySelectorAll('[data-preset]').forEach((b) => (b.onclick = () => update({ preset: b.dataset.preset, sort: '' })));
  $('#f-set', main).onchange = (e) => update({ set: e.target.value });
  $('#f-own', main).onchange = (e) => update({ own: e.target.value });
  $('#f-variant', main).onchange = (e) => update({ variant: e.target.value });
  $('#f-rarity', main).onchange = (e) => update({ rarity: e.target.value });
  $('#f-sort', main).onchange = (e) => update({ sort: e.target.value });
  $('#clear', main).onclick = () => { history.replaceState(null, '', '#cards'); render(); };
  $('#view-toggle', main).onclick = () => { store.set('cards-view', f.view === 'list' ? 'grid' : 'list'); render(); };
  $('#export', main).onclick = () => exportCsv(list);
}

function renderCardsKeepFocus() {
  const input = $('#q');
  const pos = input?.selectionStart;
  render();
  const again = $('#q');
  if (again) { again.focus(); if (pos != null) again.setSelectionRange(pos, pos); }
}

// Quantity steppers and broken images, handled once for every list.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-step]');
  if (btn) {
    const c = S.byId.get(btn.closest('[data-id]').dataset.id);
    setQty(c, c.qty + Number(btn.dataset.step));
    showQty(c);
    return;
  }
  // Tapping a card's picture or name opens its details; ctrl/cmd-click still opens TCGplayer.
  const open = e.target.closest('[data-open]');
  if (open && !e.metaKey && !e.ctrlKey && !e.shiftKey && e.button === 0) {
    e.preventDefault();
    openCard(open.closest('[data-id]').dataset.id);
  }
});

// The same card can be on screen twice (a list and its detail sheet), so update every copy.
function showQty(c) {
  document.querySelectorAll(`[data-id="${CSS.escape(c.id)}"]`).forEach((host) => {
    const own = (sel) => [...host.querySelectorAll(sel)].filter((el) => el.closest('[data-id]') === host);
    own('output').forEach((o) => (o.textContent = c.qty));
    own('.badge:not(.new)').forEach((b) => { b.textContent = c.qty > 0 ? `${c.qty} owned` : 'Not owned'; b.classList.toggle('owned', c.qty > 0); });
    own('[data-worth]').forEach((w) => (w.textContent = worthText(c)));
  });
}
document.addEventListener('error', (e) => {
  const img = e.target;
  if (img.tagName !== 'IMG' || !img.dataset.fallback) return;
  if (img.dataset.small && !img.src.endsWith(img.dataset.small)) { img.src = img.dataset.small; return; }
  const span = document.createElement('span');
  span.className = img.closest('.row') ? 'thumb noimg' : 'noimg';
  span.textContent = img.closest('.row') ? '' : img.dataset.fallback;
  img.replaceWith(span);
}, true);

// ---------- Card details ----------

const worthText = (c) => `${c.qty} owned · target ${c.target}${c.price != null ? ` · worth ${money(c.qty * c.price)}` : ''}`;

function openCard(id) {
  const c = S.byId.get(id);
  if (!c) return;
  const d = $('#card-dialog');
  const set = S.setByCode.get(c.set);
  const others = c.cardId ? S.cards.filter((o) => o.cardId === c.cardId && o.id !== c.id) : [];
  others.sort((a, b) => (b.qty > 0) - (a.qty > 0) || (a.price || 0) - (b.price || 0));
  const ch = weekChange(c);
  const f = { preset: 'all' };
  d.innerHTML = `
    <div class="sheet" data-id="${esc(c.id)}">
      <button type="button" class="icon-btn sheet-close" data-close aria-label="Close"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
      <div class="sheet-main">
        <a class="sheet-art" href="${tcgLink(c)}" target="_blank" rel="noopener" aria-label="${esc(c.name)} on TCGplayer">
          <img src="${bigImage(c)}" data-small="${image(c)}" data-fallback="${esc(c.name)}" alt="">
        </a>
        <div class="sheet-info">
          <div class="meta">${esc(c.set)}${set ? ' · ' + esc(set.name) : ''}</div>
          <h2>${esc(c.name)}</h2>
          <div class="muted small">${[c.cardId, c.rarity, kind(c) === 'alt' ? 'Alternate art' : kind(c) === 'base' ? 'Base' : isSealed(c) ? 'Sealed' : ''].filter(Boolean).map(esc).join(' · ')}</div>
          <div class="sheet-price">
            <span class="big">${c.price != null ? money(c.price) : 'No listing'}</span>
            ${changeBadge(c, true)}
            <span class="muted small">${ch ? `${money(ch.was)} a week ago · ` : ''}lowest listed on TCGplayer</span>
          </div>
          <div class="sheet-qty">${qtyControl(c)}<span class="muted small" data-worth>${esc(worthText(c))}</span></div>
          <h3>Price history</h3>
          <div class="chart small-chart" id="card-chart"></div>
          <div class="sheet-actions">
            <a class="btn primary" href="${tcgLink(c)}" target="_blank" rel="noopener">View on TCGplayer</a>
            <a class="btn" href="#cards?q=${encodeURIComponent(c.cardId || c.name)}" data-close>Find similar</a>
          </div>
        </div>
      </div>
      ${others.length ? `<h3 class="sheet-sub">Other printings of ${esc(c.cardId)}</h3>
        <div class="list">${others.map((o) => cardHtml(o, f, 'list')).join('')}</div>` : ''}
    </div>`;
  if (!d.open) d.showModal();
  d.scrollTop = 0;
  const series = cardPriceSeries(c);
  const chart = $('#card-chart', d);
  S.sheetCleanup?.();
  S.sheetCleanup = series.length > 1
    ? lineChart(chart, series, { height: 180, step: true })
    : (chart.innerHTML = '<p class="chart-empty">Price history starts with the next price changes.</p>', null);
}

$('#card-dialog').addEventListener('click', (e) => {
  const d = $('#card-dialog');
  if (e.target === d || e.target.closest('[data-close]')) d.close();
});
$('#card-dialog').addEventListener('close', () => { S.sheetCleanup?.(); S.sheetCleanup = null; });

// ---------- Pack opening ----------

const setPrefix = (code) => (code.match(/^[A-Z]+\d*/) || [''])[0];

function packMatches(q, setCode) {
  q = q.trim();
  if (!q) return [];
  let id = q.toUpperCase().replace(/\s+/g, '');
  if (/^\d{1,3}$/.test(id)) id = `${setPrefix(setCode)}-${id.padStart(3, '0')}`;
  let list = S.cards.filter((c) => c.cardId && c.cardId.toUpperCase() === id);
  if (!list.length) list = filterCards({ q, preset: 'all', set: '', own: '', variant: '', rarity: '', sort: '' }).filter((c) => !isSealed(c));
  const rank = (c) => (c.set === setCode ? 0 : 3) + (kind(c) === 'base' ? 0 : kind(c) === 'alt' ? 1 : 2);
  return list.map((c, i) => [rank(c), i, c]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map((r) => r[2]).slice(0, 8);
}

function packRow(c, extra = '') {
  return `<div class="row pack-row" data-id="${esc(c.id)}">
    <img src="${image(c)}" alt="" loading="lazy" data-fallback="${esc(c.name)}">
    <div><div class="title">${esc(c.name)}</div><div class="info">${esc(c.set)}${c.cardId ? ' · ' + esc(c.cardId) : ''}${c.rarity ? ' · ' + esc(c.rarity) : ''}${kind(c) === 'alt' ? ' · Alt' : ''} · ${c.qty} owned</div></div>
    <span class="price">${c.price != null ? money(c.price) : '–'}</span>
    ${extra}
  </div>`;
}

function renderPacks(main) {
  const boosters = S.sets.filter((s) => /^(OP|EB|PRB|ST)\d+/.test(s.code)).map((s) => s.code).sort((a, b) => b.localeCompare(a, 'en', { numeric: true }));
  const newestOP = boosters.find((code) => /^OP\d+$/.test(code));
  let setCode = store.get('pack-set');
  if (!S.setByCode.has(setCode)) setCode = newestOP || S.sets[0]?.code;
  if (!S.canEdit) {
    main.innerHTML = `<div class="callout pack-signin"><h3>Pack opening</h3><p>Type card numbers as you open packs and each one is added to your collection. Sign in first so the changes can save.</p><button class="btn primary" id="pack-signin" type="button">Sign in</button></div>`;
    $('#pack-signin', main).onclick = openAccount;
    return;
  }
  const others = S.sets.map((s) => s.code).filter((code) => !boosters.includes(code));
  main.innerHTML = `<div class="packs">
    <div class="pack-bar">
      <select class="select" id="pack-set" aria-label="Set you're opening">
        <optgroup label="Boosters and decks">${options(boosters.map((code) => [code, `${code} · ${S.setByCode.get(code).name}`]), setCode)}</optgroup>
        <optgroup label="Other">${options(others.map((code) => [code, `${code} · ${S.setByCode.get(code).name}`]), setCode)}</optgroup>
      </select>
      <label class="search"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h10"/></svg>
        <input id="pack-q" type="text" placeholder="Card number, e.g. 108 or ST01-012" autocomplete="off" autocapitalize="characters" spellcheck="false" enterkeyhint="done" aria-label="Card number or name"></label>
    </div>
    <p class="muted small pack-help">Type the number from the card and press Enter to add one copy of the highlighted printing. Tap a different printing to add that one instead.</p>
    <div id="pack-matches"></div>
    <div class="section-head"><h2>This session</h2><span class="hint" id="pack-summary"></span></div>
    <div id="pack-log"></div></div>`;

  const input = $('#pack-q', main);
  let matches = [], sel = 0;
  const showMatches = () => {
    const box = $('#pack-matches', main);
    if (!input.value.trim()) { box.innerHTML = ''; return; }
    box.innerHTML = matches.length
      ? `<div class="list">${matches.map((c, i) => packRow(c, `<button type="button" class="btn${i === sel ? ' primary' : ''} pack-add" data-add="${i}" aria-label="Add one ${esc(c.name)}">+1</button>`).replace('class="row pack-row"', `class="row pack-row${i === sel ? ' sel' : ''}"`)).join('')}</div>`
      : '<p class="empty small">No card with that number. Check the set, or type the full number like OP15-108.</p>';
  };
  const add = (c) => {
    setQty(c, c.qty + 1);
    S.packLog.unshift({ id: c.id, t: Date.now() });
    store.set('pack-log', JSON.stringify(S.packLog.slice(0, 500)));
    input.value = ''; matches = []; sel = 0;
    showMatches(); showLog();
    input.focus();
  };
  const showLog = () => {
    const log = S.packLog.map((p) => S.byId.get(p.id)).filter(Boolean);
    const value = log.reduce((n, c) => n + (c.price || 0), 0);
    const best = log.reduce((b, c) => ((c.price || 0) > (b?.price || 0) ? c : b), null);
    $('#pack-summary', main).innerHTML = log.length
      ? `${count(log.length)} ${log.length === 1 ? 'card' : 'cards'} · ${money(value)} pulled${best ? ` · best: ${esc(best.name)} (${money(best.price)})` : ''} · <button class="link-btn" id="pack-clear" type="button">Start over</button>`
      : '';
    $('#pack-log', main).innerHTML = log.length
      ? `<div class="list">${log.map((c, i) => packRow(c, `<button type="button" class="link-btn" data-undo-pull="${i}">Undo</button>`)).join('')}</div>`
      : '<p class="muted small">Cards you add show up here, newest first.</p>';
    const clear = $('#pack-clear', main);
    if (clear) clear.onclick = () => { S.packLog = []; store.set('pack-log', null); showLog(); };
  };

  input.addEventListener('input', () => { matches = packMatches(input.value, setCode); sel = 0; showMatches(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (matches.length) { sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + matches.length) % matches.length; showMatches(); }
    } else if (e.key === 'Enter' && matches[sel]) { e.preventDefault(); add(matches[sel]); }
  });
  $('#pack-set', main).onchange = (e) => {
    setCode = e.target.value;
    store.set('pack-set', setCode);
    matches = packMatches(input.value, setCode); sel = 0; showMatches();
    input.focus();
  };
  $('.packs', main).addEventListener('click', (e) => {
    const addBtn = e.target.closest('[data-add]');
    if (addBtn) { add(matches[+addBtn.dataset.add]); return; }
    const undo = e.target.closest('[data-undo-pull]');
    if (undo) {
      const [p] = S.packLog.splice(+undo.dataset.undoPull, 1);
      const c = S.byId.get(p.id);
      if (c) setQty(c, c.qty - 1);
      store.set('pack-log', JSON.stringify(S.packLog));
      showLog();
    }
  });
  showLog();
  if (matchMedia('(pointer: fine)').matches) input.focus();
}

// ---------- TCGplayer Mass Entry ----------
// Lines like "2 Nami (OP15-108) [OP15] OP15-108", pasted at tcgplayer.com/massentry.

const MASS_ENTRY = 'https://www.tcgplayer.com/massentry';
const massEntryLine = (n, c) => `${n} ${c.name} [${c.set}]${c.cardId ? ' ' + c.cardId : ''}`;

async function copyForTcgplayer(lines, what) {
  const text = lines.join('\n');
  try { await navigator.clipboard.writeText(text); }
  catch { download('tcgplayer-mass-entry.txt', text + '\n', 'text/plain'); }
  toast(`Copied ${what}. Paste it into TCGplayer Mass Entry.`, { label: 'Open TCGplayer', run: () => window.open(MASS_ENTRY, '_blank', 'noopener') });
}

// ---------- Deck checker ----------

const DECK_ID = /\b([A-Z]{1,4}\d{0,2}-\d{3})\b/;

// Accepts "4xOP01-016", "4 OP01-016", "4 Nami (OP01-016)" and similar, one card per line.
function parseDeck(text) {
  const wanted = new Map();
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*(\d+)\s*x?\s*(.+)$/i);
    const id = m && (m[2].toUpperCase().match(DECK_ID) || [])[1];
    if (id) wanted.set(id, (wanted.get(id) || 0) + Number(m[1]));
  }
  return wanted;
}

function checkDeck(text) {
  const rows = [];
  for (const [id, need] of parseDeck(text)) {
    const printings = S.cards.filter((c) => c.cardId.toUpperCase() === id && !isSealed(c));
    const priced = printings.filter((c) => c.price != null).sort((a, b) => a.price - b.price);
    const base = printings.find((c) => kind(c) === 'base') || printings[0];
    const own = printings.reduce((n, c) => n + c.qty, 0);
    const cheapest = priced[0] || null;
    const missing = Math.max(0, need - own);
    rows.push({ id, need, own, missing, base, cheapest, cost: missing * (cheapest?.price || 0) });
  }
  return rows;
}

const baseName = (c) => c.name.replace(/\s*\([^)]*\)\s*$/, '').replace(/\s*\([^)]*\)\s*$/, '') || c.name;

function renderDecks(main) {
  if (S.deckSel >= S.decks.length) S.deckSel = S.decks.length ? 0 : -1;
  const deck = S.decks[S.deckSel] || { name: '', list: '' };
  main.innerHTML = `<div class="decks">
    <div class="deck-picker">
      <div class="chips" role="group" aria-label="Saved decks">
        ${S.decks.map((d, i) => `<button type="button" class="chip" data-deck="${i}" aria-pressed="${i === S.deckSel}">${esc(d.name || 'Untitled deck')}</button>`).join('')}
        <button type="button" class="chip" data-deck="-1" aria-pressed="${S.deckSel === -1}">+ New deck</button>
      </div>
    </div>
    <div class="deck-grid">
      <div class="deck-input callout">
        <label class="field-label" for="deck-name">Deck name</label>
        <input id="deck-name" class="text-input" value="${esc(deck.name)}" placeholder="e.g. Red Zoro" autocomplete="off">
        <label class="field-label" for="deck-list">Decklist</label>
        <textarea id="deck-list" class="text-input" rows="14" spellcheck="false" placeholder="Paste a decklist, one card per line:&#10;1xOP01-001&#10;4xOP01-016&#10;4 Nami (OP15-108)">${esc(deck.list)}</textarea>
        <div class="deck-actions">
          ${S.canEdit ? `<button class="btn primary" id="deck-save" type="button">${S.deckSel === -1 ? 'Save deck' : 'Save changes'}</button>` : '<span class="muted small">Sign in to save decks.</span>'}
          ${S.canEdit && S.deckSel !== -1 ? '<button class="btn danger" id="deck-delete" type="button">Delete</button>' : ''}
        </div>
      </div>
      <div class="deck-result" id="deck-result"></div>
    </div></div>`;

  const list = $('#deck-list', main), name = $('#deck-name', main);
  const show = () => {
    const rows = checkDeck(list.value);
    const box = $('#deck-result', main);
    if (!rows.length) { box.innerHTML = '<p class="empty small">Paste a decklist to see what you own and what is missing.</p>'; return; }
    const total = rows.reduce((n, r) => n + r.need, 0);
    const owned = rows.reduce((n, r) => n + Math.min(r.need, r.own), 0);
    const missing = rows.filter((r) => r.missing && r.base);
    const unknown = rows.filter((r) => !r.base);
    const cost = missing.reduce((n, r) => n + r.cost, 0);
    box.innerHTML = `
      <div class="deck-summary callout">
        <div><div class="big">${count(owned)} / ${count(total)}</div><div class="muted small">cards owned</div></div>
        <div><div class="big">${count(missing.reduce((n, r) => n + r.missing, 0))}</div><div class="muted small">copies missing</div></div>
        <div><div class="big">${money(cost)}</div><div class="muted small">to finish, at the cheapest printing</div></div>
        ${missing.length ? '<button class="btn" id="deck-copy" type="button">Copy missing for TCGplayer</button>' : '<span class="done-tag">Ready to play</span>'}
      </div>
      ${unknown.length ? `<p class="muted small">Not found: ${unknown.map((r) => esc(r.id)).join(', ')}</p>` : ''}
      <div class="list">${rows.filter((r) => r.base).sort((a, b) => (b.missing > 0) - (a.missing > 0)).map((r) => `
        <div class="row deck-row${r.missing ? ' short' : ''}" data-id="${esc(r.base.id)}">
          <a href="${tcgLink(r.base)}" target="_blank" rel="noopener" data-open aria-label="Details for ${esc(r.base.name)}"><img src="${image(r.base)}" alt="" loading="lazy" data-fallback="${esc(r.base.name)}"></a>
          <div><div class="title" data-open>${esc(baseName(r.base))}</div><div class="info">${rarityTag(r.base)} ${esc(r.id)} · own ${r.own} of ${r.need}</div></div>
          <span class="price">${r.missing ? `Need ${r.missing}` : '✓'}</span>
          <span class="deck-cost">${r.missing ? money(r.cost) : ''}</span>
        </div>`).join('')}</div>`;
    const copy = $('#deck-copy', box);
    if (copy) copy.onclick = () => copyForTcgplayer(missing.filter((r) => r.cheapest).map((r) => massEntryLine(r.missing, r.cheapest)), `${missing.length} missing ${missing.length === 1 ? 'card' : 'cards'}`);
  };
  let typing;
  list.addEventListener('input', () => { clearTimeout(typing); typing = setTimeout(show, 200); });
  main.querySelectorAll('[data-deck]').forEach((b) => (b.onclick = () => { S.deckSel = +b.dataset.deck; renderDecks(main); }));
  const saveBtn = $('#deck-save', main);
  if (saveBtn) saveBtn.onclick = () => {
    const d = { name: name.value.trim() || 'Untitled deck', list: list.value.trim(), updated: isoDay() };
    if (S.deckSel === -1) { S.decks.push(d); S.deckSel = S.decks.length - 1; } else S.decks[S.deckSel] = d;
    S.pendingDecks = true; changed(); renderDecks(main);
    toast(`Saved ${d.name}.`);
  };
  const del = $('#deck-delete', main);
  if (del) del.onclick = () => {
    const [removed] = S.decks.splice(S.deckSel, 1);
    const at = S.deckSel;
    S.deckSel = S.decks.length ? 0 : -1;
    S.pendingDecks = true; changed(); renderDecks(main);
    toast(`Deleted ${removed.name}.`, { label: 'Undo', run: () => { S.decks.splice(at, 0, removed); S.deckSel = at; S.pendingDecks = true; changed(); render(); } });
  };
  show();
}

function renderOrders(main) {
  const paid = S.orders.reduce((n, o) => n + (Number.isFinite(o.paid) ? o.paid : 0), 0);
  const remaining = S.orders.reduce((n, o) => n + (Number.isFinite(o.remaining) ? o.remaining : 0), 0);
  const rows = S.orders.map((o, i) => [o, i]).reverse();
  const storeCell = (s) => (/^https?:\/\//.test(s) ? `<a href="${esc(s)}" target="_blank" rel="noopener">${esc(new URL(s).hostname.replace(/^www\./, ''))}</a>` : esc(s));
  main.innerHTML = `
    <div class="section-head" style="margin-top:0">
      <div><h2>Orders and preorders</h2><div class="hint">${money(paid)} paid · ${money(remaining)} remaining</div></div>
      ${S.canEdit ? '<button class="btn primary" id="add-order" type="button">+ Add order</button>' : ''}
    </div>
    <div class="table-wrap"><table>
      <thead><tr><th class="n">Qty</th><th>Set / item</th><th>Store</th><th>Order</th><th>Date</th><th class="n">Paid</th><th class="n">Remaining</th><th>Note</th></tr></thead>
      <tbody>${rows.map(([o, i]) => `<tr${S.canEdit ? ` class="clickable" data-order="${i}"` : ''}>
        <td class="n">${o.qty ?? ''}</td><td>${esc(o.set)}</td><td>${storeCell(o.store || '')}</td>
        <td style="white-space:pre-line">${esc(o.order)}</td><td class="muted">${esc(o.date)}</td>
        <td class="n">${o.paid != null ? money(o.paid) : ''}</td><td class="n">${o.remaining != null ? money(o.remaining) : ''}</td><td class="muted">${esc(o.note)}</td>
      </tr>`).join('')}</tbody>
    </table></div>`;
  $('#add-order', main)?.addEventListener('click', () => editOrder(-1));
  main.querySelectorAll('[data-order]').forEach((tr) => tr.addEventListener('click', (e) => { if (!e.target.closest('a')) editOrder(+tr.dataset.order); }));
}

function editOrder(index) {
  const o = index >= 0 ? S.orders[index] : { qty: 1, set: '', store: '', order: '', date: new Date().toISOString().slice(0, 10), paid: null, remaining: null, note: '' };
  const d = $('#order-dialog');
  const field = (name, label, type = 'text', wide = false) =>
    `<div${wide ? ' class="wide"' : ''}><label for="o-${name}">${label}</label><input id="o-${name}" name="${name}" type="${type}" ${type === 'number' ? 'step="any" inputmode="decimal"' : ''} value="${esc(o[name] ?? '')}"></div>`;
  d.innerHTML = `<form method="dialog">
    <h2>${index >= 0 ? 'Edit order' : 'Add order'}</h2>
    <div class="form-grid">
      ${field('qty', 'Quantity', 'number')}${field('set', 'Set or item')}
      ${field('store', 'Store')}${field('order', 'Order number')}
      ${field('date', 'Date')}${field('paid', 'Paid', 'number')}
      ${field('remaining', 'Remaining', 'number')}${field('note', 'Note')}
    </div>
    <div class="dialog-actions">
      ${index >= 0 ? '<button class="btn danger" value="delete">Delete</button>' : ''}
      <span class="spacer"></span>
      <button class="btn" value="cancel">Cancel</button>
      <button class="btn primary" value="save">Save</button>
    </div></form>`;
  d.onclose = () => {
    if (d.returnValue === 'delete') {
      const removed = S.orders.splice(index, 1)[0];
      S.pendingOrders = true; changed(); render();
      toast('Order deleted.', { label: 'Undo', run: () => { S.orders.splice(index, 0, removed); S.pendingOrders = true; changed(); render(); } });
    } else if (d.returnValue === 'save') {
      const form = new FormData(d.querySelector('form'));
      const num = (k) => { const v = String(form.get(k)).trim(); return v === '' ? null : Number(v); };
      const next = {
        id: o.id || `order:${Date.now()}`, qty: num('qty'), set: form.get('set').trim(), store: form.get('store').trim(),
        order: form.get('order').trim(), date: form.get('date').trim(), paid: num('paid'), remaining: num('remaining'), note: form.get('note').trim(),
      };
      if (index >= 0) S.orders[index] = next; else S.orders.push(next);
      S.pendingOrders = true; changed(); render();
    }
  };
  d.returnValue = '';
  d.showModal();
}

function renderHistory(main) {
  const pending = Object.entries(S.pendingCards).map(([id, p]) => ({ t: p.t, id, name: S.byId.get(id).name, set: S.byId.get(id).set, before: p.before, after: p.qty, pending: true }));
  const rows = [...pending.sort((a, b) => b.t.localeCompare(a.t)), ...S.history];
  main.innerHTML = `
    <div class="section-head" style="margin-top:0"><h2>Recent changes</h2><span class="hint">Every saved change is also kept in the GitHub history.</span></div>
    ${rows.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Time</th><th>Card</th><th class="n">Before</th><th class="n">After</th>${S.canEdit ? '<th></th>' : ''}</tr></thead>
      <tbody>${rows.slice(0, 300).map((h, i) => {
        const c = S.byId.get(h.id);
        const cls = h.after > h.before ? 'delta-up' : 'delta-down';
        const undo = S.canEdit && c && c.qty === h.after && !h.pending ? `<button class="link-btn" data-undo="${i}" type="button">Undo</button>` : '';
        return `<tr><td class="muted">${h.pending ? 'Saving…' : esc(fmtDate(h.t, true))}</td>
          <td>${esc(h.name)} <span class="muted">· ${esc(h.set)}</span></td>
          <td class="n">${h.before}</td><td class="n ${cls}">${h.after}</td>${S.canEdit ? `<td class="n">${undo}</td>` : ''}</tr>`;
      }).join('')}</tbody></table></div>`
      : `<p class="empty">No changes yet. Quantity edits will show up here.${S.meta.importedAt ? ` History starts from the move on ${esc(fmtDate(S.meta.importedAt))}.` : ''}</p>`}`;
  main.querySelectorAll('[data-undo]').forEach((b) => (b.onclick = () => {
    const h = rows[+b.dataset.undo];
    setQty(S.byId.get(h.id), h.before);
    render();
    toast(`${h.name} set back to ${h.before}.`);
  }));
}

// ---------- Router ----------

function render() {
  S.cleanup?.();
  S.cleanup = null;
  S.chartCleanup?.();
  S.chartCleanup = null;
  const view = (location.hash.slice(1).split('?')[0] || 'home');
  S.view = ['home', 'cards', 'packs', 'decks', 'orders', 'history'].includes(view) ? view : 'home';
  document.querySelectorAll('.tabs a').forEach((a) => { if (a.dataset.tab === S.view) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  const main = $('#main');
  ({ home: renderHome, cards: renderCards, packs: renderPacks, decks: renderDecks, orders: renderOrders, history: renderHistory })[S.view](main);
}

window.addEventListener('hashchange', () => { render(); window.scrollTo({ top: 0 }); });
$('#account-btn').onclick = openAccount;
$('#theme-toggle').onclick = () => {
  const dark = getComputedStyle(document.documentElement).colorScheme.includes('dark');
  const next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  store.set('theme', next);
};

// Jump buttons: shown once the page is long and you've scrolled; each hides at its own end.
function updateJump() {
  const max = document.documentElement.scrollHeight - innerHeight;
  const y = scrollY;
  $('#jump').hidden = max < innerHeight * 1.5 || (y < 300 && max - y < 300);
  $('#jump-top').disabled = y < 300;
  $('#jump-bottom').disabled = max - y < 300;
}
addEventListener('scroll', updateJump, { passive: true });
addEventListener('resize', updateJump);
new ResizeObserver(updateJump).observe(document.body);
const smooth = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
$('#jump-top').onclick = () => scrollTo({ top: 0, behavior: smooth });
$('#jump-bottom').onclick = () => scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth });

// Installable app: the service worker keeps the site and the last loaded data for offline use.
if ('serviceWorker' in navigator && !LOCAL) navigator.serviceWorker.register('sw.js').catch(() => {});

(async function start() {
  try {
    await Promise.all([load(), checkToken()]);
  } catch (e) {
    $('#main').innerHTML = `<p class="empty">Couldn't load the collection: ${esc(e.message)}. <button class="link-btn" onclick="location.reload()">Try again</button></p>`;
    return;
  }
  renderStats();
  afterAuth();
})();
