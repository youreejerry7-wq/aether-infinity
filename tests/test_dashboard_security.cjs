// Offline dashboard security regression: untrusted archive/API strings stay inert.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '..', 'templates/index.html'), 'utf8');
assert.doesNotMatch(html, /\.badge-discovery\b/, 'Candidate styling must not use discovery terminology');
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
let fallbackArchive = null;
let resultsMode = 'ok';
let resolveDelayedResults;
let runMode = 'ok';
let hangGitHub = false;
let hangFallback = false;
let hangArchiveBody = false;
let hangResultsBody = false;
let hangRunBody = false;
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
  if (hangArchiveBody && url.startsWith('https://raw.githubusercontent.com/')) {
    hangArchiveBody = false;
    return { ok: true, json: () => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('Body timed out')), { once: true });
    }) };
  }
  if (url === '/api/research') return { ok: !failArchive, json: async () => fallbackArchive ?? archive };
  if (url.startsWith('https://raw.githubusercontent.com/'))
    return { ok: !failArchive, json: async () => archive };
  if (url === '/api/results') {
    if (hangResultsBody) {
      hangResultsBody = false;
      return { ok: true, json: () => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new Error('GET body timed out')), { once: true });
      }) };
    }
    if (resultsMode === 'delayed') return new Promise(resolve => { resolveDelayedResults = resolve; });
    if (resultsMode === 'hang') return new Promise((resolve, reject) => {
      assert.ok(options.signal, 'Results GET must be abortable');
      options.signal.addEventListener('abort', () => reject(new Error('GET timed out')), { once: true });
    });
    return { ok: true, json: async () => results };
  }
  if (url === '/api/run') {
    if (hangRunBody) {
      hangRunBody = false;
      return { ok: true, json: () => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new Error('POST body timed out')), { once: true });
      }) };
    }
    if (runMode === 'hang') return new Promise((resolve, reject) => {
      assert.ok(options.signal, 'Experiment POST must be abortable');
      options.signal.addEventListener('abort', () => reject(new Error('POST timed out')), { once: true });
    });
    if (runMode === 'rate-limited') return {
      ok: false, status: 429,
      json: async () => ({ error: 'private server diagnostic' }),
    };
    if (runMode === 'malformed') return { ok: true, json: async () => ({ estimate: 'invalid', deviation: 0 }) };
    return { ok: true, json: async () => ({ estimate: 3.14, deviation: 0.00159 }) };
  }
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
  assert.equal(intervals[0].ms, 30000, '30-second wakeup allows bounded retries; successful fetches remain throttled for five minutes');
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
  // A later valid cycle without interpretation must not retain an earlier cycle's text.
  archive = [{time: '2026-11-02T04:00:00Z', status: 'completed', errors: [], experiments: []}];
  clockMs += 300000;
  await context.loadAuto();
  assert.equal(nodes['auto-interpretation'].textContent, '', 'Missing interpretation clears stale text');
  assert.equal(nodes['auto-errors'].children.length, 0, 'Resolved errors are not retained');

  // The existing public archive predates status/errors/category fields.
  // It must still render honestly rather than being rejected as unavailable.
  archive = [{
    time: '2026-11-07T11:49:55.113749+00:00',
    interpretation: 'Flags indicate deviations worth replication, not discoveries.',
    experiments: [{
      name: 'Fair coin frequency', observed: 0.49936, expected: 0.5,
      z_score: -0.405, trials: 100000, flag: false,
    }],
  }];
  clockMs += 300000;
  await context.loadAuto();
  const legacyBadge = nodes['val-status'].children[0];
  assert.equal(legacyBadge.textContent, 'legacy record');
  assert.equal(legacyBadge.className, 'status-badge',
    'Legacy status must use a neutral badge, not the failed state');
  assert.equal(nodes['auto-experiments'].children[0].children[1].textContent,
    'Simulated statistic');
  assert.equal(nodes['auto-errors'].children.length, 0,
    'Missing legacy errors must not be treated as a validation failure');

  // Oversized archives must not create unbounded DOM rows or hide truncation.
  archive = [{
    time: '2026-11-02T04:30:00Z', status: 'partial_failure',
    errors: Array.from({ length: 40 }, (_, i) => ({ name: 'Error ' + i })),
    experiments: Array.from({ length: 120 }, (_, i) => ({
      name: 'Experiment ' + i, category: 'known_baseline', observed: i,
      expected: i, z_score: 0, trials: 100, flag: false,
    })),
  }];
  clockMs += 300000;
  await context.loadAuto();
  assert.equal(nodes['auto-experiments'].children.length, 50,
    'Only the first 50 archive experiments may be rendered');
  assert.equal(nodes['auto-errors'].children[0].children[1].children.length, 20,
    'Only the first 20 archive error names may be rendered');
  assert.ok(nodes['auto-status'].textContent.includes('first 50 of 120 experiments'));
  assert.ok(nodes['auto-status'].textContent.includes('first 20 of 40 errors'));
  archive = [{ time: '2026-11-02T04:45:00Z', status: 'completed', errors: [], experiments: [] }];

  // A malformed GitHub cycle must never be labeled a verified current run.
  // A valid server copy is allowed only as an explicitly stale-prone snapshot.
  archive = [{ time: 'invalid timestamp', status: 'completed', errors: [], experiments: [] }];
  fallbackArchive = [{ time: '2026-11-02T04:40:00Z', status: 'completed', errors: [], experiments: [] }];
  clockMs += 300000;
  await context.loadAuto();
  assert.ok(nodes['auto-status'].textContent.includes('snapshot'),
    'Malformed primary data must use a clearly labeled fallback');
  assert.equal(requests.at(-1).url, '/api/research');
  fallbackArchive = null;
  clockMs += 30000;
  await context.loadAuto();
  assert.equal(nodes['auto-summary'].style.display, 'none',
    'Invalid primary and fallback cycles must not appear verified');
  assert.ok(nodes['auto-status'].textContent.includes('unavailable'));
  // A malformed primary archive plus a failed fallback must not display a fake run.
  archive = [{ time: 'invalid timestamp', status: 'completed', errors: [], experiments: [] }];
  hangFallback = true;
  clockMs += 30000;
  const malformedWithTimeout = context.loadAuto();
  await settle();
  const malformedFallbackTimer = timeoutTasks.at(-1);
  assert.equal(malformedFallbackTimer.ms, 15000);
  malformedFallbackTimer.fn();
  await malformedWithTimeout;
  assert.equal(nodes['auto-summary'].style.display, 'none',
    'Malformed primary data must remain rejected if fallback times out');
  assert.ok(nodes['auto-status'].textContent.includes('unavailable'));
  archive = [{ time: '2026-11-02T04:45:00Z', status: 'completed', errors: [], experiments: [] }];
  clockMs += 30000;
  await context.loadAuto();
  assert.ok(nodes['auto-status'].textContent.includes('Latest available GitHub archive.'),
    'A valid archive should recover after the short retry');

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
  const requestsAfterFailure = archiveRequests().length;
  clockMs += 29999;
  await context.loadAuto();
  assert.equal(archiveRequests().length, requestsAfterFailure,
    'Do not retry a failed archive before 30 seconds');
  clockMs += 1;
  failArchive = false;
  await context.loadAuto();
  assert.equal(archiveRequests().length, requestsAfterFailure + 1,
    'Retry an unavailable archive after 30 seconds instead of five minutes');
  assert.ok(nodes['auto-status'].textContent.includes('Latest available GitHub archive.'));

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
  const requestsAfterFallback = archiveRequests().length;
  clockMs += 30000;
  await context.loadAuto();
  assert.equal(archiveRequests().length, requestsAfterFallback + 1,
    'A potentially stale server snapshot triggers a 30-second GitHub retry');
  assert.ok(nodes['auto-status'].textContent.includes('Latest available GitHub archive.'));

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

  // A response with headers but a stalled JSON body must still time out and recover.
  hangArchiveBody = true;
  clockMs += 300000;
  const stalledBody = context.loadAuto();
  await settle();
  const bodyTimeout = timeoutTasks.at(-1);
  assert.equal(bodyTimeout.ms, 15000);
  assert.equal(bodyTimeout.active, true, 'Abort timer must remain active during JSON parsing');
  bodyTimeout.fn();
  await stalledBody;
  assert.equal(bodyTimeout.active, false, 'Body timeout must be cleared after fallback');
  assert.equal(requests.at(-1).url, '/api/research', 'Timed-out JSON body must use server fallback');
  assert.ok(nodes['auto-status'].textContent.includes('snapshot'));

  // Malformed demo rows must show a safe error instead of partial rendering.
  results = [{ created: hostile, trials: 20000, estimate: 'invalid', expected: 3.14, deviation: 0, status: hostile }];
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent, 'Interactive results temporarily unavailable.');

  // An older, slow results response must never overwrite a newer successful refresh.
  resultsMode = 'delayed';
  const olderResults = context.loadInteractive();
  assert.equal(typeof resolveDelayedResults, 'function');
  resultsMode = 'ok';
  results = [{ created: '2026-11-02T03:00:00Z', trials: 20000, estimate: 3.14,
    expected: 3.14159, deviation: 0.00159, status: 'completed' }];
  await context.loadInteractive();
  assert.equal(nodes.results.children[0].children[0].textContent, '2026-11-02 03:00:00');
  resolveDelayedResults({ ok: true, json: async () => [{
    created: '2026-11-02T01:00:00Z', trials: 20000, estimate: 3.14,
    expected: 3.14159, deviation: 0.00159, status: 'completed',
  }] });
  await olderResults;
  assert.equal(nodes.results.children[0].children[0].textContent, '2026-11-02 03:00:00',
    'Stale GET must not overwrite newer results');

  // GET timeout is bounded and releases its timer without displaying stale data.
  resultsMode = 'hang';
  const hangingGet = context.loadInteractive();
  await settle();
  const getTimeout = timeoutTasks.at(-1);
  assert.equal(getTimeout.ms, 60000);
  getTimeout.fn();
  await hangingGet;
  assert.equal(getTimeout.active, false);
  assert.equal(nodes.results.children[0].children[0].textContent,
    'Interactive results temporarily unavailable.');

  // Headers can arrive before a JSON body stalls; the GET must still time out.
  resultsMode = 'ok';
  hangResultsBody = true;
  const hangingGetBody = context.loadInteractive();
  await settle();
  const getBodyTimeout = timeoutTasks.at(-1);
  assert.equal(getBodyTimeout.ms, 60000);
  assert.equal(getBodyTimeout.active, true);
  getBodyTimeout.fn();
  await hangingGetBody;
  assert.equal(getBodyTimeout.active, false);
  assert.equal(nodes.results.children[0].children[0].textContent,
    'Interactive results temporarily unavailable.');

  // Successful POST feedback and button recovery must not wait on a stalled GET.
  const runWithHangingGet = nodes.run.onclick();
  await runWithHangingGet;
  assert.equal(nodes.run.disabled, false);
  assert.ok(nodes.message.textContent.includes('Estimate: 3.140000'));
  const refreshTimeout = timeoutTasks.at(-1);
  assert.equal(refreshTimeout.ms, 60000);
  assert.equal(refreshTimeout.active, true);
  refreshTimeout.fn();
  await settle();
  assert.equal(refreshTimeout.active, false);

  // Invalid POST response is safe and does not strand the button.
  resultsMode = 'ok';
  runMode = 'malformed';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');
  assert.equal(nodes.run.disabled, false);

  // A bounded server can return 429: give useful, non-technical feedback and
  // restore the button without reading or exposing the response body.
  runMode = 'rate-limited';
  await nodes.run.onclick();
  assert.equal(nodes.message.textContent, 'Demo temporarily busy. Please retry later.');
  assert.equal(nodes.run.disabled, false);
  assert.ok(!nodes.message.textContent.includes('private server diagnostic'));

  // A stalled POST must abort after 90 seconds and recover without exposing diagnostics.
  runMode = 'hang';
  const hangingPost = nodes.run.onclick();
  assert.equal(nodes.run.disabled, true);
  const postTimeout = timeoutTasks.at(-1);
  assert.equal(postTimeout.ms, 90000);
  postTimeout.fn();
  await hangingPost;
  assert.equal(postTimeout.active, false);
  assert.equal(nodes.run.disabled, false);
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');

  // A successful POST header with a stalled JSON body must not strand the button.
  runMode = 'ok';
  hangRunBody = true;
  const hangingPostBody = nodes.run.onclick();
  await settle();
  const postBodyTimeout = timeoutTasks.at(-1);
  assert.equal(postBodyTimeout.ms, 90000);
  assert.equal(postBodyTimeout.active, true);
  postBodyTimeout.fn();
  await hangingPostBody;
  assert.equal(postBodyTimeout.active, false);
  assert.equal(nodes.run.disabled, false);
  assert.equal(nodes.message.textContent, 'Experiment unavailable. Please try again.');

  // Optional live integration check: feed the public archive through the same
  // dashboard loader used by the browser, not just a hand-written fixture.
  if (process.env.AETHER_ARCHIVE_PATH) {
    const liveArchive = JSON.parse(fs.readFileSync(process.env.AETHER_ARCHIVE_PATH, 'utf8'));
    assert.ok(Array.isArray(liveArchive) && liveArchive.length > 0);
    assert.ok(Array.isArray(liveArchive[0].experiments));
    archive = liveArchive;
    failArchive = false;
    fallbackArchive = null;
    hangGitHub = false;
    hangFallback = false;
    hangArchiveBody = false;
    document.hidden = false;
    clockMs = Number.MAX_SAFE_INTEGER - 1000000;
    await context.loadAuto();
    assert.equal(nodes['auto-summary'].style.display, 'grid',
      'The current public archive must be accepted by the dashboard');
    const liveBadge = nodes['val-status'].children[0];
    assert.equal(liveBadge.textContent,
      typeof liveArchive[0].status === 'string' ? liveArchive[0].status : 'legacy record');
    if (liveArchive[0].experiments.length > 0) {
      const first = liveArchive[0].experiments[0];
      const expectedType = first && first.category === 'known_baseline' ? 'Known baseline' :
        first && typeof first.category === 'string' ? 'Unverified candidate' : 'Simulated statistic';
      assert.equal(nodes['auto-experiments'].children[0].children[1].textContent, expectedType);
    }
    if (!Array.isArray(liveArchive[0].errors)) {
      assert.equal(nodes['auto-errors'].children.length, 0);
    }
    console.log('Live archive/dashboard integration PASS: ' + liveArchive.length + ' cycles.');
  }

  console.log('Dashboard DOM security PASS: inert text, bounded requests, stale-response guard, nonblocking run feedback.');
})().catch(error => { console.error(error); process.exitCode = 1; });
