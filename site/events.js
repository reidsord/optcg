// Events tab: tournaments near home from Bandai TCG+, official event announcements,
// and new products (Premium Bandai exclusives marked). The data files are written by
// scripts/update_events.py every hour.

const BIG = ['Store Championship', 'Treasure Cup', 'Prerelease', 'Regionals', 'Release Event'];
const KIND_HUE = {
  'Store Championship': 12, 'Treasure Cup': 45, Prerelease: 280, Regionals: 350, 'Release Event': 200,
  'Extra Battle': 30, 'Pirates Party': 160, 'Store Tournament': 120, Other: 220,
};
const TCG_EVENT = (id) => `https://www.bandai-tcg-plus.com/event/${id}`;
const RECENT_DAYS = 3;

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
};

let cache = null;

// Event times are the venue's local wall clock, so format them without shifting zones.
const local = (iso) => new Date(iso + (/[zZ]|[+-]\d\d:\d\d$/.test(iso) ? '' : 'Z'));
const fmt = (iso, opts) => local(iso).toLocaleString('en-US', { timeZone: 'UTC', ...opts });
const dayKey = (iso) => iso.slice(0, 10);
const isRecent = (seen) => seen && Date.now() - Date.parse(seen) < RECENT_DAYS * 864e5;

function registration(e) {
  if (e.canceled) return '<span class="pill err">Canceled</span>';
  if (e.full) return '<span class="pill">Full</span>';
  if (!e.opens) return '';
  const opens = new Date(e.opens);
  if (opens <= new Date()) return '<span class="pill ok">Registration open</span>';
  return `<span class="pill">Registration opens ${esc(opens.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }))}</span>`;
}

function eventRow(e) {
  const fee = e.fee === 0 ? 'Free' : e.fee != null ? `$${e.fee}` : '';
  return `<a class="ev-row" href="${TCG_EVENT(e.id)}" target="_blank" rel="noopener" style="--kind-hue:${KIND_HUE[e.kind] ?? 220}">
    <div class="ev-time">${esc(fmt(e.start, { hour: 'numeric', minute: '2-digit' }))}</div>
    <div class="ev-main">
      <div class="ev-head"><span class="ev-kind">${esc(e.kind)}</span>${isRecent(e.seen) ? '<span class="ev-new">New</span>' : ''}</div>
      <div class="ev-title">${esc(e.title)}</div>
      <div class="muted small">${esc(e.store)} · ${esc(e.address)}</div>
      <div class="ev-meta">${e.miles != null ? `<span>${e.miles} mi</span>` : ''}${fee ? `<span>${esc(fee)}</span>` : ''}${e.cap ? `<span>${e.cap} players</span>` : ''}${registration(e)}</div>
    </div>
  </a>`;
}

function productCard(d) {
  return `<a class="drop" href="${esc(d.url)}" target="_blank" rel="noopener">
    ${d.image ? `<img src="${esc(d.image)}" alt="" loading="lazy">` : '<div class="drop-ph" aria-hidden="true">P</div>'}
    <div class="drop-body">
      <div class="ev-head">${d.premiumBandai ? '<span class="ev-kind" style="--kind-hue:330">Premium Bandai</span>' : d.category ? `<span class="muted small">${esc(d.category)}</span>` : ''}${isRecent(d.seen) ? '<span class="ev-new">New</span>' : ''}</div>
      <div class="drop-name">${esc(d.name)}</div>
      <div class="muted small">${esc(d.price || '')}</div>
    </div>
  </a>`;
}

function clock(hour) {
  const h = Math.floor(hour);
  return `${h % 12 || 12}:${hour % 1 ? '30' : '00'} ${h < 12 ? 'AM' : 'PM'} ET`;
}

