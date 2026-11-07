const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  ARCHIVE_URL,
  MAX_EXPERIMENTS,
  REQUEST_TIMEOUT_MS,
  REFRESH_MS,
  RETRY_MS,
  createController,
  isUsableArchive
} = require("../cdn-preview/app.js");

function archive(name = "known baseline") {
  return [
    {
      time: "2026-11-07T04:00:02.916661+00:00",
      status: "completed",
      errors: [],
      experiments: [{
        name,
        category: "known_baseline",
        observed: 0.5,
        expected: 0.5,
        z_score: 0,
        flag: false
      }]
    },
    { time: "2026-11-07T03:00:00Z", status: "completed", errors: [], experiments: [] }
  ];
}

function makeNode() {
  return {
    textContent: "",
    children: [],
    disabled: false,
    listeners: {},
    addEventListener(type, callback) { this.listeners[type] = callback; },
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; }
  };
}

function makeDocument() {
  const nodes = {
    status: makeNode(),
    summary: makeNode(),
    experiments: makeNode(),
    note: makeNode(),
    refresh: makeNode()
  };
  const listeners = {};
  return {
    nodes,
    listeners,
    hidden: false,
    getElementById(id) { return nodes[id]; },
    createElement() { return makeNode(); },
    addEventListener(type, callback) { listeners[type] = callback; }
  };
}

function makeHarness(fetchImpl, start = 1000) {
  const document = makeDocument();
  const calls = [];
  const timers = [];
  let clock = start;
  let timerId = 0;
  const wrappedFetch = async (url, options) => {
    calls.push({ url, options });
    return fetchImpl(url, options);
  };
  const controller = createController({
    document,
    fetchImpl: wrappedFetch,
    now: () => clock,
    setTimeoutImpl: (callback, delay) => {
      const id = ++timerId;
      timers.push({ id, callback, delay });
      return id;
    },
    clearTimeoutImpl: () => {},
    AbortControllerImpl: class {
      constructor() { this.signal = {}; this.aborted = false; }
      abort() { this.aborted = true; }
    }
  });
  return {
    controller,
    document,
    calls,
    timers,
    advance(ms) { clock += ms; }
  };
}

test("archive validation rejects empty, malformed, and undated data", () => {
  assert.equal(isUsableArchive([]), false);
  assert.equal(isUsableArchive(null), false);
  assert.equal(isUsableArchive([{ time: "not-a-date", status: "completed", errors: [], experiments: [] }]), false);
  assert.equal(isUsableArchive([{ time: "2026-11-07T04:00:00Z", status: "completed", errors: [], experiments: [] }]), true);
  assert.equal(isUsableArchive([{ time: "2026-11-07T04:00:00Z", status: "completed", errors: [] }]), false);
});

