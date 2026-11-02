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
const document = {
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
const fetch = async (url, options) => {
  if (url === '/api/research') return { ok: !failArchive, json: async () => archive };
  if (url.startsWith('https://raw.githubusercontent.com/'))
    return { ok: !failArchive, json: async () => archive };
  if (url === '/api/results') return { ok: true, json: async () => results };
  if (url === '/api/run') return { ok: true, json: async () => ({ estimate: 3.14, deviation: 0.00159 }) };
  throw Error('Unexpected fetch ' + url);
};
const context = { document, fetch, setInterval: () => {} };
const settle = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  vm.runInNewContext(match[1], context);
  await settle();
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
  await context.loadAuto();
  assert.equal(nodes['auto-summary'].style.display, 'none');
  assert.equal(nodes['auto-experiments'].children.length, 0);
  assert.equal(nodes['auto-errors'].children.length, 0);
  assert.ok(nodes['auto-status'].textContent.includes('unavailable'));

  // Malformed demo rows must show a safe error instead of partial rendering.
  results = [{ created: hostile, trials: 20000, estimate: 'invalid', expected: 3.14, deviation: 0, status: hostile }];
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent, 'Interactive results temporarily unavailable.');

  console.log('Dashboard DOM security PASS: hostile archive/API text inert, no HTML interpolation, safe failure reset.');
})().catch(error => { console.error(error); process.exitCode = 1; });
