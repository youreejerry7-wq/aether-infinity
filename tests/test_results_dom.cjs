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
const fetch = async (url, options) => {
  if (url === '/api/results') return { json: async () => rows };
  assert.equal(url, '/api/run');
  assert.equal(options.method, 'POST');
  postCalls++;
  return { ok: true, json: async () => ({ estimate: 3.14, deviation: 0.00159265 }) };
};
const context = { document, fetch };
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
  console.log('Demo results DOM regression passed: inert text, empty state, and run/reload.');
})().catch(error => { console.error(error); process.exitCode = 1; });
