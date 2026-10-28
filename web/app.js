'use strict';
/* G4S fleet route audit. UI rules: docs/G4S_product_DESIGN_SYSTEM_1.md */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (n, d = 1) => n == null ? '–' : Number(n).toLocaleString('en', { maximumFractionDigits: d, minimumFractionDigits: 0 });
const fmtMin = m => { m = Math.round(m); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + String(m % 60).padStart(2, '0') + ' min'; };
const hhmm = t => new Date((t + 4 * 3600) * 1000).toISOString().slice(11, 16);   // UAE time (UTC + 4 h)
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
};
const errorOf = async r => {
  const t = await r.text();
  try { return new Error(JSON.parse(t).detail || t); } catch (e) { return new Error(t || r.statusText); }
};
const api = async p => {
  const r = await fetch(p);
  if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search); throw new Error('Sign in to continue.'); }
  if (!r.ok) throw await errorOf(r);
  return r.json();
};
async function signOut() {
  try { await fetch('/auth/logout', { method: 'POST', headers: { 'X-G4S': '1' } }); } catch (e) { /* signed out anyway */ }
  location.href = '/login';
}

const ST = {
  Validated: { icon: '✓', label: 'Validated', meaning: 'Stopped inside the geofence within 30 min of the planned time' },
  Passed: { icon: '↷', label: 'Passed', meaning: 'Drove through the geofence without stopping' },
  Out: { icon: '⏱', label: 'Out of window', meaning: 'Stopped at the site, but more than 30 min outside the planned time or on another trip' },
  Not: { icon: '✕', label: 'Not visited', meaning: 'The bus did not visit the site during the trip' },
  Repl: { icon: '🔧', label: 'Run by replacement', meaning: 'Trip run by a replacement vehicle (maintenance records)' },
};
const chip = s => `<span class="chip st-${s}">${ST[s].icon} ${ST[s].label}</span>`;
const RUNKIND = { planned: 'Planned', unplanned: 'Unplanned', yard: 'Accommodation move', workshop: 'Workshop drive' };
const duringBadge = d => `<span class="badge ${{ planned: 'b-planned', unplanned: 'b-unplanned', workshop: 'b-check' }[d.kind] || 'b-nodata'}">${esc(d.label)}</span>`;

const S = {
  meta: null, sites: [], vehicle: null, day: null, data: null,
  tab: 'route', mode: 'plan', selTrip: null, panel: null, pin: null, groupColor: {},
};

