"use strict";

const assert = require("node:assert/strict");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

async function main() {
  const previewUrl = process.env.PREVIEW_URL || "https://aether-cdn-preview.onrender.com/";
  const previewOrigin = new URL(previewUrl).origin;
  const browser = await chromium.launch({ headless: true });

  try {
    const context = await browser.newContext({ serviceWorkers: "block" });
    const page = await context.newPage();
    const requestUrls = [];
    const responseRecords = [];
    const responseTasks = [];

    page.on("request", (request) => requestUrls.push(request.url()));
    page.on("response", (response) => {
      responseTasks.push((async () => {
        let bytes = 0;
        try {
          bytes = (await response.body()).byteLength;
        } catch (_) {
          // A body can be unavailable for a cached or bodyless response.
        }
        responseRecords.push({
          url: response.url(),
          status: response.status(),
          bodyBytes: bytes
        });
      })());
    });

    const started = Date.now();
    const navigation = await page.goto(previewUrl, {
      waitUntil: "domcontentloaded",
      timeout: 30000
    });
    assert.ok(navigation, "navigation should return an HTTP response");
    assert.equal(navigation.status(), 200, "static preview HTML should return HTTP 200");

    await page.waitForFunction(
      () => {
        const status = document.querySelector("#status")?.textContent || "";
        return status === "Latest archive record loaded" ||
          status.startsWith("Latest archive record loaded. Archive is stale (>90m);");
      },
      null,
      { timeout: 20000 }
    );
    const dataReadyMs = Date.now() - started;

    const pageMetrics = await page.evaluate(() => {
      const navigationEntry = performance.getEntriesByType("navigation")[0];
      const resources = performance.getEntriesByType("resource");
      return {
        navigationTtfbMs: Math.round(navigationEntry?.responseStart || 0),
        domContentLoadedMs: Math.round(navigationEntry?.domContentLoadedEventEnd || 0),
        loadEventMs: Math.round(navigationEntry?.loadEventEnd || 0),
        navigationTransferBytes: navigationEntry?.transferSize || 0,
        navigationDecodedBytes: navigationEntry?.decodedBodySize || 0,
        resourceCount: resources.length
      };
    });
    const summary = await page.locator("#summary").textContent();
    const status = await page.locator("#status").textContent();
    const renderedRows = await page.locator("#experiments tr").count();

    await Promise.all(responseTasks);
    const externalRequests = requestUrls.filter(
      (url) => new URL(url).origin !== previewOrigin
    );
    const unexpectedExternal = externalRequests.filter(
      (url) => new URL(url).hostname !== "raw.githubusercontent.com"
    );
    const flaskOrApiRequests = requestUrls.filter((url) => {
      const parsed = new URL(url);
      return (
        parsed.hostname === "aether-infinity.onrender.com" ||
        parsed.pathname.startsWith("/api/") ||
        parsed.pathname === "/health"
      );
    });
    const rawArchiveResponses = responseRecords.filter(
      (response) =>
        response.url.startsWith("https://raw.githubusercontent.com/") &&
        response.url.includes("/data/research")
    );
    const compactSnapshotResponses = responseRecords.filter((response) =>
      response.url.includes("/data/research-latest.json")
    );
    const compactSnapshotLoaded = compactSnapshotResponses.some(
      (response) => response.status === 200
    );
    const fullArchiveLoaded = rawArchiveResponses.some(
      (response) =>
        response.url.endsWith("/data/research.json") && response.status === 200
    );
    const decodedResponseBodyBytes = responseRecords.reduce(
      (total, response) => total + response.bodyBytes,
      0
    );

    assert.match(summary || "", /(Latest archived cycle:|archived cycles · latest:)/);
    assert.ok(
      status === "Latest archive record loaded" ||
        status.startsWith("Latest archive record loaded. Archive is stale (>90m);"),
      "the latest archive must be visibly loaded, with a stale warning when older than 90 minutes"
    );
    if (status !== "Latest archive record loaded") {
      assert.match(summary || "", /STALE$/);
    }
    assert.ok(renderedRows > 0, "the public archive should render at least one experiment row");
    assert.ok(
      externalRequests.length <= 2,
      "initial view may request one compact snapshot plus one full-archive fallback"
    );
    assert.deepEqual(unexpectedExternal, [], "only the public GitHub Raw archive may be contacted");
    assert.deepEqual(flaskOrApiRequests, [], "the static preview must not wake or call the Flask service");
    assert.ok(
      rawArchiveResponses.some((response) => response.status === 200),
      "at least one public compact-snapshot or canonical-archive response must succeed"
    );
    // Generous CI guardrails for the isolated static CDN preview, not a global SLA.
    assert.ok(pageMetrics.navigationTtfbMs > 0 && pageMetrics.navigationTtfbMs <= 3000,
      "static HTML TTFB should stay within the 3-second preview budget");
    assert.ok(pageMetrics.domContentLoadedMs > 0 && pageMetrics.domContentLoadedMs <= 3000,
      "DOMContentLoaded should stay within the 3-second preview budget");
    assert.ok(decodedResponseBodyBytes <= 150000, "initial HTML, JS, and archive payload should stay below 150 KB");
    if (compactSnapshotLoaded) {
      assert.equal(fullArchiveLoaded, false,
        "a valid compact snapshot must be used even when stale; the UI carries the stale warning");
      const compactSnapshotResponse = compactSnapshotResponses.find(
        (response) => response.status === 200
      );
      assert.ok(
        compactSnapshotResponse.bodyBytes > 0 && compactSnapshotResponse.bodyBytes <= 2048,
        "a fresh compact snapshot must be nonempty and no larger than 2 KiB"
      );
      assert.equal(externalRequests.length, 1,
        "a fresh compact snapshot should require exactly one external archive request");
      assert.ok(decodedResponseBodyBytes <= 25000,
        "compact-snapshot initial HTML, JS, and data payload should stay below 25 KB");
    } else {
      assert.ok(
        fullArchiveLoaded,
        "a stale, missing, or invalid compact snapshot must fall back to the canonical archive"
      );
      assert.equal(externalRequests.length, 2,
        "snapshot fallback should make exactly one compact attempt and one canonical request");
      assert.ok(
        externalRequests.some((url) => url.includes("/data/research-latest.json")),
        "the compact snapshot endpoint should be attempted before the canonical fallback"
      );
    }
    assert.ok(dataReadyMs <= 8000, "archive data should become visible within the 8-second preview budget");

    console.log(JSON.stringify({
      result: "PASS",
      previewUrl,
      htmlStatus: navigation.status(),
      compactSnapshotLoaded,
      fullArchiveLoaded,
      snapshotFallbackReason: fullArchiveLoaded
        ? (compactSnapshotLoaded ? "stale_or_invalid_snapshot" : "snapshot_unavailable")
        : null,
      dataReadyMs,
      ...pageMetrics,
      externalRequestCount: externalRequests.length,
      externalRequests,
      decodedResponseBodyBytes,
      responseStatuses: responseRecords.map(({ url, status, bodyBytes }) => ({
        url,
        status,
        bodyBytes
      })),
      renderedRows,
      flaskOrApiRequests: flaskOrApiRequests.length
    }, null, 2));
    await context.close();
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
