const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  LATEST_URL,
  ARCHIVE_URL,
  MAX_EXPERIMENTS,
  REQUEST_TIMEOUT_MS,
  REFRESH_MS,
  STORAGE_KEY,
  SNAPSHOT_MISSING_KEY,
  SNAPSHOT_MISSING_RECHECK_MS,
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

function makeMemoryStorage() {
  const values = new Map();
  return {
    values,
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
    removeItem(key) { values.delete(key); }
  };
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

function makeHarness(fetchImpl, start = 1000, storage = null) {
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
    },
    storage
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

test("preview prefers the compact latest snapshot and renders untrusted text inertly", async () => {
  const payload = archive("<img src=x onerror=alert(1)>").slice(0, 1);
  const h = makeHarness(async () => ({ ok: true, status: 200, json: async () => payload }));
  assert.equal(await h.controller.refresh(false), true);

  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, LATEST_URL);
  assert.equal(h.calls[0].options.cache, "default");
  assert.match(h.document.nodes.summary.textContent, /^Latest archived cycle:/);
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

test("a missing compact snapshot falls back to the full archive", async () => {
  const payload = archive("fallback archive");
  const h = makeHarness(async (url) => {
    if (url === LATEST_URL) return { ok: false, status: 404 };
    return { ok: true, status: 200, json: async () => payload };
  });

  assert.equal(await h.controller.refresh(false), true);
  assert.deepEqual(h.calls.map((call) => call.url), [LATEST_URL, ARCHIVE_URL]);
  assert.match(h.document.nodes.summary.textContent, /2 archived cycles/);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "fallback archive");
});

test("a malformed compact snapshot falls back to the canonical archive", async () => {
  const storage = makeMemoryStorage();
  const payload = archive("valid full archive");
  const h = makeHarness(async (url) => {
    if (url === LATEST_URL) {
      return { ok: true, status: 200, json: async () => { throw new SyntaxError("invalid JSON"); } };
    }
    return { ok: true, status: 200, json: async () => payload };
  }, 1000, storage);

  assert.equal(await h.controller.refresh(false), true);
  assert.deepEqual(h.calls.map((call) => call.url), [LATEST_URL, ARCHIVE_URL]);
  assert.equal(storage.values.get(SNAPSHOT_MISSING_KEY), String(1000 + SNAPSHOT_MISSING_RECHECK_MS));
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "valid full archive");
});

test("a schema-invalid compact snapshot falls back to the canonical archive", async () => {
  const payload = archive("schema fallback");
  const h = makeHarness(async (url) => {
    if (url === LATEST_URL) {
      return {
        ok: true,
        status: 200,
        json: async () => [{ time: "2026-11-07T04:00:00Z", experiments: "not-an-array" }]
      };
    }
    return { ok: true, status: 200, json: async () => payload };
  });

  assert.equal(await h.controller.refresh(false), true);
  assert.deepEqual(h.calls.map((call) => call.url), [LATEST_URL, ARCHIVE_URL]);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "schema fallback");
});

test("a transient compact-snapshot server error does not mask or bypass the error", async () => {
  const storage = makeMemoryStorage();
  const h = makeHarness(async () => ({ ok: false, status: 503 }), 1000, storage);

  assert.equal(await h.controller.refresh(false), false);
  assert.deepEqual(h.calls.map((call) => call.url), [LATEST_URL]);
  assert.equal(storage.getItem(SNAPSHOT_MISSING_KEY), null);
  assert.match(h.document.nodes.status.textContent, /temporarily unavailable/);
});

test("a missing compact snapshot is cached across page reloads", async () => {
  const storage = makeMemoryStorage();
  const first = makeHarness(async (url) => {
    if (url === LATEST_URL) return { ok: false, status: 404 };
    return { ok: true, json: async () => archive("full archive") };
  }, 1000, storage);

  assert.equal(await first.controller.refresh(false), true);
  assert.equal(storage.values.get(SNAPSHOT_MISSING_KEY), String(1000 + SNAPSHOT_MISSING_RECHECK_MS));

  const second = makeHarness(async (url) => {
    assert.equal(url, ARCHIVE_URL, "known-missing snapshot should be skipped");
    return { ok: true, json: async () => archive("cached fallback") };
  }, 1000 + REFRESH_MS, storage);

  assert.equal(await second.controller.refresh(false), true);
  assert.deepEqual(second.calls.map((call) => call.url), [ARCHIVE_URL]);
});

