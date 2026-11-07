// Offline regression for the interactive demo table in the dashboard.
// No network, database, payment, or production writes are performed.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
assert.ok(scripts.length >= 1, 'Expected the dashboard script');
const start = scripts[scripts.length - 1][1].indexOf('async function fetchInteractiveJsonWithTimeout(');
assert.ok(start >= 0, 'Expected the bounded interactive request helper');
const end = scripts[scripts.length - 1][1].indexOf('\nloadAuto();', start);
assert.ok(end > start, 'Expected the dashboard startup section after interactive controller');
const demoScript = scripts[scripts.length - 1][1].slice(start, end);

function element(tag) {
  return {
    tag, children: [], disabled: false, colSpan: undefined, _text: '',
    get textContent() { return this._text; },
    set textContent(value) { this._text = String(value); this.children = []; },
    set innerHTML(_) { throw new Error('Unsafe HTML interpolation is forbidden'); },
    appendChild(child) { this.children.push(child); return child; },
  };
}

const nodes = {
  results: element('tbody'),
  run: element('button'),
  message: element('p'),
};
const hostile = '<img src=x onerror=alert(1)>';
let rows = [{
  created: '2026-11-07T05:00:00Z',
  trials: 20000,
  estimate: 3.14,
  expected: Math.PI,
  deviation: 0.00159,
  status: hostile,
}];
let getMode = 'ok';
let postMode = 'ok';
let getCalls = 0;
let postCalls = 0;

const fetch = async (url, options = {}) => {
  if (url === '/api/results') {
    getCalls++;
    if (getMode === 'http-error') return { ok: false, status: 503 };
    if (getMode === 'malformed') return { ok: true, json: async () => ({ unexpected: true }) };
    return { ok: true, json: async () => rows };
  }
  if (url === '/api/run') {
    postCalls++;
    assert.equal(options.method, 'POST');
    if (postMode === 'http-error') return { ok: false, status: 503 };
    if (postMode === 'rate-limited') return { ok: false, status: 429 };
    if (postMode === 'malformed') return {
      ok: true, json: async () => ({ estimate: 'invalid', deviation: 0.1 }),
    };
    return {
      ok: true,
      json: async () => ({ estimate: 3.14, deviation: 0.00159 }),
    };
  }
  throw new Error('Unexpected request URL: ' + url);
};

const document = {
  getElementById(id) {
    assert.ok(nodes[id], 'Unexpected DOM lookup: ' + id);
    return nodes[id];
  },
  createElement(tag) {
    assert.ok(['tr', 'td'].includes(tag), 'Unexpected element: ' + tag);
    return element(tag);
  },
};
const context = { document, fetch, AbortController, setTimeout, clearTimeout };
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  vm.runInNewContext(demoScript, context);
  assert.equal(typeof context.fetchInteractiveJsonWithTimeout, 'function', 'Expected bounded request helper');
  assert.equal(typeof context.loadInteractive, 'function', 'Expected interactive results loader');
  await context.loadInteractive();
  await settle();

  assert.equal(getCalls, 1, 'Interactive results should load on startup');
  assert.equal(nodes.results.children.length, 1);
  let cells = nodes.results.children[0].children;
  assert.equal(cells.length, 6, 'Rows should match the six dashboard columns');
  assert.equal(cells[0].textContent, '2026-11-07 05:00:00');
  assert.equal(cells[1].textContent, '20000');
  assert.equal(cells[2].textContent, '3.140000');
  assert.equal(cells[3].textContent, Math.PI.toFixed(6));
  assert.equal(cells[5].textContent, hostile, 'Untrusted API status must remain inert text');

  rows = [];
  await context.loadInteractive();
  assert.equal(nodes.results.children.length, 1);
  assert.equal(nodes.results.children[0].children[0].textContent,
    'No interactive experiments run yet.');
  assert.equal(nodes.results.children[0].children[0].colSpan, 6);

  getMode = 'malformed';
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent,
    'Interactive results temporarily unavailable.');
  assert.equal(nodes.results.children[0].children[0].colSpan, 6);

  getMode = 'http-error';
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent,
    'Interactive results temporarily unavailable.');

  getMode = 'ok';
  rows = [{
    created: '2026-11-07T06:00:00Z', trials: 20000,
    estimate: 3.14, expected: Math.PI, deviation: 0.00159, status: 'completed',
  }];
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].children[0].textContent,
    '2026-11-07 06:00:00', 'Valid rows should recover after a failed refresh');

  postMode = 'malformed';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');
  assert.equal(nodes.run.disabled, false);

  postMode = 'http-error';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');
  assert.equal(nodes.run.disabled, false);

  postMode = 'rate-limited';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Demo temporarily busy. Please retry later.');
  assert.equal(nodes.run.disabled, false);

  postMode = 'ok';
  await nodes.run.onclick();
  await settle();
  assert.equal(postCalls, 4);
  assert.equal(nodes.run.disabled, false);
  assert.ok(nodes.message.textContent.includes('Estimate: 3.140000'));
  assert.ok(getCalls >= 5, 'Successful POST should trigger an independent results refresh');

  console.log('Interactive DOM checks passed: safe text rendering, six-column/empty states, malformed and failed GET recovery, safe POST errors, 429 feedback, and button recovery.');
})().catch(error => { console.error(error); process.exitCode = 1; });