// Bandai TCG+ shows nothing before a series goes live, so this lists the early signs:
// when past series dropped, sign-up lines on official pages, and prerelease news on store sites.
function signupWatch(watch) {
  const pattern = watch.pattern || {};
  const kinds = BIG.filter((k) => pattern[k]);
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = (watch.sets || []).filter((r) => r.expected && r.release >= today && !r.live);
  const official = (watch.official || []).filter((r) => r.lines && r.lines.length);
  const stores = watch.stores || [];
  const news = stores.filter((r) => r.snippets && r.snippets.length);
  const readable = stores.filter((r) => !r.error).length;
  if (!kinds.length && !official.length && !stores.length && !upcoming.length) return '';
  return `
      <div class="section-head"><h2>Sign-up watch</h2>
        <span class="hint">Bandai TCG+ hides events until the moment sign-ups open, so these are the early signs</span></div>
      ${upcoming.length ? `<div class="list">${upcoming.map((r) => `<a class="ev-row" href="${esc(r.url)}" target="_blank" rel="noopener" style="--kind-hue:${KIND_HUE.Prerelease}"><div class="ev-main">
        <div class="ev-head"><span class="ev-kind">${esc(r.id)} prerelease</span>${r.learned ? '' : '<span class="muted small">estimate</span>'}</div>
        <div class="ev-title">Sign-ups expected ${esc(new Date(r.expected).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }))}</div>
        <div class="muted small">Releases ${esc(fmt(r.release + 'T12:00:00', { month: 'short', day: 'numeric' }))}, prerelease likely around ${esc(fmt(r.prerelease + 'T12:00:00', { month: 'short', day: 'numeric' }))}</div></div></a>`).join('')}</div>` : ''}
      ${kinds.length ? `<div class="list">${kinds.map((k) => `<div class="ev-row" style="--kind-hue:${KIND_HUE[k] ?? 220}"><div class="ev-main">
        <div class="ev-head"><span class="ev-kind">${esc(k)}</span></div>
        <div class="ev-title">Usually goes live around ${clock(pattern[k].hourET)}, about ${pattern[k].leadDays} days before the first event</div>
        <div class="muted small">From ${pattern[k].series} series seen near you</div></div></div>`).join('')}</div>` : ''}
      ${official.map((r) => `<a class="ev-row" href="${esc(r.id)}" target="_blank" rel="noopener"><div class="ev-main">
        <div class="ev-head"><span class="muted small">Official site</span></div><div class="ev-title">${esc(r.name)}</div>
        ${r.lines.map((l) => `<div class="muted small">${esc(l)}</div>`).join('')}</div></a>`).join('')}
      ${news.map((r) => `<a class="ev-row" href="${esc(r.url)}" target="_blank" rel="noopener"><div class="ev-main">
        <div class="ev-head"><span class="muted small">${esc(r.store || r.id)}${r.miles != null ? ` · ${r.miles} mi` : ''}</span></div>
        ${r.snippets.slice(0, 4).map((l) => `<div class="small">${esc(l)}</div>`).join('')}</div></a>`).join('')}
      <p class="muted small">Watching ${readable} store website${readable === 1 ? '' : 's'} near you for prerelease news. Facebook, Instagram and Discord pages can't be read automatically.</p>`;
}