test("preview uses one stable cached archive URL and renders untrusted text inertly", async () => {
  const payload = archive("<img src=x onerror=alert(1)>");
  const h = makeHarness(async () => ({ ok: true, json: async () => payload }));
  assert.equal(await h.controller.refresh(false), true);

  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, ARCHIVE_URL);
  assert.equal(h.calls[0].options.cache, "default");
  assert.equal(h.document.nodes.summary.textContent.includes("2 archived cycles"), true);
  assert.equal(h.document.nodes.status.textContent, "Latest cycle status: completed");
  assert.equal(h.document.nodes.experiments.children.length, 1);
  assert.equal(
    h.document.nodes.experiments.children[0].children[0].textContent,
    "<img src=x onerror=alert(1)>"
  );
  assert.equal(h.document.nodes.experiments.children[0].children[1].textContent, "Known baseline");
  assert.match(h.document.nodes.note.textContent, /not discoveries/);

  const source = fs.readFileSync(path.join(__dirname, "../cdn-preview/app.js"), "utf8");
  assert.doesNotMatch(source, /\binnerHTML\b/);
  assert.doesNotMatch(source, /cache\s*:\s*["']no-store|\?t=/i);
  assert.doesNotMatch(source, /\/api\//);
});

test("successful refreshes are throttled for five minutes unless manually forced", async () => {
  const h = makeHarness(async () => ({ ok: true, json: async () => archive() }));
  await h.controller.refresh(false);
  await h.controller.refresh(false);
  h.advance(REFRESH_MS - 1);
  await h.controller.refresh(false);
  assert.equal(h.calls.length, 1);

  h.advance(1);
  await h.controller.refresh(false);
  assert.equal(h.calls.length, 2);

  await h.controller.refresh(true);
  assert.equal(h.calls.length, 3);
});

test("failed archive reads show a generic message and retry after a bounded delay", async () => {
  let attempt = 0;
  const h = makeHarness(async () => {
    attempt += 1;
    if (attempt === 1) throw new Error("private transport detail");
    return { ok: true, json: async () => archive() };
  });

  assert.equal(await h.controller.refresh(false), false);
  assert.match(h.document.nodes.status.textContent, /temporarily unavailable/);
  assert.doesNotMatch(h.document.nodes.status.textContent, /private transport detail/);
  await h.controller.refresh(false);
  assert.equal(h.calls.length, 1);

  h.advance(RETRY_MS);
  assert.equal(await h.controller.refresh(false), true);
  assert.equal(h.calls.length, 2);
});

test("hidden tabs do not fetch; visibility can resume a due refresh", async () => {
  const h = makeHarness(async () => ({ ok: true, json: async () => archive() }));
  h.document.hidden = true;
  assert.equal(await h.controller.refresh(false), false);
  assert.equal(h.calls.length, 0);

  h.document.hidden = false;
  h.controller.bind();
  await h.document.listeners.visibilitychange();
  assert.equal(h.calls.length, 1);
});

test("rendering is bounded even if a cycle contains many experiment rows", async () => {
  const large = archive();
  large[0].experiments = Array.from({ length: MAX_EXPERIMENTS + 10 }, (_, index) => ({
    name: "experiment " + index,
    category: "candidate",
    observed: index,
    expected: 0,
    z_score: 0,
    flag: false
  }));
  const h = makeHarness(async () => ({ ok: true, json: async () => large }));
  await h.controller.refresh(false);
  assert.equal(h.document.nodes.experiments.children.length, MAX_EXPERIMENTS);
  assert.match(h.document.nodes.note.textContent, /Showing 50 of 60/);
});

test("a stalled archive request is aborted after the timeout", async () => {
  const document = makeDocument();
  const timers = [];
  let rejectFetch;
  let signal;
  let abortCalled = false;

  const controller = createController({
    document,
    fetchImpl: (_url, options) => {
      signal = options.signal;
      return new Promise((_resolve, reject) => {
        rejectFetch = reject;
      });
    },
    now: () => 1000,
    setTimeoutImpl: (callback, delay) => {
      const id = timers.length + 1;
      timers.push({ id, callback, delay });
      return id;
    },
    clearTimeoutImpl: () => {},
    AbortControllerImpl: class {
      constructor() {
        this.signal = { aborted: false };
      }
      abort() {
        abortCalled = true;
        this.signal.aborted = true;
        if (rejectFetch) rejectFetch(new Error("aborted"));
      }
    }
  });

  const pending = controller.refresh(false);
  await Promise.resolve();
  const timeout = timers.find((timer) => timer.delay === REQUEST_TIMEOUT_MS);
  assert.ok(timeout, "request timeout should be scheduled");
  assert.equal(signal.aborted, false);

  timeout.callback();
  assert.equal(await pending, false);
  assert.equal(abortCalled, true);
  assert.equal(signal.aborted, true);
  assert.match(document.nodes.status.textContent, /temporarily unavailable/);
  assert.ok(timers.some((timer) => timer.delay === RETRY_MS));
});
