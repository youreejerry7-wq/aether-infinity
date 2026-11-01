// Offline behavioral regression: hostile archive/API text must never become HTML.
// Also checks that the dashboard avoids unnecessary background polling.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'templates', 'index.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0]?.[1];
assert.ok(script, 'Expected dashboard JavaScript');

class Node {
  constructor(tag) { this.tag = tag; this.children = []; this._text = ''; this.style = {}; this.className = ''; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(x => x.textContent).join(''); }
  set innerHTML(_) { throw Error('Unsafe HTML interpolation'); }
  appendChild(child) { this.children.push(child); return child; }
}
const nodes = new Map();
const document = {
  hidden: false,
  getElementById(id) {
    if (!nodes.has(id)) nodes.set(id, new Node(id));
    return nodes.get(id);
  },
  createElement(tag) { return new Node(tag); },
  addEventListener(name, handler) { listeners[name] = handler; },
};
const listeners = {};
const intervals = [];
let clock = 0;
class FakeDate extends Date { static now() { return clock; } }
const attack = '<img src=x onerror=alert(1)>';
const archive = [{
  time: '2026-11-01T20:00:00Z', status: attack, z_threshold: 3.29,
  errors: [{ name: attack, error: attack }],
  experiments: [{
    name: attack, description: attack, category: 'discovery',
    observed: 0.5, expected: 0.5, z_score: 0, trials: 10, flag: false,
  }],
}];
let githubFails = false;
const requests = [];
async function fetch(url, options = {}) {
  requests.push({ url, options });
  if (url.includes('raw.githubusercontent.com')) {
    if (githubFails) throw Error('Network failure');
    return { ok: true, json: async () => archive };
  }
  if (url === '/api/research') return { ok: true, json: async () => archive };
  if (url === '/api/results') return {
    ok: true, json: async () => [{
      created: '2026-11-01T20:00:00Z', trials: 20,
      estimate: 3.1, expected: 3.14, deviation: 0.04, status: attack,
    }],
  };
  throw Error('Unexpected URL ' + url);
}
const settle = () => new Promise(resolve => setImmediate(resolve));

(async () => {
  vm.runInNewContext(script, {
    document, fetch, Date: FakeDate,
    setInterval(fn, ms) { intervals.push({ fn, ms }); },
    console: { error() {} },
  });
  await settle();
  await settle();
  assert.equal(requests[0].url,
    'https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity/main/data/research.json');
  assert.equal(requests[0].options.cache, 'default');
  assert.equal(requests.filter(x => x.url === '/api/research').length, 0,
    'Current GitHub archive should avoid a potentially stale Render request');
  assert.equal(intervals.length, 1);
  assert.equal(intervals[0].ms, 300000);
  assert.ok(nodes.get('auto-experiments').textContent.includes(attack));
  assert.ok(nodes.get('auto-errors').textContent.includes(attack));
  assert.ok(nodes.get('val-status').textContent.includes(attack));
  assert.ok(nodes.get('results').textContent.includes(attack));
  assert.ok(nodes.get('auto-experiments').textContent.includes('Simulation candidate'));
  assert.ok(!nodes.get('auto-experiments').textContent.includes('Discovery'),
    'Simulated candidates must not be labeled proven discoveries');

  const firstCount = requests.length;
  await intervals[0].fn();
  assert.equal(requests.length, firstCount, 'No refresh before five minutes');
  document.hidden = true;
  clock += 300000;
  await intervals[0].fn();
  assert.equal(requests.length, firstCount, 'No polling in hidden tabs');

  document.hidden = false;
  githubFails = true;
  await listeners.visibilitychange();
  await settle();
  assert.equal(requests.filter(x => x.url === '/api/research').length, 1,
    'Bundled fallback should be used only when GitHub fails');
  assert.ok(nodes.get('auto-status').textContent.includes('bundled snapshot'));
  assert.ok(!nodes.get('auto-status').textContent.includes('Network failure'));
  console.log('PASS: safe text-only DOM, current archive preference, fallback, 5-minute hidden-tab polling');
})().catch(error => { console.error(error); process.exitCode = 1; });