export async function renderEvents(main, { getJson, ref }) {
  if (!cache) {
    main.innerHTML = '<p class="loading">Loading events…</p>';
    const optional = (path) => getJson(path, ref).catch(() => null);
    const [events, drops, cfg, watch] = await Promise.all([optional('data/events.json'), optional('data/drops.json'), optional('data/alerts.json'), optional('data/watch.json')]);
    cache = { events: events || {}, drops: drops || {}, cfg: cfg || {}, watch: watch || {} };
  }
  const { events, drops, cfg, watch } = cache;
  const list = (events.events || []).filter((e) => e.start && dayKey(e.start) >= new Date(Date.now() - 864e5).toISOString().slice(0, 10));
  const kinds = [...new Set(list.map((e) => e.kind))].sort((a, b) => (BIG.indexOf(a) + 1 || 99) - (BIG.indexOf(b) + 1 || 99));
  let filter = store.get('events-filter') || 'big';
  if (filter !== 'big' && filter !== 'all' && !kinds.includes(filter)) filter = 'big';
  let pbOnly = store.get('drops-pb') === '1';
  const search = events.search || {};
  const home = search.home && search.home !== 'test' ? search.home : null;

  const draw = () => {
    const shown = list.filter((e) => (filter === 'all' ? true : filter === 'big' ? BIG.includes(e.kind) : e.kind === filter));
    const byDay = new Map();
    for (const e of shown) {
      const k = dayKey(e.start);
      if (!byDay.has(k)) byDay.set(k, []);
      byDay.get(k).push(e);
    }
    const products = (drops.items || []).filter((d) => !pbOnly || d.premiumBandai).slice(0, 24);
    const news = events.announcements || [];
    main.innerHTML = `
      <div class="section-head" style="margin-top:0">
        <div><h2>Tournaments${home ? ` within ${search.radiusMiles} miles of ${esc(home)}` : ''}</h2>
        <div class="hint">From Bandai TCG+, checked every hour. New big events notify you on Discord and GitHub, with a reminder before registration opens.</div></div>
      </div>
      ${!home ? `<p class="empty">Add your zip code in <code>data/alerts.json</code> to see tournaments near you.</p>` : `
      <div class="chips" role="group" aria-label="Event type">
        <button type="button" class="chip" data-f="big" aria-pressed="${filter === 'big'}">Big events</button>
        <button type="button" class="chip" data-f="all" aria-pressed="${filter === 'all'}">All (${list.length})</button>
        ${kinds.map((k) => `<button type="button" class="chip" data-f="${esc(k)}" aria-pressed="${filter === k}">${esc(k)} (${list.filter((e) => e.kind === k).length})</button>`).join('')}
      </div>
      ${shown.length ? [...byDay].slice(0, 60).map(([day, rows]) => `
        <h3 class="ev-day">${esc(fmt(day + 'T12:00:00', { weekday: 'long', month: 'long', day: 'numeric' }))}</h3>
        <div class="list">${rows.map(eventRow).join('')}</div>`).join('')
        : `<p class="empty">No ${filter === 'big' ? 'big events' : 'events'} coming up nearby right now.${filter === 'big' && list.length ? ' Try All to see weekly store tournaments.' : ''}</p>`}`}

      ${signupWatch(watch)}

      <div class="section-head"><h2>Official announcements</h2><span class="hint">Treasure Cups, Store Championships, Regionals and more from the official site</span></div>
      ${news.length ? `<div class="list">${news.map((a) => `<a class="ev-row" href="${esc(a.url)}" target="_blank" rel="noopener">
        <div class="ev-main"><div class="ev-head">${(a.tags || []).map((t) => `<span class="muted small">${esc(t)}</span>`).join(' · ')}${isRecent(a.seen) ? '<span class="ev-new">New</span>' : ''}</div>
        <div class="ev-title">${esc(a.name)}</div><div class="muted small">${esc(a.when)}</div></div></a>`).join('')}</div>`
        : '<p class="empty small">Nothing yet. The first check fills this in.</p>'}

      <div class="section-head"><h2>New products</h2>
        <button type="button" class="chip" id="pb-only" aria-pressed="${pbOnly}">Premium Bandai only</button></div>
      ${products.length ? `<div class="drops">${products.map(productCard).join('')}</div>`
        : '<p class="empty small">Nothing yet. The first check fills this in.</p>'}
      <p class="muted small">Premium Bandai blocks automated visits to its store pages, so card game drops come from the official card game site, which marks Premium Bandai exclusives, plus the featured items on <a href="https://p-bandai.com/us/series/onepiece-series" target="_blank" rel="noopener">Premium Bandai's One Piece page</a>.</p>`;

    main.querySelectorAll('[data-f]').forEach((b) => (b.onclick = () => { filter = b.dataset.f; store.set('events-filter', filter); draw(); }));
    const pb = main.querySelector('#pb-only');
    if (pb) pb.onclick = () => { pbOnly = !pbOnly; store.set('drops-pb', pbOnly ? '1' : '0'); draw(); };
  };
  draw();
}
