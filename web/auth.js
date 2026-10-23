'use strict';
/* Shared by the sign in, create account, setup and admin pages. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-G4S': '1' }, body: JSON.stringify(body || {}) });
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty body */ }
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Something went wrong. Try again.');
  return data;
}

function showMsg(el, kind, text) {
  el.className = 'msg ' + kind;
  el.textContent = text;
  el.hidden = false;
}

function safeNext() {
  const n = new URLSearchParams(location.search).get('next') || '/';
  return n.startsWith('/') && !n.startsWith('//') ? n : '/';   // never redirect off site
}

async function signOut() {
  try { await post('/auth/logout'); } catch (e) { /* signed out anyway */ }
  location.href = '/login';
}

// a form handler: disables the button while the request runs and shows the error
function onSubmit(form, fn) {
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const btn = $('button[type=submit]', form), msg = $('.msg', form);
    msg.hidden = true;
    btn.disabled = true;
    try { await fn(Object.fromEntries(new FormData(form)), msg); } catch (err) { showMsg(msg, 'err', err.message); }
    btn.disabled = false;
  });
}
