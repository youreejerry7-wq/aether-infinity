// DOM regression for demo results: never interpret API-supplied text as HTML.
// Offline, standard-library-only test. Does not contact or modify production.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.ok(scripts.length >= 2, 'Expected separate demo and research scripts');
const demoScript = scripts[scripts.length - 1][1];

function element(tag) {
  return {
    tag, children: [], disabled: false, _text: '',
    get textContent() { return this._text; },
    set textContent(value) { this._text = String(value); this.children = []; },
    set innerHTML(_) { throw Error('Unsafe HTML interpolation in demo results'); },
    appendChild(child) { this.children.push(child); },
  };
}
const nodes = {
  results: element('tbody'),
  run: element('button'),
  message: element('p'),
};
const document = {
  getElementById(id) {
    assert.ok(nodes[id], 'Unexpected element ID: ' + id);
    return nodes[id];
  },
  createElement(tag) {
    assert.ok(['tr', 'td'].includes(tag), 'Unexpected DOM element: ' + tag);
    return element(tag);
  },
};
const hostile = '<svg onload=1>';
let rows = [{
  created: hostile, trials: 20000, estimate: 3.14, deviation: 0.00159265,
}];
let postCalls = 0;
let postMode = 'ok';
let resolveAbortedPost;
const timers = [];
const fakeSetTimeout = (fn, ms) => { const timer = { fn, ms, active: true }; timers.push(timer); return timer; };
const fakeClearTimeout = timer => { timer.active = false; };
let resultsMode = 'ok';
let resolveDelayedResults;
const fetch = async (url, options) => {
  if (url === '/api/results') {
    if (resultsMode === 'delayed') return new Promise(resolve => { resolveDelayedResults = resolve; });
    if (resultsMode === 'http-error') return { ok: false, json: async () => rows };
    if (resultsMode === 'malformed') return { ok: true, json: async () => ({ unexpected: 'object' }) };
    return { ok: true, json: async () => rows };
  }
  assert.equal(url, '/api/run');
  assert.equal(options.method, 'POST');
  postCalls++;
  if (postMode === 'hang') return new Promise((resolve, reject) => {
    assert.ok(options.signal, 'POST must be abortable');
    options.signal.addEventListener('abort', () => reject(new Error('Request timed out')), { once: true });
  });
  if (postMode === 'http-error') return { ok: false };
  if (postMode === 'malformed') return { ok: true, json: async () => ({ estimate: 'invalid', deviation: 0.1 }) };
  return { ok: true, json: async () => ({ estimate: 3.14, deviation: 0.00159265 }) };
};
const context = { document, fetch, AbortController, setTimeout: fakeSetTimeout, clearTimeout: fakeClearTimeout };
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  vm.runInNewContext(demoScript, context);
  await settle();
  assert.equal(nodes.results.children.length, 1);
  const cells = nodes.results.children[0].children;
  assert.equal(cells.length, 4);
  assert.equal(cells[0].textContent, hostile, 'Untrusted date must remain inert text');
  assert.equal(cells[1].textContent, '20000');
  assert.equal(cells[2].textContent, '3.140000');
  assert.equal(cells[3].textContent, '0.001593');

  rows = [];
  await context.load();
  assert.equal(nodes.results.children.length, 1);
  const empty = nodes.results.children[0].children[0];
  assert.equal(empty.textContent, 'No experiments yet');
  assert.equal(empty.colSpan, 4);

  rows = [{ created: '2026-11-01T05:00:00Z', trials: 20000, estimate: 3.14, deviation: 0.00159265 }];
  await nodes.run.onclick();
  assert.equal(postCalls, 1, 'Run button still submits once');
  assert.equal(nodes.run.disabled, false, 'Button re-enabled after success');
  assert.ok(nodes.message.textContent.includes('Estimate 3.140000'));
  assert.equal(nodes.results.children.length, 1, 'Results reload after run');

  resultsMode = 'http-error';
  await context.load();
  assert.equal(nodes.results.children.length, 1, 'Failed HTTP request must clear stale results');
  assert.equal(nodes.results.children[0].children[0].textContent, 'Experiments temporarily unavailable.');
  assert.equal(nodes.results.children[0].children[0].colSpan, 4);

  resultsMode = 'malformed';
  await context.load();
  assert.equal(nodes.results.children[0].children[0].textContent, 'Experiments temporarily unavailable.',
    'Malformed response must not render as a successful empty result');

  resultsMode = 'ok';
  rows = [{ created: '2026-11-01T05:00:00Z', trials: 20000, estimate: 'invalid', deviation: 0.1 }];
  await context.load();
  assert.equal(nodes.results.children[0].children[0].textContent, 'Experiments temporarily unavailable.',
    'Invalid row must not cause a partial render or leak a runtime error');

  rows = [{ created: '2026-11-01T05:00:00Z', trials: 20000, estimate: 3.14, deviation: 0.00159265 }];
  await context.load();
  assert.equal(nodes.results.children[0].children[0].textContent, '2026-11-01T05:00:00',
    'Valid results should recover after transient failure');

  // A slower, older GET must never overwrite a newer successful refresh.
  resultsMode = 'delayed';
  const olderRequest = context.load();
  assert.equal(typeof resolveDelayedResults, 'function');
  resultsMode = 'ok';
  rows = [{ created: '2026-11-01T06:00:00Z', trials: 20000, estimate: 3.14, deviation: 0.00159265 }];
  await context.load();
  assert.equal(nodes.results.children[0].children[0].textContent, '2026-11-01T06:00:00');
  resolveDelayedResults({ ok: true, json: async () => [{
    created: '2026-11-01T04:00:00Z', trials: 20000, estimate: 3.14, deviation: 0.00159265,
  }] });
  await olderRequest;
  assert.equal(nodes.results.children[0].children[0].textContent, '2026-11-01T06:00:00',
    'Late stale results must not overwrite the most recent successful response');
  // Invalid experiment responses and failed POSTs must not display JS exception text.
  postMode = 'malformed';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.',
    'Invalid POST payload must produce a stable, non-technical error');
  assert.equal(nodes.run.disabled, false, 'Button must recover after invalid POST payload');
  postMode = 'http-error';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.',
    'Failed POST must produce the same safe error');
  assert.equal(nodes.run.disabled, false, 'Button must recover after HTTP failure');

  // A stalled POST must eventually release the disabled button, without raw error text.
  postMode = 'hang';
  const hangingPost = nodes.run.onclick();
  assert.equal(nodes.run.disabled, true, 'Button stays disabled during pending request');
  const pendingTimeout = timers.at(-1);
  assert.ok(pendingTimeout && pendingTimeout.active, 'Pending POST must have a timeout');
  assert.equal(pendingTimeout.ms, 90000, 'Allow cold-start time, but bound request to 90 seconds');
  pendingTimeout.fn();
  await hangingPost;
  assert.equal(nodes.run.disabled, false, 'Aborted POST must restore button');
  assert.equal(pendingTimeout.active, false, 'Clear timeout after aborted POST');
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');

  console.log('Demo results DOM regression passed: inert text, empty state, run/reload, failed HTTP, malformed payload, invalid row, recovery, stale-response race, and safe POST failure handling.');
})().catch(error => { console.error(error); process.exitCode = 1; });
