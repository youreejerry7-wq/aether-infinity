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
      interpretation: "Flags indicate deviations worth replication, not discoveries. Multiple-testing corrections and independent validation are required.",
      experiments: [{
        name,
        observed: 0.5,
        expected: 0.5,
        z_score: 0,
        trials: 100000,
        flag: false
      }]
    },
    {
      time: "2026-11-07T03:00:00Z",
      interpretation: "Flags indicate deviations worth replication, not discoveries.",
      experiments: []
    }
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
  assert.equal(isUsableArchive([{ time: "not-a-date", experiments: [] }]), false);
  assert.equal(isUsableArchive([{
    time: "2026-11-07T04:00:00Z",
    interpretation: "Flags are not discoveries.",
    experiments: []
  }]), true);
  assert.equal(isUsableArchive([{ time: "2026-11-07T04:00:00Z", interpretation: "Missing experiments" }]), false);
});

test("preview uses one stable cached archive URL and renders untrusted text inertly", async () => {
  const payload = archive("<img src=x onerror=alert(1)>");
  const h = makeHarness(async () => ({ ok: true, json: async () => payload }));
  assert.equal(await h.controller.refresh(false), true);

  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, ARCHIVE_URL);
  assert.equal(h.calls[0].options.cache, "default");
  assert.equal(h.document.nodes.summary.textContent.includes("2 archived cycles"), true);
  assert.equal(h.document.nodes.status.textContent, "Latest archive record loaded");
  assert.equal(h.document.nodes.experiments.children.length, 1);
  assert.equal(
    h.document.nodes.experiments.children[0].children[0].textContent,
    "<img src=x onerror=alert(1)>"
  );
  assert.equal(h.document.nodes.experiments.children[0].children[1].textContent, "Simulated statistic");
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

test("a failed refresh clears previously rendered archive data", async () => {
  let fail = false;
  const h = makeHarness(async () => {
    if (fail) throw new Error("private transport detail");
    return { ok: true, json: async () => archive("last good cycle") };
  });

  assert.equal(await h.controller.refresh(false), true);
  assert.equal(h.document.nodes.experiments.children.length, 1);
  assert.match(h.document.nodes.summary.textContent, /archived cycles/);

  fail = true;
  h.advance(REFRESH_MS);
  assert.equal(await h.controller.refresh(false), false);
  assert.equal(h.document.nodes.summary.textContent, "");
  assert.equal(h.document.nodes.experiments.children.length, 0);
  assert.match(h.document.nodes.status.textContent, /temporarily unavailable/);
  assert.match(h.document.nodes.note.textContent, /No current archive data is displayed/);
  assert.doesNotMatch(h.document.nodes.status.textContent, /private transport detail/);
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

test("initial HTML stays lightweight and avoids third-party render-blocking assets", () => {
  const htmlPath = path.join(__dirname, "../cdn-preview/index.html");
  const html = fs.readFileSync(htmlPath, "utf8");

  // A small document and one deferred local script keep first paint independent
  // of third-party JavaScript, font, stylesheet, or iframe requests.
  assert.ok(Buffer.byteLength(html, "utf8") <= 4096, "initial HTML must stay under 4 KiB");
  assert.match(html, /<script\s+src=["']\.\/app\.js["']\s+defer\s*>\s*<\/script>/i);
  assert.doesNotMatch(html, /<script\b[^>]*\bsrc=["']https?:\/\//i);
  const linkTags = html.split("<link").slice(1).map((part) => "<link" + part.slice(0, part.indexOf(">") + 1));
  const externalLinks = linkTags.filter((tag) => tag.includes('href="https://'));
  assert.equal(externalLinks.length, 1, "only the archive host may be preconnected");
  assert.ok(externalLinks[0].includes('rel="preconnect"'));
  assert.ok(externalLinks[0].includes('href="https://raw.githubusercontent.com"'));
  assert.ok(externalLinks[0].includes("crossorigin"));
  assert.doesNotMatch(html, /<iframe\b|<img\b/i);
  assert.doesNotMatch(html, /@import\s+url|url\(\s*["']?https?:/i);
});


test("static preview transfer budget and external data dependency stay bounded", () => {
  const html = fs.readFileSync(path.join(__dirname, "../cdn-preview/index.html"));
  const script = fs.readFileSync(path.join(__dirname, "../cdn-preview/app.js"));
  const htmlBytes = html.byteLength;
  const scriptBytes = script.byteLength;
  const totalBytes = htmlBytes + scriptBytes;

  // Raw source bytes are a reproducible upper bound before HTTP compression.
  assert.ok(scriptBytes <= 8 * 1024, `app.js is ${scriptBytes} bytes; budget is 8192`);
  assert.ok(totalBytes <= 12 * 1024, `HTML + JS are ${totalBytes} bytes; budget is 12288`);

  const source = script.toString("utf8");
  const absoluteUrls = [...source.matchAll(/https?:\/\/[^"'\s]+/g)].map((match) => match[0]);
  assert.deepEqual(absoluteUrls, [ARCHIVE_URL], "the archive must remain the only external data URL");
  assert.equal(source.split("fetchImpl(ARCHIVE_URL").length - 1, 1);
});

test("concurrent refresh attempts do not start duplicate archive requests", async () => {
  let resolveResponse;
  const h = makeHarness(() => new Promise((resolve) => {
    resolveResponse = resolve;
  }));

  const first = h.controller.refresh(false);
  const second = h.controller.refresh(true);

  assert.equal(h.calls.length, 1, "only one archive request may be in flight");
  assert.equal(await second, false, "the concurrent refresh should be ignored");

  resolveResponse({ ok: true, json: async () => archive() });
  assert.equal(await first, true);
  assert.equal(h.calls.length, 1);
  assert.equal(h.document.nodes.status.textContent, "Latest archive record loaded");
});