/* ---------- client wording guard: no hyphens or apostrophes in visible text ---------- */
const SKIP = new Set(['SCRIPT', 'STYLE', 'TEXTAREA', 'INPUT']);
function cleanNode(n) {
  if (n.nodeType === 3) {
    if (n.parentElement && (SKIP.has(n.parentElement.tagName) || n.parentElement.closest('[data-raw]'))) return;
    const v = n.nodeValue, c = v.replace(/(\S)\s*[-‐-—]\s*(?=\S)/g, '$1 ').replace(/['’]/g, '');
    if (c !== v) n.nodeValue = c;
  } else if (n.nodeType === 1 && !SKIP.has(n.tagName)) n.childNodes.forEach(cleanNode);
}
new MutationObserver(ms => ms.forEach(m => { m.addedNodes.forEach(cleanNode); if (m.type === 'characterData') cleanNode(m.target); }))
  .observe(document.body, { childList: true, subtree: true, characterData: true });

/* ---------- theme: Auto / Light / Dark ---------- */
const THEMES = ['auto', 'light', 'dark'];
function applyTheme(t) {
  if (t === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = t;
  $('#theme').textContent = '◐ ' + t[0].toUpperCase() + t.slice(1);
  store.set('g4s-theme', t);
  if (S.data) redrawMap();
  if (S.tab === 'mileage' && M.data) drawChart();
}
$('#theme').onclick = () => applyTheme(THEMES[(THEMES.indexOf(store.get('g4s-theme', 'auto')) + 1) % 3]);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (store.get('g4s-theme', 'auto') === 'auto') applyTheme('auto'); });

/* ---------- URL state ---------- */
function syncUrl() {
  const q = new URLSearchParams();
  if (S.vehicle) q.set('v', S.vehicle);
  if (S.day) q.set('d', S.day);
  if (S.tab !== 'route') q.set('tab', S.tab);
  history.replaceState(null, '', '?' + q);
}

/* ---------- refresh ---------- */
async function refreshGps() {
  const b = $('#refresh');
  b.disabled = true;
  b.textContent = '↻ Refreshing…';
  try {
    const r = await fetch('/api/refresh', { method: 'POST', headers: { 'X-G4S': '1' } });
    if (!r.ok) throw await errorOf(r);
    location.reload();
  } catch (e) {
    b.disabled = false;
    b.textContent = '↻ Refresh';
    $('#subtitle').textContent = 'Refresh failed, showing the earlier data. ' + e.message;
  }
}

/* ---------- boot ---------- */
async function boot() {
  applyTheme(store.get('g4s-theme', 'auto'));
  $('#refresh').onclick = refreshGps;
  try {
    S.me = await api('/api/me');
  } catch (e) {
    $('#subtitle').textContent = 'Could not load data: ' + e.message;
    return;
  }
  $('#tab-ops').classList.toggle('hidden', !S.me.ops);
  try {
    [S.meta, S.sites] = await Promise.all([api('/api/meta'), api('/api/sites')]);
  } catch (e) {
    if (S.me.ops) { opsOnly('GPS data could not load (' + e.message + '). The Operations tab still works.'); return; }
    $('#subtitle').textContent = 'Could not load data: ' + e.message;
    return;
  }
  $('#userbox').innerHTML = `${S.me.role === 'admin' ? '<a href="/admin">Accounts</a>' : ''}<span class="who" title="${esc(S.me.email)}">${esc(S.me.email)}</span>
    <button class="iconbtn" id="signout">Sign out</button>`;
  $('#signout').onclick = signOut;
  const loaded = 'Loaded at ' + new Date(S.meta.loaded_at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  $('#refresh').title = 'Fetch the latest GPS. ' + loaded;
  const live = S.meta.source === 'totalsecure';
  const src = $('#source');
  const warn = live && S.meta.token_warn_days != null;
  src.textContent = live ? '● Live Feed' : 'Spreadsheet';
  if (warn) src.textContent += ` · access expires in ${S.meta.token_warn_days} day${S.meta.token_warn_days === 1 ? '' : 's'}`;
  src.className = 'chip src' + (warn ? ' warn' : live ? ' live' : '');
  src.title = warn
    ? 'Automatic renewal of the Total Secure token is failing. See the server log, or run: python3 -m app.totalsecure token'
    : (live ? 'GPS from the Total Secure platform. ' : 'GPS from the Route export in the sheets folder. ') + loaded;
  src.hidden = false;
  S.siteById = Object.fromEntries(S.sites.map(s => [s.id, s]));
  const q = new URLSearchParams(location.search);
  const withGps = S.meta.vehicles.filter(v => v.has_gps);
  const v = S.meta.vehicles.find(x => x.vehicle === q.get('v') && x.has_gps) || withGps[0];
  $('#tab-fleet').classList.toggle('hidden', !S.meta.fleet);
  if (!v && S.meta.fleet) {   // only devices outside the plan: the Fleet tab alone
    $$('#tab-route,#tab-mileage').forEach(el => el.classList.add('hidden'));
    setTab(S.me.ops && q.get('tab') === 'ops' ? 'ops' : 'fleet');
    return;
  }
  if (!v && S.me.ops) { opsOnly(); return; }
  if (!v) {
    $('#title').textContent = 'Route audit';
    $('#subtitle').textContent = S.me.role === 'admin'
      ? (S.meta.source === 'totalsecure' ? 'No GPS data found on Total Secure for the planned vehicles in this period.' : 'No GPS data found. Add a GPS export to the sheets folder.')
      : S.meta.vehicles.length ? 'Your vehicles have no GPS data yet.' : 'No vehicles are assigned to your account yet. The admin will add them.';
    $$('.tabs,#view-route,#view-mileage').forEach(el => el.classList.add('hidden'));
    return;
  }
  S.vehicle = v.vehicle;
  const days = pickable(v), gpsDays = v.days.map(d => d.day).filter(k => days.includes(k));
  S.day = days.includes(q.get('d')) ? q.get('d') : gpsDays[gpsDays.length - 1] || days[days.length - 1];  // opens on the latest date with GPS
  fillVehicleSelect();
  initMap();
  wireRoute();
  await loadDay();
  const want = q.get('tab');
  setTab(want === 'mileage' || (want === 'fleet' && S.meta.fleet) || (want === 'ops' && S.me.ops) ? want : 'route');
}

// the operations team without GPS vehicles (or with the GPS provider down): the Operations tab alone
function opsOnly(note) {
  if (!$('#userbox').innerHTML) {
    $('#userbox').innerHTML = `${S.me.role === 'admin' ? '<a href="/admin">Accounts</a>' : ''}<span class="who" title="${esc(S.me.email)}">${esc(S.me.email)}</span>
      <button class="iconbtn" id="signout">Sign out</button>`;
    $('#signout').onclick = signOut;
  }
  $$('#tab-route,#tab-mileage').forEach(el => el.classList.add('hidden'));
  if (!S.meta || !S.meta.fleet) $('#tab-fleet').classList.add('hidden');
  O.note = note || '';
  setTab('ops');
}

function vmeta(vno = S.vehicle) { return S.meta.vehicles.find(v => v.vehicle === vno); }

function fillVehicleSelect() {
  $('#vsel').innerHTML = S.meta.vehicles.map(v => v.has_gps
    ? `<option value="${v.vehicle}">${v.vehicle} · ${esc(v.branch)} · ${v.pct ?? '–'}% stops validated</option>`
    : `<option value="${v.vehicle}" disabled>${v.vehicle} · ${esc(v.branch)} · no GPS yet</option>`).join('');
  $('#vsel').value = S.vehicle;
}

/* ---------- date picker: this month and last month only ---------- */
const CAL = { month: null };   // 'YYYY-MM' shown in the calendar
const isoDay = d => d.toISOString().slice(0, 10);
const dayDate = k => new Date(k + 'T00:00:00Z');
const nextKey = (k, n) => isoDay(new Date(dayDate(k).getTime() + n * 864e5));
const todayKey = () => S.meta.calendar.to;           // UAE today, from the server
const calRange = () => S.meta.calendar;              // previous month and this month, up to today
const isLoaded = (k, v = vmeta()) => v.days.some(d => d.day === k);
function pickable(v = vmeta()) {   // dates the calendar offers, oldest first
  const r = calRange();
  if (!r.on_demand) return v.days.map(d => d.day).filter(k => k >= r.from && k <= r.to);
  const out = [];   // Total Secure: any date, fetched when picked
  for (let k = r.from; k <= r.to; k = nextKey(k, 1)) out.push(k);
  return out;
}
const WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const dayLabel = k => { const d = dayDate(k); return `${WD[d.getUTCDay()]} ${d.getUTCDate()} ${MO[d.getUTCMonth()]}`; };
const CAL_ICON = '<svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="3" width="13" height="11.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.4"/><path d="M1.5 6.5h13M5 1.5v3M11 1.5v3" stroke="currentColor" stroke-width="1.4"/></svg>';

function fillDatePicker() {
  const days = pickable(), i = days.indexOf(S.day);
  $('#d-btn').innerHTML = CAL_ICON + (S.day ? esc(dayLabel(S.day)) : 'Choose a date');
  $('#d-prev').disabled = i <= 0;
  $('#d-next').disabled = i < 0 || i === days.length - 1;
  $('#d-prev').title = i > 0 ? 'Previous day: ' + dayLabel(days[i - 1]) : 'No earlier date with GPS';
  $('#d-next').title = i >= 0 && i < days.length - 1 ? 'Next day: ' + dayLabel(days[i + 1]) : 'No later date with GPS';
}

function renderCal() {
  const r = calRange(), has = new Set(pickable()), today = todayKey();
  const first = dayDate(CAL.month + '-01');
  const n = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
  const cells = Array(first.getUTCDay()).fill('<span></span>');   // weeks start on Sunday
  for (let d = 1; d <= n; d++) {
    const k = CAL.month + '-' + String(d).padStart(2, '0'), ok = has.has(k);
    const long = dayDate(k).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
    cells.push(`<button class="cd${k === S.day ? ' on' : ''}${k === today ? ' today' : ''}" data-d="${k}" ${ok ? '' : 'disabled'}
      aria-label="${long}${ok ? '' : ', no GPS'}"${k === S.day ? ' aria-current="date"' : ''}>${d}</button>`);
  }
  $('#cal').innerHTML = `
    <div class="calh">
      <button class="dnav" data-m="-1" aria-label="Previous month" ${CAL.month <= r.from.slice(0, 7) ? 'disabled' : ''}>‹</button>
      <b>${first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric', timeZone: 'UTC' })}</b>
      <button class="dnav" data-m="1" aria-label="Next month" ${CAL.month >= r.to.slice(0, 7) ? 'disabled' : ''}>›</button>
    </div>
    <div class="calg">${['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map(w => `<span class="wd">${w}</span>`).join('')}${cells.join('')}</div>
    <div class="caln">${calRange().on_demand ? 'Any date in this month or last month. Dates not loaded yet come from Total Secure.' : 'Dates with GPS in this month and last month.'}</div>`;
}

function openCal() {
  CAL.month = (S.day || todayKey()).slice(0, 7);
  renderCal();
  $('#cal').classList.remove('hidden');
  $('#d-btn').setAttribute('aria-expanded', 'true');
  ($('#cal .cd.on') || $('#cal .cd:not(:disabled)') || $('#cal .dnav')).focus();
}
function closeCal(focusBtn) {
  if ($('#cal').classList.contains('hidden')) return;
  $('#cal').classList.add('hidden');
  $('#d-btn').setAttribute('aria-expanded', 'false');
  if (focusBtn) $('#d-btn').focus();
}
async function goDay(k) { closeCal(); if (k && k !== S.day) { S.day = k; await loadDay(); } }

function wireDatePicker() {
  $('#d-btn').onclick = () => $('#cal').classList.contains('hidden') ? openCal() : closeCal();
  $('#d-prev').onclick = () => { const d = pickable(); goDay(d[d.indexOf(S.day) - 1]); };
  $('#d-next').onclick = () => { const d = pickable(); goDay(d[d.indexOf(S.day) + 1]); };
  $('#cal').onclick = e => {
    const b = e.target.closest('button');
    if (!b || b.disabled) return;
    if (b.dataset.d) { goDay(b.dataset.d); return; }
    const [y, m] = CAL.month.split('-').map(Number);
    CAL.month = isoDay(new Date(Date.UTC(y, m - 1 + Number(b.dataset.m), 1))).slice(0, 7);
    renderCal();
    $(`#cal .dnav[data-m="${b.dataset.m}"]`).focus();
  };
  $('#datepick').addEventListener('keydown', e => { if (e.key === 'Escape') closeCal(true); });
  // composedPath, not closest: a month change replaces the clicked button before this runs
  document.addEventListener('click', e => { if (!e.composedPath().includes($('#datepick'))) closeCal(); });
}

function setHeader() {
  if (S.tab === 'ops') {
    const d = O.data;
    $('#title').textContent = 'Operations · Vehicles and replacements';
    $('#subtitle').textContent = O.note || (d ? `${d.summary.permanent} permanent vehicles · ${d.summary.active} active replacements · ${d.replacements.length} entries logged` : 'Loading…');
    document.title = 'G4S Operations';
    return;
  }
  if (S.tab === 'fleet') {
    $('#title').textContent = 'Fleet · All GPS devices';
    $('#subtitle').textContent = F.data ? `${F.data.devices.length} device${F.data.devices.length === 1 ? '' : 's'} on Total Secure at their latest position` : 'Loading devices…';
    document.title = 'G4S Fleet';
    return;
  }
  const v = vmeta(), d = S.data;
  if (S.tab === 'route') {
    $('#title').textContent = 'Route audit · Vehicle ' + v.vehicle;
    $('#subtitle').textContent = `${v.driver} · ${v.type} · ${v.branch} · based at ${v.home} · GPS ${v.gps_from} to ${v.gps_to} vs G4S route plan`;
  } else {
    $('#title').textContent = 'Fleet route audit · Mileage & excess use';
    const n = S.meta.vehicles.filter(x => x.has_gps).length;
    $('#subtitle').textContent = `${n} vehicle${n === 1 ? '' : 's'} with GPS · GPS ${v.gps_from} to ${v.gps_to} vs G4S route plan`;
  }
  document.title = S.tab === 'route' ? `Route audit ${v.vehicle}` : 'G4S Mileage';
  if (d) {
    $('#vbadge').textContent = v.type_abbr;
    $('#vbadge').title = v.type;
    $('#vdrv').textContent = v.driver;
  }
}

function setTab(t) {
  S.tab = t;
  ['route', 'mileage', 'fleet', 'ops'].forEach(k => {
    $('#tab-' + k).setAttribute('aria-selected', t === k);
    $('#view-' + k).classList.toggle('hidden', t !== k);
  });
  if (t !== 'route' && typeof map !== 'undefined' && map) stopReplay();
  if (t === 'route') map.invalidateSize();
  if (t === 'mileage') loadMileage();
  if (t === 'fleet') loadFleet();
  if (t === 'ops') loadOps();
  setHeader();
  syncUrl();
}
$('#tab-route').onclick = () => setTab('route');
$('#tab-mileage').onclick = () => setTab('mileage');
$('#tab-fleet').onclick = () => setTab('fleet');
$('#tab-ops').onclick = () => setTab('ops');

/* ================= ROUTE CHECK ================= */
function wireRoute() {
  $('#vsel').onchange = async e => {
    S.vehicle = e.target.value;
    const v = vmeta();
    const days = pickable(v);
    if (!days.includes(S.day)) S.day = days[days.length - 1];  // keep the date when possible
    await loadDay();
  };
  wireDatePicker();
  $('#m-plan').onclick = () => setMode('plan');
  $('#m-replay').onclick = () => setMode('replay');
  $('#z-in').onclick = () => map.zoomIn();
  $('#z-out').onclick = () => map.zoomOut();
  $('#z-fit').onclick = () => fitDay();
}

async function loadDay(after) {
  fillDatePicker();
  if (!S.day) {
    $('#side').innerHTML = '<div class="empty">This vehicle has no GPS in this month or last month.</div>';
    $('#kpis').innerHTML = '';
    return;
  }
  const day = S.day;
  $('#side').innerHTML = `<div class="empty">${isLoaded(day) ? 'Loading data…' : 'Loading ' + dayLabel(day) + ' from Total Secure…'}</div>`;
  S.selTrip = null; S.panel = null; S.pin = null;
  let data;
  try {
    data = await api(`/api/vehicles/${S.vehicle}/days/${day}`);
  } catch (e) {
    if (day !== S.day) return;   // another date was picked meanwhile
    if (S.mode === 'replay') stopReplay();
    S.data = null;
    Object.values(LY).forEach(l => l.clearLayers());
    $('#kpis').innerHTML = '';
    $('#opsrc').textContent = ''; $('#opsnote').innerHTML = '';
    $('#side').innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    syncUrl();
    return;
  }
  if (day !== S.day) return;     // another date was picked meanwhile
  S.data = data;
  S.groupColor = {};
  S.data.trips.forEach(t => { if (!(t.group in S.groupColor)) S.groupColor[t.group] = Object.keys(S.groupColor).length % 9 + 1; });
  setHeader();
  renderOps();
  renderKpis();
  if (S.mode === 'replay') { setupReplay(); } else { renderSide(); }
  redrawMap(true);
  syncUrl();
  if (after) after();
}

const tripColor = t => css('--plan' + (S.groupColor[t.group] || 1));

function renderOps() {
  const r = S.data.record;
  $('#opsrc').textContent = r ? '' : 'Records: no maintenance or replacement on this day';
  $('#d-btn').classList.toggle('wk', !!(r && r.replaced_by));
  $('#opsnote').innerHTML = r
    ? `<div class="opsnote ${r.replaced_by ? 'wk' : 'rt'}">🔧 ${r.replaced_by ? 'In the workshop' : 'Back from the workshop'}${r.note ? ' (' + esc(r.note) + ')' : ''}${r.replaced_by ? ', replaced by ' + esc(r.replaced_by) : ''}.</div>`
    : '';
}

function renderKpis() {
  const k = S.data.kpi;
  const tiles = [
    { id: 'val', v: `${k.validated}<small> of ${k.with_data}</small>`, l: 'Planned stops validated',
      s: k.pct == null ? 'No stops to check' : k.pct + '% of planned stops' },
    { id: 'km', v: `${fmt(k.km)}<small> km</small>`, l: 'Actual km (GPS)',
      s: `${fmt(k.km_planned)} km on planned trips · ${fmt(k.km_unplanned)} km unplanned` },
    { id: 'trips', v: `${k.trips_run} + ${k.trips_unplanned}`, l: 'Planned + unplanned trips',
      s: `${k.trips_planned} trips in the G4S route plan`, click: k.trips_unplanned > 0 },
    { id: 'oz', v: k.outside, l: 'Stops outside geofences', s: k.outside ? `${fmtMin(k.outside_min)} in total · click to show` : 'None on this day', click: k.outside > 0 },
    { id: 'idle', v: k.idling, l: 'Idling at accommodation over 10 min', s: k.idling ? `${fmtMin(k.idling_min)} with engine on` : 'None on this day', click: k.idling > 0 },
    { id: 'spd', v: k.speeding, l: 'Speeding over 100 km/h', s: k.speeding ? `Top speed ${k.max_speed} km/h · click for table` : 'None on this day', click: k.speeding > 0 },
  ];
  $('#kpis').innerHTML = tiles.map(t => `<div class="kpi ${t.id}${t.click ? ' click' : ''}${S.panel === t.id ? ' on' : ''}" data-k="${t.id}" ${t.click ? 'role="button" tabindex="0"' : ''}>
    <div class="v">${t.v}</div><div class="l">${t.l}</div><div class="s">${t.s}</div></div>`).join('');
  $$('#kpis .kpi.click').forEach(el => {
    const go = () => el.dataset.k === 'trips' ? scrollSide('#sec-unp') : togglePanel(el.dataset.k);
    el.onclick = go;
    el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } };
  });
}