test("manual refresh bypasses the missing-snapshot cache", async () => {
  const storage = makeMemoryStorage();
  const h = makeHarness(async (url) => {
    if (url === LATEST_URL) return { ok: false, status: 404 };
    return { ok: true, json: async () => archive("manual fallback") };
  }, 1000, storage);

  assert.equal(await h.controller.refresh(false), true);
  assert.equal(await h.controller.refresh(true), true);
  assert.deepEqual(h.calls.map((call) => call.url), [
    LATEST_URL, ARCHIVE_URL, LATEST_URL, ARCHIVE_URL
  ]);
});

test("the missing-snapshot cache expires and retries publication checks", async () => {
  const storage = makeMemoryStorage();
  const h = makeHarness(async (url) => {
    if (url === LATEST_URL) return { ok: false, status: 404 };
    return { ok: true, json: async () => archive("expiry fallback") };
  }, 1000, storage);

  assert.equal(await h.controller.refresh(false), true);
  h.advance(SNAPSHOT_MISSING_RECHECK_MS);
  assert.equal(await h.controller.refresh(false), true);
  assert.deepEqual(h.calls.map((call) => call.url), [
    LATEST_URL, ARCHIVE_URL, LATEST_URL, ARCHIVE_URL
  ]);
});

test("publishing the compact snapshot clears the negative cache", async () => {
  const storage = makeMemoryStorage();
  storage.setItem(SNAPSHOT_MISSING_KEY, String(1000 + SNAPSHOT_MISSING_RECHECK_MS));
  const h = makeHarness(async (url) => {
    assert.equal(url, LATEST_URL);
    return { ok: true, json: async () => archive("new compact snapshot").slice(0, 1) };
  }, 1000, storage);

  assert.equal(await h.controller.refresh(true), true);
  assert.equal(storage.getItem(SNAPSHOT_MISSING_KEY), null);
  assert.deepEqual(h.calls.map((call) => call.url), [LATEST_URL]);
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
  assert.equal(h.calls[2].options.cache, "reload");
});

test("manual cache-bypass refreshes have a bounded cooldown", async () => {
  const h = makeHarness(async () => ({ ok: true, json: async () => archive() }));

  assert.equal(await h.controller.refresh(true), true);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].options.cache, "reload");

  assert.equal(await h.controller.refresh(true), false);
  assert.equal(h.calls.length, 1);
  assert.match(h.document.nodes.status.textContent, /wait before refreshing again/i);

  h.advance(RETRY_MS - 1);
  assert.equal(await h.controller.refresh(true), false);
  assert.equal(h.calls.length, 1);

  h.advance(1);
  assert.equal(await h.controller.refresh(true), true);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].options.cache, "reload");
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

test("saved public archive renders immediately and remains visible when refresh fails", async () => {
  const saved = archive("saved public cycle");
  const storage = {
    getItem(key) {
      if (key === SNAPSHOT_MISSING_KEY) return null;
      assert.equal(key, STORAGE_KEY);
      return JSON.stringify(saved);
    },
    setItem() { throw new Error("storage should not be written on a failed fetch"); }
  };
  const h = makeHarness(async () => {
    throw new Error("private transport detail");
  }, 1000, storage);

  // The last successful public archive is rendered before any network request.
  assert.match(h.document.nodes.status.textContent, /saved archive while checking for updates/i);
  assert.match(h.document.nodes.summary.textContent, /2 archived cycles/);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "saved public cycle");

  assert.equal(await h.controller.refresh(false), false);
  assert.match(h.document.nodes.status.textContent, /showing last good copy \(may be stale\)/i);
  assert.equal(h.document.nodes.experiments.children.length, 1);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "saved public cycle");
  assert.doesNotMatch(h.document.nodes.status.textContent, /private transport detail/);
});

test("invalid or unavailable local storage never blocks a fresh archive response", async () => {
  const writes = [];
  const storage = {
    getItem() { return "{invalid json"; },
    setItem(key, value) { writes.push({ key, value }); }
  };
  const h = makeHarness(async () => ({ ok: true, json: async () => archive("fresh archive") }), 1000, storage);
  assert.equal(h.document.nodes.summary.textContent, "");
  assert.equal(await h.controller.refresh(false), true);
  assert.match(h.document.nodes.summary.textContent, /2 archived cycles/);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].key, STORAGE_KEY);
  assert.equal(JSON.parse(writes[0].value)[0].experiments[0].name, "fresh archive");

  const throwingStorage = {
    getItem() { throw new Error("storage blocked"); },
    setItem() { throw new Error("storage quota"); }
  };
  const fallback = makeHarness(async () => ({ ok: true, json: async () => archive("network still works") }), 1000, throwingStorage);
  assert.equal(await fallback.controller.refresh(false), true);
  assert.equal(fallback.document.nodes.experiments.children[0].children[0].textContent, "network still works");
});

