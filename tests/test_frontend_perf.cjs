// Behavioral tests for the inline research archive polling logic.
// No external network, packages, production writes, or secrets required.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const scripts = [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.ok(scripts.length >= 1, 'Research page must have inline scripts');
const script = scripts[0][1];

const requests = [];
const listeners = {};
const intervals = [];
const nodes = {
  'auto-status': { textContent: '' },
  'auto-results': {
    _text: '', entries: [],
    get textContent() { return this._text; },
    set textContent(value) { this._text = value; if (value === '') this.entries = []; },
    appendChild(item) { this.entries.push(item); },
  },
};
const document = {
  hidden: false,
  getElementById(id) {
    assert.ok(nodes[id], 'Unexpected DOM lookup: ' + id);
    return nodes[id];
  },
  createElement(tag) {
    assert.equal(tag, 'p');
    return { textContent: '' };
  },
  addEventListener(event, fn) { listeners[event] = fn; },
};
let archiveResponse = [{
  time: '2026-10-31T00:00:00Z', status: 'completed', errors: [],
  experiments: [{ name: 'Known baseline', observed: 3.14, expected: 3.14159, z_score: 0.12, flag: false }],
}];
let fetchFailure = false;
let hangNext = false;
const fakeFetch = async (url, options) => {
  requests.push({ url, options });
  if (hangNext) {
    hangNext = false;
    return new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('Timed out')), { once: true });
    });
  }
  if (fetchFailure) throw new Error('Network unavailable');
  return {
    ok: true,
    json: async () => archiveResponse,
  };
};
const fakeInterval = (fn, ms) => { intervals.push({ fn, ms }); };
const timeoutTasks = [];
const fakeSetTimeout = (fn, ms) => {
  const task = { fn, ms, active: true };
  timeoutTasks.push(task);
  return task;
};
const fakeClearTimeout = task => { task.active = false; };
let clockMs = 0;
class FakeDate extends Date { static now() { return clockMs; } }
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  vm.runInNewContext(script, { document, fetch: fakeFetch, setInterval: fakeInterval, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout, AbortController, Date: FakeDate });
  await settle();

  assert.equal(requests.length, 1, 'Should load once at startup');
  assert.equal(requests[0].url, 'https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity/main/data/research.json',
    'Archive URL should be stable so browser caches can work');
  assert.equal(requests[0].options.cache, 'default', 'Do not bypass caching');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].ms, 300000, 'Do not fetch more often than every 5 minutes');
  assert.equal(typeof listeners.visibilitychange, 'function');
  assert.ok(nodes['auto-status'].textContent.includes('Status: completed'));
  assert.ok(nodes['auto-status'].textContent.includes('Latest archived cycle'));
  assert.equal(nodes['auto-results'].entries.length, 1);

  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 1, 'Do not re-fetch before five minutes elapsed');

  document.hidden = true;
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 1, 'No refresh requests in hidden tabs');

  archiveResponse = [{
    time: '2026-10-31T01:00:00Z', status: 'partial_failure',
    experiments: [], errors: [{ name: 'Coin sample', error: 'private diagnostic' }],
  }];
  document.hidden = false;
  listeners.visibilitychange();
  await settle();
  assert.equal(requests.length, 2, 'Resume refresh after five minutes while hidden');
  assert.ok(nodes['auto-status'].textContent.includes('Status: partial_failure'),
    'A partially failed cycle must not be labeled completed');
  assert.ok(nodes['auto-status'].textContent.includes('1 recorded errors'));
  assert.equal(nodes['auto-results'].entries.length, 1, 'Display error summary without fake experiments');
  assert.ok(nodes['auto-results'].entries[0].textContent.includes('Coin sample'));
  assert.ok(!nodes['auto-results'].entries[0].textContent.includes('private diagnostic'),
    'Do not render arbitrary error details in the page');

  listeners.visibilitychange();
  await settle();
  assert.equal(requests.length, 2, 'Rapid tab switching must not bypass five-minute throttle');

  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 3, 'Continue scheduled refresh while visible');

  clockMs += 300000;
  const pending = intervals[0].fn();
  intervals[0].fn();
  await pending;
  await settle();
  assert.equal(requests.length, 4, 'Overlapping refreshes must be suppressed');


  // Failed refreshes must not leave stale cycle data looking current.
  fetchFailure = true;
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 5);
  assert.equal(nodes['auto-results'].entries.length, 0,
    'A failed refresh must clear previously rendered cycle details');
  assert.ok(nodes['auto-status'].textContent.includes('archive unavailable'));
  assert.ok(!nodes['auto-status'].textContent.includes('Network unavailable'),
    'Do not expose arbitrary network diagnostics');

  // Recovery should restore accurate status on the next allowed refresh.
  fetchFailure = false;
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 6);
  assert.ok(nodes['auto-status'].textContent.includes('Status: partial_failure'));
  assert.equal(nodes['auto-results'].entries.length, 1);

  // A malformed/empty archive must also clear the prior successful display.
  archiveResponse = [];
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 7);
  assert.equal(nodes['auto-results'].entries.length, 0);
  assert.ok(nodes['auto-status'].textContent.includes('archive unavailable'));

  // A stalled network request must time out, clear the stale display, and unblock a later refresh.
  archiveResponse = [{ time: '2026-11-01T06:00:00Z', status: 'completed', errors: [], experiments: [] }];
  hangNext = true;
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 8);
  const timeout = timeoutTasks.at(-1);
  assert.equal(timeout.ms, 15000, 'Archive fetch must have a bounded timeout');
  assert.equal(timeout.active, true, 'Timeout must remain active while fetch is stalled');
  timeout.fn();
  await settle();
  assert.equal(timeout.active, false, 'Timeout must be cleared after an aborted request');
  assert.equal(nodes['auto-results'].entries.length, 0, 'Timed-out archive must not display stale results');
  assert.ok(nodes['auto-status'].textContent.includes('archive unavailable'));
  clockMs += 300000;
  intervals[0].fn();
  await settle();
  assert.equal(requests.length, 9, 'A timed-out fetch must not block the next refresh');
  assert.ok(nodes['auto-status'].textContent.includes('Status: completed'));
  assert.equal(timeoutTasks.at(-1).active, false, 'Successful fetch must clear its timeout');

  console.log('Frontend polling regression checks passed: caching, throttling, visibility, overlap, accurate status, stale-data clearing, timeout/abort, and recovery.');
})().catch(error => { console.error(error); process.exitCode = 1; });