function scrollSide(sel) {
  if (S.mode !== 'plan') setMode('plan');
  const el = $(sel); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- side panel ---------- */
function renderSide() {
  const d = S.data, k = d.kpi, c = d.counts;
  const label = d.label.toUpperCase();
  const legendRows = ['Validated', 'Passed', 'Out', 'Not'].map(s =>
    `<tr><td>${chip(s)}</td><td>${ST[s].meaning}</td><td class="num">${c[s] || 0}</td></tr>`).join('');
  const trips = d.trips.map(tripCard).join('') || '<div class="empty">No planned trips for this vehicle.</div>';
  const unp = d.runs.filter(r => r.kind === 'unplanned' || r.kind === 'workshop');
  const night = [...d.trips.filter(t => t.night && t.run != null).map(t => ({ p: 1, t: t.dep, txt: `Trip ${t.n} · ${t.group}`, km: t.km })),
    ...d.runs.filter(r => r.night && r.kind === 'unplanned').map(r => ({ p: 0, t: r.dep, txt: 'Unplanned trip', km: r.km, run: r }))];
  $('#side').innerHTML = `
    <div class="totals">
      <div>Total planned trips today <b class="num">${k.trips_planned}</b></div>
      <div>Planned stop visits <b class="num">${k.planned_stops}</b></div>
    </div>
    <div class="sec"><div class="tbox"><table class="legendt"><thead><tr><th>Status</th><th>Meaning</th><th>Stops</th></tr></thead><tbody>${legendRows}</tbody></table></div></div>
    <div class="sec"><h2>Planned stops by trip · ${label}</h2>${trips}</div>
    <div class="sec" id="sec-unp"><h2>Unplanned trips · ${label}</h2>
      ${unp.length ? unp.map(runCard).join('') : '<div class="empty">No unplanned trips on this day.</div>'}</div>
    <div class="sec"><h2>At night · 22:00 to 04:00</h2>
      <div style="margin-bottom:6px"><span class="chip ahp">${night.filter(x => x.p).length} planned</span> <span class="chip ahu">${night.filter(x => !x.p).length} unplanned</span></div>
      ${night.length ? night.map(x => `<div class="srow"><span>${esc(x.txt)}</span><span class="tm">${x.t}</span><span class="num">${fmt(x.km)} km</span></div>`).join('') : '<div class="empty">No trips at night on this day.</div>'}</div>
    <div class="note">Times are UAE time (GPS UTC + 4 h). Geofences are 300 m circles (accommodation 400 m). A stop is 3 km/h or less for 30 s or more. Source: ${S.meta.source === 'xlsx' ? 'GPS tracker export' : 'GPS provider'}.</div>`;
  $$('#side .trip[data-n]').forEach(el => el.onclick = e => {
    const row = e.target.closest('.srow');
    if (row && row.dataset.lat) { flyTo(+row.dataset.lat, +row.dataset.lon, row.dataset.site); e.stopPropagation(); return; }
    selectTrip(+el.dataset.n);
  });
  $$('#side .kmbtn').forEach(b => b.onclick = () => startReplayAt(+b.dataset.t));
  $$('#side .showrun').forEach(b => b.onclick = () => frameRun(+b.dataset.run));
}

function tripCard(t) {
  const col = tripColor(t);
  const meta = [`Plan ${t.plan_start} to ${t.plan_end}`];
  if (t.replaced) meta.push('Run by replacement ' + esc(t.replaced_by || ''));
  else if (t.run != null) {
    meta.push(`Actual ${t.dep} to ${t.arr} (${t.delta})`);
    meta.push(`${fmt(t.km)} km`);
  } else meta.push('No matching GPS trip');
  if (t.staff_out != null) meta.push(`Staff ${t.staff_out} out, ${t.staff_back ?? 0} back`);
  const chain = t.chained && t.chained.length ? `<div class="meta">Same run as trip ${t.chained.join(', ')}</div>` : '';
  const rows = t.stops.map(s => `<div class="srow" data-lat="${s.lat}" data-lon="${s.lon}" data-site="${s.site}" title="Show on map">
      <span>${esc(s.label)}</span><span class="tm"${s.est ? ' title="Estimated from the odometer and the route plan"' : ''}>${s.time ? (s.est ? '≈ ' : '') + s.time + (s.dur_min ? ' · ' + fmt(s.dur_min) + ' min' : '') : (s.note ? esc(s.note) : '')}</span>${chip(s.status)}</div>`).join('');
  return `<div class="trip${S.selTrip === t.n ? ' on' : ''}${t.replaced ? ' repl' : ''}" data-n="${t.n}">
    <div class="th"><span class="sw" style="border-color:${col}"></span><span class="tn">Trip ${t.n} · ${esc(t.group)}</span>
      <span class="vc">${t.replaced ? chip('Repl') : `${t.validated} of ${t.stops.length} validated`}</span></div>
    <div class="meta">${meta.join(' · ')}</div>${chain}
    ${rows}</div>`;
}

function typeChip(type) {
  if (!type) return '';
  const c = { 'Late night': 't-night', 'Daytime': 't-day', 'Short hop': 't-hop' }[type] || 't-hop';
  return `<span class="chip ${c}">${type}</span>`;
}

function runCard(r) {
  return `<div class="runcard"><div class="rh"><span class="badge ${r.kind === 'workshop' ? 'b-check' : 'b-unplanned'}">${RUNKIND[r.kind]}</span>
    ${typeChip(r.type)}<span class="num">${r.dep} to ${r.arr}</span>
    <span style="margin-left:auto;display:flex;gap:8px"><button class="linkbtn showrun" data-run="${r.id}">Show ↗</button><button class="kmbtn" data-t="${r.t0}">${fmt(r.km)} km ▶</button></span></div>
    <p>${esc(r.comment)}</p></div>`;
}

/* ---------- map ---------- */
let map;
const LY = {};
function initMap() {
  map = L.map('map', { zoomControl: false, attributionControl: true, zoomSnap: 0.5, maxZoom: 18, minZoom: 6, preferCanvas: false });
  map.attributionControl.setPrefix(false);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(map);
  // order matters: the dashed plan sits above the actual route so both stay readable
  ['sites', 'track', 'sel', 'plan', 'stops', 'oz', 'replay'].forEach(k => LY[k] = L.layerGroup().addTo(map));
  map.setView([25.3, 55.6], 9);
}

function legend() {
  const rows = [
    `<div><i class="dash" style="border-color:${css('--plan1')}"></i>Planned route (one colour per trip group)</div>`,
    `<div><i style="border-color:${css('--act')}"></i>Actual GPS route</div>`,
    `<div><i style="border-color:${css('--act')};border-top-style:dotted"></i>Estimated route</div>`,
    `<div><i class="ring" style="border-color:${css('--fence')};background:${css('--fence-fill')}"></i>Planned geofence (300 m)</div>`,
    `<div><i class="ring" style="border-color:${css('--ink-3')};background:${css('--other-fill')}"></i>Other directory site</div>`,
    `<div><i class="dot" style="background:${css('--stop-fill')};border:1px solid ${css('--act')}"></i>Actual stop at a site</div>`,
    `<div><i class="pin" style="background:${css('--zone-line')}"></i>Stop outside geofences</div>`,
  ];
  if (S.mode === 'replay') rows.splice(1, 1,
    `<div><i style="border-color:${css('--trail-svc')}"></i>Replay trail on a planned trip</div>`,
    `<div><i style="border-color:${css('--trail-oth')}"></i>Replay trail off plan</div>`);
  $('#legend').innerHTML = rows.join('');
}

function trackSegments(track) {
  // split the track where it switches between GPS and estimated points (p[5]); the estimate is drawn dotted
  const segs = [], est = [];
  let cur = [];
  for (let i = 0; i < track.length; i++) {
    const p = track[i];
    if (i && p[5] !== track[i - 1][5]) {
      if (cur.length > 1) (track[i - 1][5] ? est : segs).push(cur);
      cur = [cur[cur.length - 1]];
    }
    cur.push([p[1], p[2]]);
  }
  if (cur.length > 1) (track[track.length - 1][5] ? est : segs).push(cur);
  return { segs, est };
}

function siteStatusToday(id) {
  const out = [];
  S.data.trips.forEach(t => t.stops.forEach(s => { if (s.site === id) out.push(`Trip ${t.n}: ${chip(s.status)}${s.time ? ' ' + s.time : ''}`); }));
  return out;
}

function redrawMap(fit) {
  if (!map || !S.data) return;
  Object.values(LY).forEach(l => l.clearLayers());
  const d = S.data, planSet = new Set(d.plan_sites), home = d.vehicle.home_ll;
  legend();
  // geofences
  S.sites.forEach(s => {
    const planned = planSet.has(s.id) || (home && Math.abs(s.lat - home[0]) < 1e-6 && Math.abs(s.lon - home[1]) < 1e-6);
    const c = L.circle([s.lat, s.lon], {
      radius: s.radius, weight: planned ? 1.5 : 1, color: planned ? css('--fence') : css('--ink-3'),
      fillColor: planned ? css('--fence') : css('--ink-3'), fillOpacity: planned ? .16 : .10, opacity: planned ? .9 : .5,
    }).addTo(LY.sites);
    const st = siteStatusToday(s.id);
    c.bindPopup(`<b>${esc(s.label)}</b><br>${s.accommodation ? 'Accommodation · 400 m' : 'Geofence · 300 m'}${st.length ? '<br>' + st.join('<br>') : planned ? '' : '<br><span class="muted">Not in this vehicle plan</span>'}`);
    c._siteId = s.id;
  });
  // planned routes
  const replay = S.mode === 'replay';
  d.trips.forEach(t => {
    const pl = d.planned_lines[t.n];
    if (!pl || !pl.line.length) return;
    const on = S.selTrip == null || S.selTrip === t.n;
    L.polyline(pl.line, { color: tripColor(t), weight: 3, dashArray: '7 7', opacity: replay ? .35 : on ? .9 : .2, interactive: false }).addTo(LY.plan);
  });
  // actual route
  const { segs, est } = trackSegments(d.track);
  segs.forEach(s => {
    L.polyline(s, { color: css('--surface'), weight: 6, opacity: replay ? .3 : .75, interactive: false }).addTo(LY.track);
    L.polyline(s, { color: css('--act'), weight: 3, opacity: replay ? .3 : .95, interactive: false }).addTo(LY.track);
  });
  est.forEach(s => L.polyline(s, { color: css('--act'), weight: 3, dashArray: '2 7', opacity: replay ? .3 : .9 })
    .bindPopup('<b>Estimated route</b><br>Rebuilt from the odometer and the G4S route plan.').addTo(LY.track));
  // actual stops at sites
  d.trips.forEach(t => t.stops.forEach(s => {
    if (!s.t || !(s.status === 'Validated' || s.status === 'Out')) return;
    const p = posAt(s.t) || [s.lat, s.lon];
    L.circleMarker(p, { radius: 5, color: css('--act'), weight: 1.5, fillColor: css('--stop-fill'), fillOpacity: 1 })
      .bindPopup(`<b>${esc(s.label)}</b><br>Trip ${t.n} · ${s.est ? '≈ ' : ''}${s.time}${s.dur_min ? ' · ' + fmt(s.dur_min) + ' min' : ''}<br>${chip(s.status)}`).addTo(LY.stops);
  }));
  if (S.panel === 'oz') drawOzPins();
  if (S.selTrip != null) drawSel();
  if (replay) drawReplayLayers();
  if (fit) fitDay();
}

function fitDay() {
  const pts = S.data.track.map(p => [p[1], p[2]]);
  if (S.data.vehicle.home_ll) pts.push(S.data.vehicle.home_ll);
  if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [30, 30], maxZoom: 15 });
}

function posAt(t) {
  const tr = S.data.track;
  if (!tr.length) return null;
  let lo = 0, hi = tr.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (tr[m][0] <= t) lo = m; else hi = m - 1; }
  return [tr[lo][1], tr[lo][2]];
}

function flyTo(lat, lon, siteId) {
  map.flyTo([lat, lon], Math.max(map.getZoom(), 15), { duration: .6 });
  if (siteId) LY.sites.eachLayer(l => { if (l._siteId === siteId) setTimeout(() => l.openPopup(), 650); });
}

function runLatLngs(id) {
  return S.data.track.filter(p => p[4] === id).map(p => [p[1], p[2]]);
}

function frameRun(id) {
  const pts = runLatLngs(id);
  LY.sel.clearLayers();
  if (pts.length) {
    L.polyline(pts, { color: css('--ink'), weight: 7, opacity: .25, interactive: false }).addTo(LY.sel);
    map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 15 });
  }
}

function selectTrip(n) {
  S.selTrip = S.selTrip === n ? null : n;
  $$('#side .trip[data-n]').forEach(el => el.classList.toggle('on', +el.dataset.n === S.selTrip));
  redrawMap(false);
  const t = S.data.trips.find(x => x.n === S.selTrip);
  if (!t) { fitDay(); return; }
  const pts = t.run != null ? runLatLngs(t.run) : [];
  t.stops.forEach(s => pts.push([s.lat, s.lon]));
  if (pts.length) map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 15 });
}

function drawSel() {
  const t = S.data.trips.find(x => x.n === S.selTrip);
  if (t && t.run != null) L.polyline(runLatLngs(t.run), { color: css('--act'), weight: 5, opacity: 1, interactive: false }).addTo(LY.sel);
}

/* ---------- drill down panels over the map ---------- */
function togglePanel(id) {
  S.panel = S.panel === id ? null : id;
  S.pin = null;
  renderKpis();
  renderPanel();
  LY.oz.clearLayers();
  if (S.panel === 'oz') { drawOzPins(); const b = S.data.outside.map(o => [o.lat, o.lon]); if (b.length) map.fitBounds(L.latLngBounds(b), { padding: [60, 60], maxZoom: 15 }); }
}