test("a failed refresh retains the last good copy in memory", async () => {
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
  assert.match(h.document.nodes.summary.textContent, /archived cycles/);
  assert.equal(h.document.nodes.experiments.children.length, 1);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "last good cycle");
  assert.match(h.document.nodes.status.textContent, /last good copy \(may be stale\)/i);
  assert.doesNotMatch(h.document.nodes.status.textContent, /private transport detail/);
});

test("last good copy remains visible when browser storage writes fail", async () => {
  let attempt = 0;
  const storage = {
    getItem() { return null; },
    setItem() { throw new Error("storage quota"); }
  };
  const h = makeHarness(async () => {
    attempt += 1;
    if (attempt === 1) return { ok: true, json: async () => archive("in-memory last good") };
    throw new Error("private transport detail");
  }, 1000, storage);

  assert.equal(await h.controller.refresh(false), true);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "in-memory last good");

  h.advance(REFRESH_MS);
  assert.equal(await h.controller.refresh(false), false);
  assert.match(h.document.nodes.status.textContent, /last good copy \(may be stale\)/i);
  assert.match(h.document.nodes.summary.textContent, /archived cycles/);
  assert.equal(h.document.nodes.experiments.children[0].children[0].textContent, "in-memory last good");
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
  const policy = html.match(/<meta http-equiv="Content-Security-Policy" content="([^"]+)">/i);
  assert.ok(policy, "static preview must declare a restrictive Content Security Policy");
  assert.ok(policy[1].includes("default-src 'none'"));
  assert.ok(policy[1].includes("script-src 'self'"));
  assert.ok(policy[1].includes("connect-src https://raw.githubusercontent.com"));
  assert.ok(policy[1].includes("object-src 'none'"));
  assert.ok(!policy[1].includes("unsafe-eval"));
  assert.match(html, /<meta name="referrer" content="no-referrer">/i);
  assert.match(html, /<meta name="robots" content="noindex, nofollow">/i);
  assert.doesNotMatch(html, /@import\s+url|url\(\s*["']?https?:/i);
});


test("static preview transfer budget and external data dependency stay bounded", () => {
  const html = fs.readFileSync(path.join(__dirname, "../cdn-preview/index.html"));
  const script = fs.readFileSync(path.join(__dirname, "../cdn-preview/app.js"));
  const htmlBytes = html.byteLength;
  const scriptBytes = script.byteLength;
  const totalBytes = htmlBytes + scriptBytes;

  // Raw source bytes are a reproducible upper bound before HTTP compression.
  assert.ok(scriptBytes <= 10 * 1024, `app.js is ${scriptBytes} bytes; budget is 10240`);
  assert.ok(totalBytes <= 13 * 1024, `HTML + JS are ${totalBytes} bytes; budget is 13312`);

  const source = script.toString("utf8");
  const absoluteUrls = [...source.matchAll(/https?:\/\/[^"'\s]+/g)].map((match) => match[0]);
  assert.deepEqual(absoluteUrls, [LATEST_URL, ARCHIVE_URL], "only the compact snapshot and its fallback may be external");
  assert.equal(source.split("fetchImpl(LATEST_URL").length - 1, 1);
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



test("static preview keeps its dependency surface small and same-origin", () => {
  const html = fs.readFileSync(path.join(__dirname, "../cdn-preview/index.html"), "utf8");
  const scriptSources = [...html.matchAll(/<script\b[^>]*\bsrc=["']([^"']+)["'][^>]*>/gi)]
    .map((match) => match[1]);
  const stylesheetLinks = [...html.matchAll(/<link\b[^>]*\brel=["']stylesheet["'][^>]*>/gi)];
  const preconnects = [...html.matchAll(/<link\b[^>]*\brel=["']preconnect["'][^>]*>/gi)]
    .map((match) => match[0]);

  // Keep first paint independent of third-party scripts, fonts, and stylesheets.
  assert.deepEqual(scriptSources, ["./app.js"]);
  assert.match(html, /<script src=["']\.\/app\.js["'] defer>/i);
  assert.equal(stylesheetLinks.length, 0);
  assert.equal(preconnects.length, 1);
  assert.match(preconnects[0], /href=["']https:\/\/raw\.githubusercontent\.com["']/i);

  // The only cross-origin network destination is the public read-only archive.
  assert.match(html, /Content-Security-Policy/);
  assert.match(html, /default-src 'none'/);
  assert.match(html, /script-src 'self'/);
  assert.match(html, /connect-src https:\/\/raw\.githubusercontent\.com/);
  assert.doesNotMatch(html, /fonts\.googleapis|fonts\.gstatic|googletagmanager|doubleclick/i);
});
