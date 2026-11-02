// Offline dashboard security regression: untrusted archive/API strings stay inert.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'templates/index.html'), 'utf8');
const match = html.match(/<script>([\s\S]*?)<\/script>/);
assert.ok(match, 'Expected dashboard script');
class Element {
  constructor(tag = 'div') { this.tag = tag; this.children = []; this.style = {}; this._text = ''; this.disabled = false; }
  set innerHTML(_) { throw new Error('Untrusted HTML interpolation is forbidden'); }
  get textContent() { return this._text; }
  set textContent(value) { this._text = String(value); this.children = []; }
  appendChild(child) { this.children.push(child); return child; }
}
const ids = ['auto-status','auto-summary','auto-table','auto-experiments',
  'auto-errors','auto-interpretation','val-last-run','val-status',
  'val-cycles','val-threshold','results','run','message'];
const nodes = Object.fromEntries(ids.map(id => [id, new Element()]));
const listeners = {};
const intervals = [];
const requests = [];
let clockMs = 0;
class FakeDate extends Date { static now() { return clockMs; } }
const document = {
  hidden: false,
  addEventListener(event, fn) { listeners[event] = fn; },
  getElementById(id) { assert.ok(nodes[id], 'Unexpected DOM lookup: ' + id); return nodes[id]; },
  createElement(tag) { return new Element(tag); },
};
const hostile = '<img src=x onerror=alert(1)>';
let archive = [{
  time: '2026-11-01T18:00:00Z', status: hostile, z_threshold: 3.29,
  interpretation: hostile, errors: [{ name: hostile, error: 'private diagnostic' }],
  experiments: [{
    name: hostile, description: hostile, category: 'discovery',
    observed: hostile, expected: 0.5, z_score: 0.1, trials: 1000, flag: true,
  }],
}];
let results = [{
  created: hostile, trials: 20000, estimate: 3.14,
  expected: 3.14159, deviation: 0.00159, status: hostile,
}];
let failArchive = false;
let hangGitHub = false;
let hangFallback = false;
const fetch = async (url, options) => {
  requests.push({url, options});
  const shouldHang = (hangGitHub && url.startsWith('https://raw.githubusercontent.com/')) ||
    (hangFallback && url === '/api/research');
  if (shouldHang) {
    if (url === '/api/research') hangFallback = false;
    else hangGitHub = false;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('Timed out')), { once: true });
    });
  }
  if (url === '/api/research') return { ok: !failArchive, json: async () => archive };
  if (url.startsWith('https://raw.githubusercontent.com/'))
    return { ok: !failArchive, json: async () => archive };
  if (url === '/api/results') return { ok: true, json: async () => results };
  if (url === '/api/run') return { ok: true, json: async () => ({ estimate: 3.14, deviation: 0.00159 }) };
  throw Error('Unexpected fetch ' + url);
};
const timeoutTasks = [];
const fakeSetTimeout = (fn, ms) => {
  const task = { fn, ms, active: true };
  timeoutTasks.push(task);
  return task;
};
const fakeClearTimeout = task => { task.active = false; };
const context = {
  document, fetch, Date: FakeDate, AbortController,
  setInterval: (fn, ms) => intervals.push({fn, ms}),
  setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout,
};
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  vm.runInNewContext(match[1], context);
  await settle();
  const archiveRequests = () => requests.filter(x => x.url.startsWith('https://raw.githubusercontent.com/'));
  assert.equal(archiveRequests().length, 1, 'Load GitHub archive first, not stale deployed copy');
  assert.equal(archiveRequests()[0].url, 'https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity/main/data/research.json');
  assert.equal(archiveRequests()[0].options.cache, 'default', 'Allow browser caching');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].ms, 300000, 'Refresh at most every five minutes');
  assert.equal(typeof listeners.visibilitychange, 'function');
  await context.loadAuto();
  assert.equal(archiveRequests().length, 1, 'Repeated visible refresh is throttled');
  document.hidden = true;
  clockMs += 300000;
  await context.loadAuto();
  assert.equal(archiveRequests().length, 1, 'Hidden tabs must not poll');
  document.hidden = false;
  listeners.visibilitychange();
  await settle();
  assert.equal(archiveRequests().length, 2, 'Resume when tab is visible after interval');
  const status = nodes['val-status'].children[0];
  assert.equal(status.textContent, hostile, 'Untrusted status must remain inert text');
  assert.equal(nodes['auto-experiments'].children.length, 1);
  const cells = nodes['auto-experiments'].children[0].children;
  assert.equal(cells.length, 7);
  assert.equal(cells[0].textContent, hostile, 'Experiment name must remain inert');
  assert.equal(cells[1].textContent, 'Unverified candidate', 'Never label synthetic category as discovery');
  assert.equal(cells[2].textContent, hostile, 'Observed value must remain inert');
  assert.equal(nodes['auto-errors'].children[0].children[1].children[0].textContent, hostile);
  assert.equal(nodes['auto-interpretation'].textContent, hostile);
  assert.equal(nodes.results.children[0].children[0].textContent, hostile.slice(0, 19), 'Date field stays inert even when truncated');
  assert.equal(nodes.results.children[0].children[5].textContent, hostile);

  // A missing archive must not leave a stale "completed" dashboard visible.
  failArchive = true;
  clockMs += 300000;
  await context.loadAuto();
  assert.equal(nodes['auto-summary'].style.display, 'none');
  assert.equal(nodes['auto-experiments'].children.length, 0);
  assert.equal(nodes['auto-errors'].children.length, 0);
  assert.ok(nodes['auto-status'].textContent.includes('unavailable'));

  // A stalled GitHub request must abort and use the bounded server snapshot fallback.
  failArchive = false;
  hangGitHub = true;
  clockMs += 300000;
  const primaryPending = context.loadAuto();
  await settle();
  const primaryTimeout = timeoutTasks.at(-1);
  assert.equal(primaryTimeout.ms, 15000, 'GitHub archive request must be bounded');
  assert.equal(primaryTimeout.active, true);
  primaryTimeout.fn();
  await primaryPending;
  assert.equal(primaryTimeout.active, false);
  assert.ok(nodes['auto-status'].textContent.includes('snapshot'),
    'GitHub timeout should allow a clearly labeled server snapshot');
  const fallbackRequest = requests.at(-1);
  assert.equal(fallbackRequest.url, '/api/research');
  assert.ok(fallbackRequest.options.signal, 'Fallback must also be abortable');
  assert.equal(timeoutTasks.at(-1).active, false, 'Fallback timer must be cleared');

  // If both sources hang, neither the lock nor stale data may survive the timeout.
  hangGitHub = true;
  hangFallback = true;
  clockMs += 300000;
  const bothPending = context.loadAuto();
  await settle();
  const firstTimeout = timeoutTasks.at(-1);
  firstTimeout.fn();
  await settle();
  const secondTimeout = timeoutTasks.at(-1);
  assert.notEqual(secondTimeout, firstTimeout, 'Fallback gets its own timeout');
  assert.equal(secondTimeout.ms, 15000);
  secondTimeout.fn();
  await bothPending;
  assert.equal(secondTimeout.active, false);
  assert.equal(nodes['auto-summary'].style.display, 'none');
  assert.equal(nodes['auto-experiments'].children.length, 0);
  assert.ok(nodes['auto-status'].textContent.includes('unavailable'));

  // A subsequent scheduled refresh must recover after the stalled requests.
  clockMs += 300000;
  await context.loadAuto();
  assert.ok(nodes['auto-status'].textContent.includes('Latest available GitHub archive.'));

  // Malformed demo rows must show a safe error instead of partial rendering.
  results = [{ created: hostile, trials: 20000, estimate: 'invalid', expected: 3.14, deviation: 0, status: hostile }];
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent, 'Interactive results temporarily unavailable.');

  console.log('Dashboard DOM security PASS: hostile archive/API text inert, no HTML interpolation, safe failure reset.');
})().catch(error => { console.error(error); process.exitCode = 1; });