function renderPanel() {
  const el = $('#ozpanel'), d = S.data;
  if (!S.panel) { el.innerHTML = ''; return; }
  let head, rows, cls = '';
  if (S.panel === 'oz') {
    head = `Stops outside geofences · ${d.outside.length}`;
    rows = d.outside.map(o => `<div class="ozrow${S.pin === o.n ? ' on' : ''}" data-n="${o.n}" data-lat="${o.lat}" data-lon="${o.lon}">
      <span class="pinno">${o.n}</span><span>${o.time} to ${o.end}<br><span class="sm">${fmt(o.near_km)} km from ${esc(o.near)} · ${esc(o.during.label)}</span></span><b class="num">${fmt(o.dur_min)} min</b></div>`).join('');
  } else if (S.panel === 'spd') {
    cls = ' spd';
    head = `Speeding over 100 km/h · ${d.speeding.length}`;
    rows = `<table><thead><tr><th>When</th><th>Top</th><th>Driver</th><th>Where</th></tr></thead><tbody>${d.speeding.map(s =>
      `<tr class="ozrow" style="display:table-row" data-lat="${s.lat}" data-lon="${s.lon}"><td>${s.time}<br><span class="sm">${esc(s.during.label)}</span></td><td class="num">${s.max} km/h</td><td>${esc(s.driver)}</td><td>${fmt(s.near_km)} km from ${esc(s.near)}</td></tr>`).join('')}</tbody></table>`;
  } else if (S.panel === 'idle') {
    head = `Idling at accommodation · ${d.idling.length}`;
    rows = d.idling.map(i => `<div class="ozrow" style="grid-template-columns:1fr auto" data-lat="${d.vehicle.home_ll[0]}" data-lon="${d.vehicle.home_ll[1]}">
      <span>${i.time} to ${i.end}<br><span class="sm">Engine on, not moving, at ${esc(d.vehicle.home)}</span></span><b class="num">${i.dur_min} min</b></div>`).join('');
  }
  el.innerHTML = `<div class="ozpanel${cls}"><div class="hd"><b>${head}</b><button class="x" aria-label="Close">✕</button></div>${rows || '<div class="empty">Nothing in this selection.</div>'}</div>`;
  $('.x', el).onclick = () => togglePanel(S.panel);
  $$('.ozrow', el).forEach(r => r.onclick = () => {
    if (r.dataset.n) { S.pin = +r.dataset.n; renderPanel(); drawOzPins(); }
    map.flyTo([+r.dataset.lat, +r.dataset.lon], 16, { duration: .6 });
  });
}

function drawOzPins() {
  LY.oz.clearLayers();
  S.data.outside.forEach(o => {
    L.circle([o.lat, o.lon], { radius: 60, color: css('--zone-line'), weight: 1, fillColor: css('--zone-line'), fillOpacity: .32, interactive: false }).addTo(LY.oz);
    L.marker([o.lat, o.lon], { icon: L.divIcon({ className: '', html: `<div class="pinno${S.pin === o.n ? ' on' : ''}">${o.n}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }), zIndexOffset: 1000 })
      .bindPopup(`<b>Stop outside geofences #${o.n}</b><br>${o.time} to ${o.end} · ${fmt(o.dur_min)} min<br>${fmt(o.near_km)} km from ${esc(o.near)}<br>${esc(o.during.label)}`)
      .on('click', () => { S.pin = o.n; renderPanel(); })
      .addTo(LY.oz);
  });
}

/* ================= REPLAY ================= */
const R = { t: 0, t0: 0, t1: 1, playing: false, speed: 360, raf: 0, last: 0, drawn: -1, segs: [], ev: -1, km: [], callout: null };
const SPEEDS = [60, 180, 360, 900, 1800];

function setMode(m) {
  if (m === S.mode) return;
  S.mode = m;
  $('#m-plan').classList.toggle('on', m === 'plan');
  $('#m-replay').classList.toggle('on', m === 'replay');
  $('#rpbar').classList.toggle('hidden', m !== 'replay');
  $('#narr').classList.add('hidden');
  if (!S.data) return;   // date without GPS: nothing to show in either mode
  if (S.panel) togglePanel(S.panel);
  if (m === 'replay') setupReplay(); else { stopReplay(); renderSide(); }
  redrawMap(false);
  setTimeout(() => map.invalidateSize(), 0);
}

function setupReplay(startT) {
  const tr = S.data.track;
  stopReplay();
  if (!tr.length) return;
  R.t0 = tr[0][0]; R.t1 = tr[tr.length - 1][0];
  const firstRun = S.data.runs[0];
  R.t = startT ?? (firstRun ? firstRun.t0 - 300 : R.t0);
  R.drawn = -1; R.ev = -1;
  // cumulative km along the thinned track (straight line; gaps skipped)
  R.km = [0];
  for (let i = 1; i < tr.length; i++) {
    const a = tr[i - 1], b = tr[i];
    R.km.push(R.km[i - 1] + (b[0] - a[0] > 600 ? 0 : map.distance([a[1], a[2]], [b[1], b[2]]) / 1000));
  }
  $('#rp-speed').innerHTML = SPEEDS.map(s => `<button class="sbtn${s === R.speed ? ' on' : ''}" data-s="${s}">${s}×</button>`).join('');
  $$('#rp-speed .sbtn').forEach(b => b.onclick = () => { R.speed = +b.dataset.s; $$('#rp-speed .sbtn').forEach(x => x.classList.toggle('on', x === b)); });
  const sc = $('#rp-scrub');
  sc.min = R.t0; sc.max = R.t1; sc.value = R.t;
  sc.oninput = () => { R.t = +sc.value; renderReplay(true); };
  $('#rp-play').onclick = togglePlay;
  // band: green on planned trips, orange off plan
  const span = R.t1 - R.t0 || 1;
  $('#rp-band').innerHTML = S.data.runs.map(r => `<span style="left:${(r.t0 - R.t0) / span * 100}%;width:${Math.max((r.t1 - r.t0) / span * 100, .3)}%;background:${css(r.kind === 'planned' ? '--trail-svc' : '--trail-oth')}" title="${RUNKIND[r.kind]} ${r.dep} to ${r.arr}"></span>`).join('');
  const ticks = [];
  for (let h = 0; h <= 24; h += 3) {
    const t = R.t0 - ((R.t0 + 4 * 3600) % 86400) + h * 3600;
    if (t >= R.t0 && t <= R.t1) ticks.push(`<span style="left:${(t - R.t0) / span * 100}%">${String(h % 24).padStart(2, '0')}:00</span>`);
  }
  $('#rp-ticks').innerHTML = ticks.join('');
  renderEvents();
  $('#narr').classList.remove('hidden');
}

function drawReplayLayers() {
  LY.replay.clearLayers();
  R.segs = []; R.drawn = -1;
  R.bus = L.marker([0, 0], { icon: L.divIcon({ className: '', html: '<div class="bus"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }), zIndexOffset: 2000, interactive: false }).addTo(LY.replay);
  renderReplay(true);
}

function idxAt(t) {
  const tr = S.data.track;
  let lo = 0, hi = tr.length - 1;
  while (lo < hi) { const m = (lo + hi + 1) >> 1; if (tr[m][0] <= t) lo = m; else hi = m - 1; }
  return lo;
}

function interp(t) {
  const tr = S.data.track, i = idxAt(t), a = tr[i], b = tr[i + 1];
  if (!b || b[0] - a[0] > 600 || t <= a[0]) return { i, ll: [a[1], a[2]], spd: b && b[0] - a[0] <= 600 ? a[3] : 0 };
  const f = (t - a[0]) / (b[0] - a[0]);
  return { i, ll: [a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f], spd: a[3] + (b[3] - a[3]) * f };
}

const trailColor = rid => {
  if (rid < 0) return null;
  const r = S.data.runs.find(x => x.id === rid);
  return css(r && r.kind === 'planned' ? '--trail-svc' : '--trail-oth');
};

function renderReplay(jump) {
  if (!S.data || !R.bus) return;
  const tr = S.data.track, p = interp(R.t);
  // trail
  if (p.i < R.drawn || jump && p.i < R.drawn) { R.segs.forEach(s => LY.replay.removeLayer(s.pl)); R.segs = []; R.drawn = -1; }
  for (let k = R.drawn + 1; k <= p.i; k++) {
    const rid = tr[k][4], col = trailColor(rid), last = R.segs[R.segs.length - 1];
    const brk = k > 0 && tr[k][0] - tr[k - 1][0] > 600;
    if (!col) continue;
    if (!last || last.rid !== rid || brk) {
      const pl = L.polyline(k > 0 && !brk && last && tr[k - 1][4] === rid ? [[tr[k - 1][1], tr[k - 1][2]]] : [], { color: col, weight: 5, opacity: .95, interactive: false }).addTo(LY.replay);
      R.segs.push({ rid, pl });
    }
    R.segs[R.segs.length - 1].pl.addLatLng([tr[k][1], tr[k][2]]);
  }
  R.drawn = p.i;
  R.bus.setLatLng(p.ll);
  if ($('#rp-follow').checked && !map.getBounds().pad(-0.2).contains(p.ll)) map.panTo(p.ll, { animate: !jump && R.speed <= 360 });
  $('#rp-clock').textContent = hhmm(R.t);
  $('#rp-scrub').value = R.t;
  // narration
  const ev = S.data.events;
  let e = -1;
  for (let k = 0; k < ev.length; k++) if (ev[k].t <= R.t) e = k; else break;
  const run = S.data.runs.find(r => r.t0 <= R.t && R.t <= r.t1);
  const km = R.km[p.i] || 0;
  if (e !== R.ev) { R.ev = e; narrate(e, p.ll); markEvents(); }
  $('#narr .ft') && ($('#narr .ft').textContent = `${hhmm(R.t)} · ${fmt(km)} km today · ${Math.round(p.spd)} km/h`);
  const pb = $('#narr .pb i');
  if (pb) pb.style.width = run ? ((R.t - run.t0) / Math.max(run.t1 - run.t0, 1) * 100) + '%' : '0%';
}

const EVCOL = { planned: '--trail-svc', unplanned: '--trail-oth', yard: '--x2-yard', workshop: '--serious', stop: '--good', outside: '--zone-line', speed: '--x2-plan' };

function narrate(i, ll) {
  const el = $('#narr'), e = S.data.events[i];
  const draw = () => {
    if (!e) {
      el.style.borderLeftColor = css('--ink-3');
      el.innerHTML = `<b>Parked at ${esc(S.data.vehicle.home)}</b><p>Press Play or Space to start the day.</p><div class="ft"></div><div class="pb"><i></i></div>`;
    } else {
      el.style.borderLeftColor = css(EVCOL[e.kind] || '--act');
      el.innerHTML = `<b>${esc(e.title)}</b><p>${esc(e.text)}</p><div class="ft"></div><div class="pb"><i></i></div>`;
    }
    el.classList.remove('fade');
  };
  el.classList.add('fade');
  setTimeout(draw, matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 250);
  if (R.callout) { LY.replay.removeLayer(R.callout); R.callout = null; }
  if (e && $('#rp-explain').checked && R.playing) {
    const at = e.lat != null ? [e.lat, e.lon] : ll;
    R.callout = L.marker(at, { icon: L.divIcon({ className: '', html: `<div class="callout"><span class="rip"></span><span class="card">${esc(e.title)}</span></div>`, iconSize: [0, 0] }), interactive: false }).addTo(LY.replay);
    const mine = R.callout;
    setTimeout(() => { if (R.callout === mine) { LY.replay.removeLayer(mine); R.callout = null; } }, 4000);
  }
}

function renderEvents() {
  const ev = S.data.events;
  $('#side').innerHTML = `<h2>Events · ${S.data.label.toUpperCase()}</h2>
    ${ev.length ? `<ul class="evl">${ev.map((e, i) => `<li data-i="${i}"><span class="tm num">${e.time}</span><span class="dot" style="background:${css(EVCOL[e.kind] || '--act')}"></span><span>${esc(e.title)}</span></li>`).join('')}</ul>` : '<div class="empty">No movement on this day.</div>'}
    <div class="note">Space plays or pauses. Click an event to jump there.</div>`;
  $$('#side .evl li').forEach(li => li.onclick = () => { R.t = S.data.events[+li.dataset.i].t; renderReplay(true); });
}

function markEvents() {
  $$('#side .evl li').forEach(li => {
    const i = +li.dataset.i;
    li.classList.toggle('past', i < R.ev);
    li.classList.toggle('cur', i === R.ev);
  });
  const cur = $('#side .evl li.cur');
  if (cur && R.playing) cur.scrollIntoView({ block: 'nearest' });
}

function togglePlay() {
  R.playing = !R.playing;
  $('#rp-play').textContent = R.playing ? '❚❚ Pause' : '▶ Play';
  if (R.playing) {
    if (R.t >= R.t1) { R.t = R.t0; renderReplay(true); }
    R.last = performance.now();
    R.raf = requestAnimationFrame(tick);
  } else cancelAnimationFrame(R.raf);
}

function tick(now) {
  const dt = Math.min((now - R.last) / 1000, .25);
  R.last = now;
  R.t = Math.min(R.t + dt * R.speed, R.t1);
  renderReplay(false);
  if (R.t >= R.t1) { togglePlay(); return; }
  R.raf = requestAnimationFrame(tick);
}

function stopReplay() {
  if (R.playing) togglePlay();
  cancelAnimationFrame(R.raf);
}

function startReplayAt(t) {
  if (S.mode !== 'replay') setMode('replay');
  R.t = t - 120;
  renderReplay(true);
  if (!R.playing) togglePlay();
}

document.addEventListener('keydown', e => {
  if (e.code !== 'Space' || S.mode !== 'replay' || S.tab !== 'route') return;
  if (e.target.closest('input[type=text],textarea,select,button')) return;
  e.preventDefault();
  togglePlay();
});

/* ================= MILEAGE & EXCESS USE ================= */
const M = { vehicle: 'all', emirate: 'all', mode: 'daily', period: null, data: null, focus: null };
const VAL_OPTS = ['to validate', 'Approved, passenger pick up / drop off', 'Approved, client errand', 'Approved, fuel / rest break', 'Not authorised', 'Need more information'];
const valStore = () => store.get('g4s_oz_validation', {});

async function loadMileage() {
  const el = $('#mx');
  if (!M.data) el.innerHTML = '<div class="loading">Loading data…</div>';
  try {
    M.data = await api(`/api/mileage?vehicle=${M.vehicle}&emirate=${encodeURIComponent(M.emirate)}&mode=${M.mode}`);
  } catch (e) { el.innerHTML = `<div class="empty">Could not load mileage: ${esc(e.message)}</div>`; return; }
  renderMileage();
}

function inPeriod(day) {
  if (!M.period) return true;
  if (M.mode === 'daily') return day === M.period.key;
  if (M.mode === 'monthly') return day.slice(0, 7) === M.period.key;
  const d = new Date(day + 'T00:00:00Z'), k = new Date(M.period.key + 'T00:00:00Z');
  return d >= k && d < new Date(k.getTime() + 7 * 864e5);
}

function renderMileage() {
  const d = M.data, t = d.totals, vs = S.meta.vehicles;
  const emirates = [...new Set(vs.flatMap(v => v.emirates))].sort();
  const vals = valStore();
  const outside = d.outside.filter(o => inPeriod(o.day));
  const reviewed = d.outside.filter(o => vals[o.key] && vals[o.key].v && vals[o.key].v !== 'to validate').length;
  const nightN = d.unplanned.filter(r => r.night).length;
  const unMin = d.unplanned.reduce((a, r) => a + (r.t1 - r.t0) / 60, 0);
  $('#mx').innerHTML = `
    <div class="filters">
      <label class="dd">Search by vehicle <select id="mx-v" aria-label="Search by vehicle"><option value="all">All vehicles</option>
        ${vs.map(v => `<option value="${v.vehicle}" ${v.has_gps ? '' : 'disabled'}>${v.vehicle} · ${esc(v.branch)}${v.has_gps ? '' : ' · no GPS yet'}</option>`).join('')}</select></label>
      <label class="dd">Search by Emirate <select id="mx-e" aria-label="Search by Emirate"><option value="all">All emirates</option>
        ${emirates.map(e => `<option>${esc(e)}</option>`).join('')}</select></label>
      <span class="emcount">${d.vehicles.length} vehicle${d.vehicles.length === 1 ? '' : 's'}</span>
    </div>
    <div class="tiles">
      <div class="tile"><div class="l">Actual km (GPS)</div><div class="v num">${fmt(t.km, 0)} km</div>
        <span class="tl pos">${fmt(t.planned, 0)} km on planned trips</span><span class="tl neg">${fmt(t.unplanned, 0)} km unplanned</span><span class="tl">${fmt(t.other, 0)} km other moves</span></div>
      <div class="tile click" data-go="#t-unp" role="button" tabindex="0"><div class="l">Unplanned trips</div><div class="v num">${t.unplanned_trips}</div>
        <span class="tl neg">${fmt(t.unplanned, 0)} km in ${fmtMin(unMin)}</span><span class="tl neg">${nightN} at night</span><span class="tl">Open table ↗</span></div>
      <div class="tile click spd" data-go="#t-spd" role="button" tabindex="0"><div class="l">Speeding over 100 km/h</div><div class="v num">${t.speeding}</div>
        <span class="tl ${t.speeding ? 'neg' : 'pos'}">${t.speeding ? 'Top speed ' + Math.max(...d.speeding.map(s => s.max)) + ' km/h' : 'No speeding'}</span><span class="tl">Open table ↗</span></div>
      <div class="tile click" data-go="#t-oz" role="button" tabindex="0"><div class="l">Stops outside geofences</div><div class="v num">${t.outside}</div>
        <span class="tl neg">${fmtMin(t.outside_min)} in total</span><span class="tl ${reviewed === t.outside && t.outside ? 'pos' : ''}">${reviewed} reviewed</span><span class="tl">Open table ↗</span></div>
    </div>
    <div class="card">
      <div class="ch"><h3>Actual km by ${M.mode === 'daily' ? 'day' : M.mode === 'weekly' ? 'week' : 'month'}</h3>
        <div class="r"><div class="seg" role="group" aria-label="Period">${['daily', 'weekly', 'monthly'].map(m => `<button class="sbtn${M.mode === m ? ' on' : ''}" data-m="${m}">${m[0].toUpperCase() + m.slice(1)}</button>`).join('')}</div></div></div>
      <div class="chart" id="chart"></div>
      <div class="clegend"><span><i style="background:${css('--x2-svc')}"></i>Planned trips</span><span><i style="background:${css('--x2-unp')}"></i>Unplanned trips</span><span><i style="background:${css('--x2-yard')}"></i>Accommodation moves and other</span></div>
      <div class="note">Click a bar to filter the tables below to that period.</div>
    </div>
    ${M.period ? `<div style="margin-bottom:10px"><span class="fchip">Showing ${esc(M.period.label)} <button id="clr" aria-label="Clear filter">✕</button></span></div>` : ''}
    ${unplannedTable(d.unplanned.filter(r => inPeriod(r.day)))}
    ${speedingTable(d.speeding.filter(s => inPeriod(s.day)))}
    ${outsideTable(outside, vals, reviewed)}`;
  $('#mx-v').value = M.vehicle;
  $('#mx-e').value = M.emirate;
  $('#mx-v').onchange = e => { M.vehicle = e.target.value; M.period = null; loadMileage(); };
  $('#mx-e').onchange = e => { M.emirate = e.target.value; M.period = null; loadMileage(); };
  $$('#mx .seg .sbtn').forEach(b => b.onclick = () => { M.mode = b.dataset.m; M.period = null; loadMileage(); });
  $$('#mx .tile.click').forEach(el => { const go = () => $(el.dataset.go).scrollIntoView({ behavior: 'smooth' }); el.onclick = go; el.onkeydown = e => { if (e.key === 'Enter') go(); }; });
  if ($('#clr')) $('#clr').onclick = () => { M.period = null; renderMileage(); };
  $$('#mx .kmbtn').forEach(b => b.onclick = () => openRoute(b.dataset.v, b.dataset.d, () => startReplayAt(+b.dataset.t)));
  $$('#mx .show').forEach(b => b.onclick = () => openRoute(b.dataset.v, b.dataset.d, () => {
    if (S.mode !== 'plan') setMode('plan');
    if (b.dataset.oz) {
      if (S.panel !== 'oz') togglePanel('oz');
      S.pin = +b.dataset.oz; renderPanel(); drawOzPins();
    }
    map.flyTo([+b.dataset.lat, +b.dataset.lon], 16, { duration: .6 });
  }));
  $$('#mx .vsel').forEach(s => s.onchange = () => saveVal(s.dataset.k, { v: s.value }));
  $$('#mx .vcom').forEach(i => i.onchange = () => saveVal(i.dataset.k, { c: i.value }));
  if ($('#csv')) $('#csv').onclick = downloadCsv;
  drawChart();
}

function saveVal(k, patch) {
  const all = valStore();
  all[k] = Object.assign({ v: 'to validate', c: '' }, all[k], patch, { at: new Date().toISOString() });
  store.set('g4s_oz_validation', all);
  renderMileage();
}

const valClass = v => !v || v === 'to validate' ? '' : v.startsWith('Approved') ? 'ok' : v === 'Not authorised' ? 'bad' : 'info';

function unplannedTable(rows) {
  const km = rows.reduce((a, r) => a + r.km, 0);
  return `<div class="card" id="t-unp"><div class="ch"><h3>Unplanned trips</h3><span class="muted">${rows.length} trips</span></div>
    ${rows.length ? `<div class="x2wrap"><table class="x2t"><thead><tr><th>Vehicle</th><th>Day</th><th>Left</th><th>Back</th><th>Actual km</th><th>Type</th><th>Comment</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${r.vehicle}</td><td>${r.day_label}</td><td class="num">${r.dep}</td><td class="num">${r.arr}</td>
      <td><button class="kmbtn" data-v="${r.vehicle}" data-d="${r.day}" data-t="${r.t0}">${fmt(r.km)} km ▶</button></td><td>${typeChip(r.type)}</td><td class="cm">${esc(r.comment)}</td></tr>`).join('')}
    </tbody><tfoot><tr><td>Total</td><td></td><td></td><td></td><td class="num">${fmt(km)} km</td><td></td><td class="cm"></td></tr></tfoot></table></div>`
    : '<div class="empty">No unplanned trips in this selection.</div>'}</div>`;
}

function speedingTable(rows) {
  return `<div class="card" id="t-spd"><div class="ch"><h3>Speeding over 100 km/h</h3><span class="muted">${rows.length} events</span></div>
    ${rows.length ? `<div class="x2wrap"><table class="x2t"><thead><tr><th>Vehicle</th><th>When</th><th>Top speed</th><th>Driver on roster</th><th>Where</th><th>During</th><th></th></tr></thead><tbody>
    ${rows.map(s => `<tr><td>${s.vehicle}</td><td>${s.day_label} · ${s.time}</td><td class="num">${s.max} km/h</td><td>${esc(s.driver)}</td>
      <td>${fmt(s.near_km)} km from ${esc(s.near)}</td><td>${duringBadge(s.during)}</td>
      <td><button class="linkbtn show" data-v="${s.vehicle}" data-d="${s.day}" data-lat="${s.lat}" data-lon="${s.lon}">Show on map ↗</button></td></tr>`).join('')}
    </tbody></table></div>` : '<div class="empty">No speeding in this selection.</div>'}</div>`;
}

function outsideTable(rows, vals, reviewed) {
  const min = rows.reduce((a, o) => a + o.dur_min, 0);
  return `<div class="card" id="t-oz"><div class="ch"><h3>Stops outside geofences</h3><span class="muted">${rows.length} stops · ${reviewed} reviewed</span>
      <div class="r"><button class="btn" id="csv">Download CSV</button></div></div>
    ${rows.length ? `<div class="x2wrap"><table class="x2t"><thead><tr><th>#</th><th>Vehicle</th><th>When</th><th>Duration</th><th>Where</th><th>During</th><th>Validation</th><th>Comment</th><th></th></tr></thead><tbody>
    ${rows.map(o => {
      const v = vals[o.key] || {};
      return `<tr><td>${o.n}</td><td>${o.vehicle}</td><td>${o.day_label} · ${o.time}</td><td class="num">${fmt(o.dur_min)} min</td>
        <td>${fmt(o.near_km)} km from ${esc(o.near)}</td><td>${duringBadge(o.during)}</td>
        <td><select class="vsel ${valClass(v.v)}" data-k="${o.key}" aria-label="Validation">${VAL_OPTS.map(x => `<option ${x === (v.v || 'to validate') ? 'selected' : ''}>${x}</option>`).join('')}</select></td>
        <td><input class="vcom" data-k="${o.key}" value="${esc(v.c || '')}" placeholder="Comment" aria-label="Comment"></td>
        <td><button class="linkbtn show" data-v="${o.vehicle}" data-d="${o.day}" data-lat="${o.lat}" data-lon="${o.lon}" data-oz="${o.n}">Show ↗</button></td></tr>`;
    }).join('')}
    </tbody><tfoot><tr><td>Total</td><td></td><td></td><td class="num">${fmtMin(min)}</td><td></td><td></td><td></td><td></td><td></td></tr></tfoot></table></div>
    <div class="note">Answers are saved in this browser only. Download the CSV to send them back.</div>` : '<div class="empty">No stops outside geofences in this selection.</div>'}</div>`;
}

function downloadCsv() {
  const vals = valStore();
  const q = s => '"' + String(s ?? '').replace(/"/g, '""') + '"';
  const head = ['Vehicle', 'Day', 'Number', 'Start', 'End', 'Minutes', 'Latitude', 'Longitude', 'Nearest site', 'km from site', 'During', 'Validation', 'Comment'];
  const rows = M.data.outside.filter(o => inPeriod(o.day)).map(o => {
    const v = vals[o.key] || {};
    return [o.vehicle, o.day, o.n, o.time, o.end, o.dur_min, o.lat, o.lon, o.near, o.near_km, o.during.label, v.v || 'to validate', v.c || ''];
  });
  const blob = new Blob([[head, ...rows].map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'G4S stops outside geofences.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function drawChart() {
  const el = $('#chart');
  if (!el || !M.data) return;
  const bars = M.data.bars, W = Math.max(el.clientWidth, 300), H = 260, pl = 44, pr = 10, pt = 22, pb = 30;
  if (!bars.length) { el.innerHTML = '<div class="empty">No GPS in this selection.</div>'; return; }
  const max = Math.max(...bars.map(b => b.planned + b.unplanned + b.other), 1);
  const step = Math.pow(10, Math.floor(Math.log10(max))) * (max / Math.pow(10, Math.floor(Math.log10(max))) > 5 ? 2 : 1);
  const top = Math.ceil(max / step) * step;
  const y = v => pt + (H - pt - pb) * (1 - v / top);
  const bw = Math.min(64, (W - pl - pr) / bars.length * .62), gap = (W - pl - pr) / bars.length;
  const col = { planned: css('--x2-svc'), unplanned: css('--x2-unp'), other: css('--x2-yard') };
  let svg = '';
  for (let v = 0; v <= top; v += step) svg += `<line x1="${pl}" x2="${W - pr}" y1="${y(v)}" y2="${y(v)}" stroke="${css('--line')}"/><text x="${pl - 6}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="${css('--ink-3')}">${fmt(v, 0)}</text>`;
  bars.forEach((b, i) => {
    const x = pl + gap * i + (gap - bw) / 2;
    let base = 0;
    const segs = ['planned', 'unplanned', 'other'].filter(k => b[k] > 0);
    segs.forEach((k, j) => {
      const y0 = y(base), y1 = y(base + b[k]), h = y0 - y1, isTop = j === segs.length - 1;
      svg += isTop
        ? `<path d="M${x},${y0}V${y1 + 4}q0,-4 4,-4h${bw - 8}q4,0 4,4V${y0}Z" fill="${col[k]}"/>`
        : `<rect x="${x}" y="${y1}" width="${bw}" height="${h}" fill="${col[k]}"/>`;
      if (h > 16 && bw > 30) svg += `<text x="${x + bw / 2}" y="${y1 + h / 2 + 4}" text-anchor="middle" font-size="12" font-weight="700" fill="#1a1a19">${fmt(b[k], 0)}</text>`;
      base += b[k];
    });
    const sel = M.period && M.period.key === b.key;
    svg += `<text x="${x + bw / 2}" y="${y(base) - 6}" text-anchor="middle" font-size="11.5" font-weight="${sel ? 800 : 600}" fill="${css('--ink-2')}">${fmt(base, 0)}</text>`;
    svg += `<text x="${x + bw / 2}" y="${H - 10}" text-anchor="middle" font-size="11.5" font-weight="${sel ? 800 : 500}" fill="${css(sel ? '--ink' : '--ink-2')}">${esc(b.label.replace('Week of ', 'Wk '))}</text>`;
    svg += `<rect class="hit" data-i="${i}" x="${pl + gap * i}" y="${pt}" width="${gap}" height="${H - pt}" fill="transparent" style="cursor:pointer"/>`;
  });
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Actual km by period">${svg}</svg><div class="svgtip hidden"></div>`;
  const tip = $('.svgtip', el);
  $$('.hit', el).forEach(r => {
    const b = bars[+r.dataset.i];
    r.onmousemove = e => {
      const box = el.getBoundingClientRect();
      tip.innerHTML = `<b>${esc(b.label)}</b><br><span class="pl">${fmt(b.planned)} km planned trips</span><br><span class="neg">${fmt(b.unplanned)} km unplanned · ${b.unplanned_trips} trips · ${fmtMin(b.unplanned_min)}</span><br>${fmt(b.other)} km other moves`;
      tip.classList.remove('hidden');
      tip.style.left = Math.min(e.clientX - box.left + 12, box.width - tip.offsetWidth - 4) + 'px';
      tip.style.top = (e.clientY - box.top - 10) + 'px';
    };
    r.onmouseleave = () => tip.classList.add('hidden');
    r.onclick = () => { M.period = M.period && M.period.key === b.key ? null : { key: b.key, label: b.label }; renderMileage(); };
  });
}
addEventListener('resize', () => { if (S.tab === 'mileage') drawChart(); });

/* ================= FLEET ================= */
const F = { data: null, q: '', status: 'all', map: null, layer: null, marks: {}, sel: null };
const F_STATUS = { online: 'Online', offline: 'Offline', unknown: 'Unknown' };
const fColor = st => css(st === 'online' ? '--good' : st === 'offline' ? '--ink-3' : '--warn');

function ago(t) {
  if (!t) return 'never';
  const m = Math.max(0, (Date.now() / 1000 - t) / 60);
  if (m < 1) return 'just now';
  if (m < 60) return Math.round(m) + ' min ago';
  if (m < 48 * 60) return Math.round(m / 60) + ' h ago';
  return Math.round(m / 1440) + ' days ago';
}
const when = t => t ? new Date(t * 1000).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : 'never';

async function loadFleet() {
  if (!F.map) {
    F.map = L.map('fmap', { zoomControl: true, zoomSnap: 0.5, maxZoom: 18, minZoom: 5 });
    F.map.attributionControl.setPrefix(false);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19, attribution: '© OpenStreetMap contributors' }).addTo(F.map);
    F.layer = L.layerGroup().addTo(F.map);
    F.map.setView([25.2, 55.4], 8);
    $('#f-q').oninput = e => { F.q = e.target.value.trim().toLowerCase(); renderFleet(); };
    $('#f-st').onclick = e => { const b = e.target.closest('[data-st]'); if (b) { F.status = b.dataset.st; renderFleet(); } };
    $('#f-rows').onclick = e => { const b = e.target.closest('[data-id]'); if (b) selectDevice(+b.dataset.id, true); };
    F.map.on('popupopen', e => {
      const b = e.popup.getElement().querySelector('[data-route]');
      if (b) b.onclick = () => openRoute(b.dataset.route, S.day || vmeta(b.dataset.route).days.slice(-1)[0].day);
    });
  }
  setTimeout(() => F.map.invalidateSize(), 0);
  if (!F.data) $('#f-rows').innerHTML = '<div class="empty">Loading devices…</div>';
  try {
    F.data = await api('/api/fleet');
  } catch (e) {
    $('#f-rows').innerHTML = `<div class="empty">Could not load devices: ${esc(e.message)}</div>`;
    return;
  }
  setHeader();
  renderFleet(true);
}

function fleetShown() {
  const order = { online: 0, unknown: 1, offline: 2 };
  return F.data.devices
    .filter(d => F.status === 'all' || d.status === F.status)
    .filter(d => !F.q || [d.vehicle, d.name, d.category].some(x => String(x || '').toLowerCase().includes(F.q)))
    .sort((a, b) => order[a.status] - order[b.status] || a.vehicle.localeCompare(b.vehicle, 'en', { numeric: true }));
}

function devicePopup(d) {
  const canRoute = d.in_plan && d.has_gps && vmeta(d.vehicle);
  return `<div class="fpop"><b>${esc(d.vehicle)}</b>${d.category ? ` <span class="fcat">${esc(d.category)}</span>` : ''}
    <div>${F_STATUS[d.status]} · last update ${when(d.last)} (${ago(d.last)})</div>
    <div>${d.speed != null ? fmt(d.speed, 0) + ' km/h' : 'No position yet'}${d.ignition != null ? ' · engine ' + (d.ignition ? 'on' : 'off') : ''}</div>
    ${d.name !== d.vehicle ? `<div class="fsub">${esc(d.name)}</div>` : ''}
    ${canRoute ? `<button class="kmbtn" data-route="${esc(d.vehicle)}">Open in Route check ↗</button>` : d.in_plan ? '' : '<div class="fsub">Not in the G4S route plan</div>'}</div>`;
}

function renderFleet(fit) {
  const all = F.data.devices, shown = fleetShown();
  const n = { online: 0, offline: 0, unknown: 0 };
  all.forEach(d => n[d.status]++);
  $('#f-st').innerHTML = [['all', 'All', all.length], ...Object.entries(F_STATUS).map(([k, l]) => [k, l, n[k]])]
    .map(([k, l, c]) => `<button class="sbtn${F.status === k ? ' on' : ''}" data-st="${k}">${l} ${c}</button>`).join('');
  $('#f-count').textContent = shown.length === all.length ? `${all.length} devices` : `${shown.length} of ${all.length} devices`;
  $('#f-rows').innerHTML = shown.length ? shown.map(d => `
    <button class="frow${F.sel === d.id ? ' on' : ''}" data-id="${d.id}">
      <i style="background:${fColor(d.status)}"></i>
      <span class="fname"><b>${esc(d.vehicle)}</b>${d.category ? ` <span class="fcat">${esc(d.category)}</span>` : ''}${d.in_plan ? ' <span class="fplan">G4S plan</span>' : ''}</span>
      <span class="fspd">${d.speed != null && d.status === 'online' ? fmt(d.speed, 0) + ' km/h' : ''}</span>
      <span class="fsub">${F_STATUS[d.status]} · ${ago(d.last)}${d.lat == null ? ' · no position yet' : ''}</span>
    </button>`).join('') : '<div class="empty">No device matches.</div>';
  F.layer.clearLayers(); F.marks = {};
  const pts = [];
  shown.forEach(d => {
    if (d.lat == null) return;
    const m = L.circleMarker([d.lat, d.lon], { radius: 7, weight: 2, color: css('--surface'), fillColor: fColor(d.status), fillOpacity: .95 })
      .bindTooltip(esc(d.vehicle), { direction: 'top', offset: [0, -6] })
      .bindPopup(() => devicePopup(d))
      .on('click', () => selectDevice(d.id, false))
      .addTo(F.layer);
    F.marks[d.id] = m; pts.push([d.lat, d.lon]);
  });
  if (fit && pts.length) F.map.fitBounds(pts, { padding: [30, 30], maxZoom: 13 });
}

function selectDevice(id, fly) {
  F.sel = id;
  $$('#f-rows .frow').forEach(r => r.classList.toggle('on', +r.dataset.id === id));
  const r = $(`#f-rows [data-id="${id}"]`);
  if (r) r.scrollIntoView({ block: 'nearest' });
  const m = F.marks[id];
  if (m && fly) { F.map.setView(m.getLatLng(), Math.max(F.map.getZoom(), 13)); m.openPopup(); }
}

async function openRoute(vno, day, after) {
  const same = vno === S.vehicle && day === S.day && S.data;
  S.vehicle = vno; S.day = day;
  $('#vsel').value = vno;
  setTab('route');
  if (same) { if (after) after(); } else await loadDay(after);
}

/* ================= OPERATIONS ================= */
// Replaces the first two tabs of the Internal G4S Operations Sheet. Columns follow the sheet order.
const O = { data: null, view: 'replacements', q: '', status: 'all', emirate: 'all', supplier: 'all',
  sort: { replacements: { k: 'id', dir: -1 }, vehicles: { k: 'swvl_no', dir: 1 } }, edit: null, note: '', timer: 0 };
const REP_COLS = [
  ['plate', 'Permanent vehicle'], ['swvl_no', 'SWVL number'], ['vehicle_status', 'Vehicle status'], ['vehicle_type', 'Vehicle type'],
  ['replacement', 'Replacement'], ['supplier', 'Supplier'], ['replacement_date', 'Replacement date', 'd'], ['emirate', 'Emirate'],
  ['driver', 'Driver'], ['contact', 'Contact'], ['status', 'Status', 's'], ['return_date', 'Return date', 'd'],
  ['workshop_date', 'Workshop report date', 'd'], ['perm_return_date', 'Permanent vehicle return date', 'd'],
  ['workshop_days', 'Total workshop days', 'n'], ['replacement_type', 'Replacement type'], ['issue', 'Issues', 'w'],
  ['issue_date', 'Issue report date', 'd'], ['remarks', 'Remarks', 'w']];
const VEH_COLS = [
  ['supplier', 'Supplier name'], ['swvl_no', 'SWVL number'], ['agt_agreement', 'AGT agreement number'], ['g4s_agreement', 'G4S agreement number'],
  ['plate_code', 'Plate code'], ['plate', 'Plate number'], ['vehicle_type', 'Vehicle type'], ['emirate', 'Emirate'], ['driver', 'Driver'],
  ['contact', 'Contact'], ['delivery_date', 'Delivery date', 'd'], ['delivery_time', 'Time'], ['start_date', 'Start date', 'd'],
  ['vehicle_status', 'Vehicle status'], ['rental_charges', 'Rental charges', 'n'], ['now', 'Now', 'now'], ['replacements', 'Replacements', 'n'], ['notes', 'Notes', 'w']];
const OPS_FILTERS = { all: 'All', open: 'In workshop now', running: 'Active, AGT or out source', active: 'Active', outsource: 'Active out source', none: 'No replacement', closed: 'Closed' };
const opsPost = async (url, body) => {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-G4S': '1' }, body: JSON.stringify(body || {}) });
  if (r.status === 401) { location.href = '/login?next=' + encodeURIComponent('/?tab=ops'); throw new Error('Sign in to continue.'); }
  if (!r.ok) throw await errorOf(r);
  return r.json();
};
const fdate = v => /^\d{4}-\d{2}-\d{2}$/.test(v || '') ? `${+v.slice(8)} ${MO[+v.slice(5, 7) - 1]} ${v.slice(0, 4)}` : (v || '');
const statusClass = st => st === 'Active' ? 'os-act' : st === 'Active - Out Source' ? 'os-out'
  : O.data.options.no_replacement.includes(st) ? 'os-none' : 'os-done';
const plateOf = s => (String(s || '').match(/^\s*(\d+)/) || [])[1] || '';

async function loadOps(quiet) {
  const el = $('#ops');
  if (!O.data) el.innerHTML = '<div class="loading">Loading the operations log…</div>';
  try {
    O.data = await api('/api/ops');
  } catch (e) {
    if (!quiet) el.innerHTML = `<div class="empty">Could not load the operations log: ${esc(e.message)}</div>`;
    return;
  }
  setHeader();
  renderOpsTab();
  // live view: pick up what the rest of the team logs, unless a form is open
  clearInterval(O.timer);
  O.timer = setInterval(() => { if (S.tab === 'ops' && !O.edit && !document.hidden) loadOps(true); }, 60000);
}

function opsRows() {
  const d = O.data, q = O.q.toLowerCase();
  const cols = O.view === 'replacements' ? REP_COLS : VEH_COLS;
  let rows = O.view === 'replacements' ? d.replacements : d.vehicles;
  if (O.view === 'replacements') {
    const f = O.status, o = d.options;
    rows = rows.filter(r => f === 'all' || (f === 'open' && r.open) || (f === 'active' && r.status === 'Active')
      || (f === 'running' && o.active.includes(r.status))
      || (f === 'outsource' && r.status === 'Active - Out Source') || (f === 'none' && o.no_replacement.includes(r.status))
      || (f === 'closed' && !r.open));
    if (O.supplier !== 'all') rows = rows.filter(r => r.supplier === O.supplier);
  }
  if (O.emirate !== 'all') rows = rows.filter(r => r.emirate === O.emirate);
  if (q) rows = rows.filter(r => cols.some(([k]) => String(r[k] ?? '').toLowerCase().includes(q)));
  const { k, dir } = O.sort[O.view];
  const val = r => k === 'now' ? r.open.length : r[k];
  return [...rows].sort((a, b) => {
    const x = val(a), y = val(b);
    if (x === y) return (a.id - b.id) * dir;
    if (x === '' || x == null) return 1;
    if (y === '' || y == null) return -1;
    return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true })) * dir;
  });
}

function opsCell(r, [k, , t]) {
  const v = r[k];
  if (t === 's') return `<td><span class="chip ${statusClass(v)}">${esc(v)}</span></td>`;
  if (t === 'd') {
    const missing = k === 'return_date' && !v && r.replacement && !r.open;
    return `<td class="num">${missing ? '<span class="miss" title="Returned, but no return date was logged">not logged</span>' : esc(fdate(v))}</td>`;
  }
  if (t === 'n') return `<td class="num">${v == null || v === '' ? '' : esc(k === 'rental_charges' ? fmt(+v, 2) : v)}</td>`;
  if (t === 'w') return `<td class="wide" title="${esc(v)}">${esc(v)}</td>`;
  if (t === 'now') {
    const reps = r.open.map(id => O.data.replacements.find(x => x.id === id)).filter(Boolean);
    return `<td>${reps.length ? reps.map(x => `<span class="chip ${statusClass(x.status)}">In workshop${x.replacement ? ' · ' + esc(x.replacement) : ', no replacement'}</span>`).join(' ') : '<span class="muted">Running</span>'}</td>`;
  }
  return `<td>${esc(v)}</td>`;
}

function renderOpsTab() {
  const d = O.data, sm = d.summary, o = d.options, isRep = O.view === 'replacements';
  const cols = isRep ? REP_COLS : VEH_COLS, rows = opsRows(), srt = O.sort[O.view];
  const types = Object.entries(sm.by_type).map(([t, n]) => `${n} × ${esc(t)}`).join(' · ');
  const emLines = sm.by_emirate.map(e => `<span class="tl">${esc(e.emirate)}: ${e.replacement} AGT${e.outsource ? ` + ${e.outsource} out source` : ''}</span>`).join('');
  $('#ops').innerHTML = `
    <div class="tiles otiles">
      <div class="tile click" data-f="running" role="button" tabindex="0"><div class="l">Active replacements</div><div class="v num">${sm.active}</div>
        <span class="tl"><b class="num">${sm.replacement}</b> replacement from ${esc(o.main_supplier)} · <b class="num">${sm.outsource}</b> out source</span>${emLines}</div>
      <div class="tile click" data-f="none" role="button" tabindex="0"><div class="l">In workshop, no replacement</div><div class="v num">${sm.waiting}</div>
        <span class="tl ${sm.waiting ? 'neg' : 'pos'}">${sm.waiting ? 'Trips at risk until a vehicle is provided' : 'Every vehicle in the workshop is covered'}</span></div>
      <div class="tile click" data-f="open" role="button" tabindex="0"><div class="l">In the workshop now</div><div class="v num">${sm.in_workshop}</div>
        <span class="tl">${sm.avg_days != null ? `${sm.avg_days} days on average · longest ${sm.max_days} days` : 'None'}</span></div>
      <div class="tile click" data-view="vehicles" role="button" tabindex="0"><div class="l">Permanent vehicles</div><div class="v num">${sm.permanent}</div>
        <span class="tl">${types}</span></div>
      <div class="tile"><div class="l">Logged this month</div><div class="v num">${sm.this_month}</div>
        <span class="tl">Replacement or issue dated this month</span></div>
    </div>
    <div class="card ocard">
      <div class="ch">
        <div class="seg" role="group" aria-label="Table">
          <button class="sbtn${isRep ? ' on' : ''}" data-view="replacements">Replacement vehicles · ${d.replacements.length}</button>
          <button class="sbtn${isRep ? '' : ' on'}" data-view="vehicles">Permanent vehicles · ${d.vehicles.length}</button>
        </div>
        <div class="r"><button class="btn" id="o-csv">Download CSV</button>
          <button class="btn ok" id="o-new">${isRep ? '+ Log replacement' : '+ Add vehicle'}</button></div>
      </div>
      <div class="filters ofilters">
        <input type="search" id="o-q" placeholder="Search plate, SWVL number, driver, issue…" aria-label="Search" value="${esc(O.q)}">
        ${isRep ? `<label class="dd">Status <select id="o-st">${Object.entries(OPS_FILTERS).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select></label>
          <label class="dd">Supplier <select id="o-sup"><option value="all">All suppliers</option>${o.suppliers.map(x => `<option>${esc(x)}</option>`).join('')}</select></label>` : ''}
        <label class="dd">Emirate <select id="o-em"><option value="all">All emirates</option>${o.emirates.map(x => `<option>${esc(x)}</option>`).join('')}</select></label>
        <span class="muted">${rows.length === (isRep ? d.replacements : d.vehicles).length ? rows.length + ' rows' : `${rows.length} of ${(isRep ? d.replacements : d.vehicles).length} rows`} · click a row to edit</span>
      </div>
      ${rows.length ? `<div class="x2wrap owrap"><table class="opst"><thead><tr>${cols.map(([k, l]) =>
        `<th data-k="${k}" aria-sort="${srt.k === k ? (srt.dir > 0 ? 'ascending' : 'descending') : 'none'}">${esc(l)}${srt.k === k ? (srt.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(r => `<tr data-id="${r.id}" tabindex="0" class="${r.open ? 'isopen' : ''}">${cols.map(c => opsCell(r, c)).join('')}</tr>`).join('')}</tbody></table></div>`
        : '<div class="empty">No rows match these filters.</div>'}
    </div>`;
  if (isRep) { $('#o-st').value = O.status; $('#o-sup').value = O.supplier; }
  $('#o-em').value = O.emirate;
  $('#o-q').oninput = e => { O.q = e.target.value; const at = e.target.selectionStart; renderOpsTab(); const i = $('#o-q'); i.focus(); i.setSelectionRange(at, at); };
  if (isRep) {
    $('#o-st').onchange = e => { O.status = e.target.value; renderOpsTab(); };
    $('#o-sup').onchange = e => { O.supplier = e.target.value; renderOpsTab(); };
  }
  $('#o-em').onchange = e => { O.emirate = e.target.value; renderOpsTab(); };
  $$('#ops [data-view]').forEach(b => b.onclick = () => { O.view = b.dataset.view; renderOpsTab(); });
  $$('#ops .tile[data-f]').forEach(t => {
    const go = () => { O.view = 'replacements'; O.status = t.dataset.f; renderOpsTab(); };
    t.onclick = go; t.onkeydown = e => { if (e.key === 'Enter') go(); };
  });
  $$('#ops .tile[data-view]').forEach(t => t.onkeydown = e => { if (e.key === 'Enter') t.click(); });
  $$('#ops th[data-k]').forEach(th => th.onclick = () => {
    const s = O.sort[O.view];
    O.sort[O.view] = s.k === th.dataset.k ? { k: s.k, dir: -s.dir } : { k: th.dataset.k, dir: 1 };
    renderOpsTab();
  });
  $$('#ops tbody tr').forEach(tr => {
    tr.onclick = () => openEditor(O.view, +tr.dataset.id);
    tr.onkeydown = e => { if (e.key === 'Enter') openEditor(O.view, +tr.dataset.id); };
  });
  $('#o-new').onclick = () => openEditor(O.view, null);
  $('#o-csv').onclick = () => opsCsv(cols, rows);
}

function opsCsv(cols, rows) {
  const q = s => '"' + String(s ?? '').replace(/"/g, '""') + '"';
  const val = (r, k) => k === 'now' ? (r.open.length ? 'In workshop' : 'Running') : r[k];
  const blob = new Blob([[cols.map(c => c[1]), ...rows.map(r => cols.map(([k]) => val(r, k)))].map(r => r.map(q).join(',')).join('\n')], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = O.view === 'replacements' ? 'G4S replacement vehicles.csv' : 'G4S permanent vehicles.csv';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ---------- log and edit form ---------- */
const fld = (name, label, v, type = 'text', extra = '') =>
  `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${esc(v ?? '')}" ${extra}></label>`;
const selFld = (name, label, v, opts, blank) =>
  `<label class="field"><span>${label}</span><select name="${name}">${blank ? `<option value="">${blank}</option>` : ''}${
    [...new Set([...(v && !opts.includes(v) ? [v] : []), ...opts])].map(x => `<option ${x === v ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>`;

function openEditor(tab, id) {
  const d = O.data, o = d.options;
  const row = id ? (tab === 'replacements' ? d.replacements : d.vehicles).find(r => r.id === id) : null;
  if (id && !row) return;
  O.edit = { tab, id, updated_at: row ? row.updated_at : null };
  const r = row || (tab === 'replacements'
    ? { supplier: o.main_supplier, status: 'Active', replacement_date: d.today, workshop_date: d.today, issue_date: d.today }
    : { supplier: 'Al Ghazal', vehicle_status: 'Brand New' });
  const title = tab === 'replacements' ? (row ? `Replacement for ${row.plate}` : 'Log a replacement') : (row ? `Vehicle ${row.plate}` : 'Add a permanent vehicle');
  const body = tab === 'replacements' ? `
      <h2>Permanent vehicle</h2>
      ${fld('plate', 'Plate number of the permanent vehicle', r.plate, 'text', 'list="dl-plates" required autocomplete="off"')}
      <div class="vinfo" id="vinfo"></div>
      <details class="snap"${row ? '' : ' hidden'}><summary>Vehicle details on this entry</summary>
        <div class="fgrid">${fld('swvl_no', 'SWVL number', r.swvl_no)}${fld('driver', 'Driver', r.driver)}${fld('contact', 'Contact', r.contact)}
        ${selFld('emirate', 'Emirate', r.emirate, o.emirates, 'Not set')}${selFld('vehicle_type', 'Vehicle type', r.vehicle_type, o.vehicle_types, 'Not set')}
        ${selFld('vehicle_status', 'Vehicle status', r.vehicle_status, o.vehicle_statuses, 'Not set')}</div></details>
      <h2>Issue and workshop</h2>
      <div class="fgrid">${fld('issue', 'Issue', r.issue, 'text', 'list="dl-issues" autocomplete="off"')}${fld('issue_date', 'Issue report date', r.issue_date, 'date')}
      ${fld('workshop_date', 'Workshop report date', r.workshop_date, 'date')}${fld('perm_return_date', 'Permanent vehicle return date', r.perm_return_date, 'date')}</div>
      <h2>Replacement</h2>
      <div class="fgrid">${fld('supplier', 'Supplier', r.supplier, 'text', 'list="dl-sup" autocomplete="off"')}${fld('replacement', 'Replacement plate number', r.replacement)}
      ${fld('replacement_date', 'Replacement date', r.replacement_date, 'date')}${fld('return_date', 'Return date', r.return_date, 'date')}</div>
      ${selFld('status', 'Status', r.status, o.statuses)}
      <div class="btnrow"><button type="button" class="btn" id="f-ret">Mark returned today</button><span class="calc" id="f-calc"></span></div>
      <label class="field"><span>Remarks</span><textarea name="remarks" rows="3">${esc(r.remarks)}</textarea></label>
      <datalist id="dl-plates">${d.vehicles.map(v => `<option value="${esc(v.plate)}">${esc(v.swvl_no)} · ${esc(v.driver)}</option>`).join('')}</datalist>
      <datalist id="dl-issues">${o.issues.map(x => `<option value="${esc(x)}">`).join('')}</datalist>
      <datalist id="dl-sup">${o.suppliers.map(x => `<option value="${esc(x)}">`).join('')}</datalist>` : `
      <div class="fgrid">${fld('plate', 'Plate number', r.plate, 'text', 'required')}${fld('plate_code', 'Plate code', r.plate_code)}
      ${fld('swvl_no', 'SWVL number', r.swvl_no)}${fld('supplier', 'Supplier name', r.supplier)}
      ${fld('agt_agreement', 'AGT agreement number', r.agt_agreement)}${fld('g4s_agreement', 'G4S agreement number', r.g4s_agreement)}
      ${selFld('vehicle_type', 'Vehicle type', r.vehicle_type, o.vehicle_types, 'Not set')}${selFld('emirate', 'Emirate', r.emirate, o.emirates, 'Not set')}
      ${fld('driver', 'Driver', r.driver)}${fld('contact', 'Contact', r.contact)}
      ${fld('delivery_date', 'Delivery date', r.delivery_date, 'date')}${fld('delivery_time', 'Delivery time', r.delivery_time, 'time')}
      ${fld('start_date', 'Start date', r.start_date, 'date')}${selFld('vehicle_status', 'Vehicle status', r.vehicle_status, o.vehicle_statuses, 'Not set')}
      ${fld('rental_charges', 'Rental charges', r.rental_charges, 'text', 'inputmode="decimal"')}</div>
      <label class="field"><span>Notes</span><textarea name="notes" rows="3">${esc(r.notes)}</textarea></label>`;
  $('#drawer').innerHTML = `
    <div class="dhd"><h3 id="dr-h">${esc(title)}</h3><button class="x" id="dr-x" aria-label="Close">✕</button></div>
    <form id="dr-f" novalidate><div class="dbody">
      ${row ? `<div class="stamp">Logged by ${esc(row.created_by)} · ${when(row.created_at)}${row.updated_at !== row.created_at ? `<br>Last edit by ${esc(row.updated_by)} · ${when(row.updated_at)}` : ''}</div>` : ''}
      <div class="msg" hidden></div>${body}
      ${row ? '<h2>Change history</h2><div class="hist" id="dr-hist"><div class="muted">Loading…</div></div>' : ''}
    </div>
    <div class="dft"><button class="btn ok" type="submit">${row ? 'Save changes' : tab === 'replacements' ? 'Log replacement' : 'Add vehicle'}</button>
      <button class="btn" type="button" id="dr-cancel">Cancel</button>
      ${row ? '<button class="btn no" type="button" id="dr-del">Delete</button>' : ''}</div></form>`;
  $('#drawer').classList.remove('hidden'); $('#dr-bg').classList.remove('hidden');
  const f = $('#dr-f');
  $('#dr-x').onclick = $('#dr-cancel').onclick = $('#dr-bg').onclick = closeEditor;
  if (row) {
    $('#dr-del').onclick = () => deleteRow(tab, id);
    api(`/api/ops/${tab}/${id}/history`).then(h => { const el = $('#dr-hist'); if (el) el.innerHTML = histHtml(h.history); }).catch(() => {});
  }
  if (tab === 'replacements') wireRepForm(f, !row);
  f.onsubmit = e => { e.preventDefault(); saveRow(f); };
  setTimeout(() => $('input:not([type=hidden])', f).focus(), 0);
}

function wireRepForm(f, isNew) {
  const d = O.data, o = d.options, F = n => f.elements[n];
  const info = () => {
    const p = plateOf(F('plate').value), v = d.vehicles.find(x => x.plate === p);
    const open = d.replacements.filter(x => plateOf(x.plate) === p && x.open && x.id !== O.edit.id);
    $('#vinfo').innerHTML = !F('plate').value ? '' : v
      ? `<b>${esc(v.swvl_no)}</b> · ${esc(v.driver)} · ${esc(v.contact)}<br>${esc(v.vehicle_type)} · ${esc(v.emirate)} · ${esc(v.vehicle_status)}`
        + (open.length ? `<div class="warnline">Already in the workshop: ${open.map(x => `${esc(x.status)} since ${fdate(x.replacement_date || x.workshop_date)}`).join('; ')}. Edit that entry if it is the same visit.</div>` : '')
      : '<div class="warnline">Not in the permanent vehicle directory. Check the plate, or add the vehicle first.</div>';
    if (isNew && v) ['swvl_no', 'driver', 'contact', 'emirate', 'vehicle_type', 'vehicle_status'].forEach(k => { F(k).value = v[k]; });
  };
  // the status follows the supplier: AGT is a replacement, anyone else is out source
  const syncStatus = () => {
    const out = F('supplier').value.trim() && F('supplier').value.trim().toUpperCase() !== o.main_supplier.toUpperCase();
    const st = F('status').value;
    if (st.startsWith('Active')) F('status').value = out ? 'Active - Out Source' : 'Active';
    else if (st === 'Returned' || st === 'Returned - Out Source') F('status').value = out ? 'Returned - Out Source' : 'Returned';
    calc();
  };
  const calc = () => {
    const w = F('workshop_date').value, pr = F('perm_return_date').value;
    const days = w ? Math.round((new Date(pr || d.today) - new Date(w)) / 864e5) : null;
    const sup = F('supplier').value.trim(), st = F('status').value;
    const type = ['Vehicle Not Recovered - Replacement Not Provided', 'Reported To The Workshop - No Replacement'].includes(st) ? 'Reported To Workshop - No Replacement'
      : !sup && !F('replacement').value.trim() ? 'Replacement Was Not Arranged' : sup.toUpperCase() === o.main_supplier.toUpperCase() ? 'Provided By AGT' : 'Out Source Replacement';
    $('#f-calc').textContent = `${type}${days != null ? ` · ${days} workshop day${days === 1 ? '' : 's'}` : ''}`;
  };
  F('plate').oninput = info;
  F('supplier').oninput = syncStatus;
  ['status', 'workshop_date', 'perm_return_date', 'replacement'].forEach(n => F(n).addEventListener('input', calc));
  $('#f-ret').onclick = () => {
    const out = F('status').value.includes('Out Source') || (F('supplier').value.trim() && F('supplier').value.trim().toUpperCase() !== o.main_supplier.toUpperCase());
    F('status').value = F('replacement').value.trim() ? (out ? 'Returned - Out Source' : 'Returned') : 'Returned From Workshop - Fixed';
    if (!F('return_date').value && F('replacement').value.trim()) F('return_date').value = d.today;
    if (!F('perm_return_date').value) F('perm_return_date').value = d.today;
    calc();
  };
  info(); calc();
}

function histHtml(h) {
  if (!h.length) return '<div class="muted">No changes yet.</div>';
  const lbl = Object.fromEntries([...REP_COLS, ...VEH_COLS]);
  return h.map(e => `<div class="hrow2"><div class="muted">${when(e.at)} · ${esc(e.user)} · ${esc(e.action)}</div>
    ${e.action === 'edited' ? Object.entries(e.changes).map(([k, [a, b]]) => `<div>${esc(lbl[k] || k)}: <s>${esc(fdate(a) || 'empty')}</s> → <b>${esc(fdate(b) || 'empty')}</b></div>`).join('') : ''}</div>`).join('');
}

function closeEditor() {
  O.edit = null;
  $('#drawer').classList.add('hidden'); $('#dr-bg').classList.add('hidden');
  $('#drawer').innerHTML = '';
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && O.edit) closeEditor(); });

async function saveRow(f) {
  const msg = $('.msg', f), btn = $('button[type=submit]', f);
  const body = Object.fromEntries(new FormData(f));
  if (!body.plate.trim()) { showOpsMsg(msg, 'The plate number is required.'); f.elements.plate.focus(); return; }
  body.updated_at = O.edit.updated_at;
  btn.disabled = true;
  try {
    const { tab, id } = O.edit;
    await opsPost(id ? `/api/ops/${tab}/${id}` : `/api/ops/${tab}`, body);
    closeEditor();
    await loadOps();
  } catch (e) { showOpsMsg(msg, e.message); btn.disabled = false; }
}

async function deleteRow(tab, id) {
  const r = (tab === 'replacements' ? O.data.replacements : O.data.vehicles).find(x => x.id === id);
  if (!confirm(`Delete this ${tab === 'replacements' ? 'replacement entry' : 'vehicle'} (${r.plate})? It stays in the change history.`)) return;
  try {
    await opsPost(`/api/ops/${tab}/${id}/delete`);
    closeEditor();
    await loadOps();
  } catch (e) { showOpsMsg($('#dr-f .msg'), e.message); }
}

function showOpsMsg(el, text) {
  el.className = 'msg err'; el.textContent = text; el.hidden = false;
  el.scrollIntoView({ block: 'nearest' });
}

boot();
