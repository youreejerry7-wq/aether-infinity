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
      () => document.querySelector("#status")?.textContent === "Latest archive record loaded",
      null,
      { timeout: 20000 }
    );
    const dataReadyMs = Date.now() - started;

    const pageMetrics = await page.evaluate(() => {
      const navigationEntry = performance.getEntriesByType("navigation")[0];
      const resources = performance.getEntriesByType("resource");
      return {
        domContentLoadedMs: Math.round(navigationEntry?.domContentLoadedEventEnd || 0),
        loadEventMs: Math.round(navigationEntry?.loadEventEnd || 0),
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
    const decodedResponseBodyBytes = responseRecords.reduce(
      (total, response) => total + response.bodyBytes,
      0
    );

    assert.match(summary || "", /(Latest archived cycle:|archived cycles · latest:)/);
    assert.equal(status, "Latest archive record loaded");
    assert.ok(renderedRows > 0, "the public archive should render at least one experiment row");
    assert.ok(externalRequests.length <= 2, "the initial view should make at most two archive requests");
    assert.deepEqual(unexpectedExternal, [], "only the public GitHub Raw archive may be contacted");
    assert.deepEqual(flaskOrApiRequests, [], "the static preview must not wake or call the Flask service");
    assert.ok(
      rawArchiveResponses.some((response) => response.status === 200),
      "at least one canonical public archive response must succeed"
    );
    assert.ok(decodedResponseBodyBytes <= 150000, "initial HTML, JS, and archive payload should stay below 150 KB");
    assert.ok(dataReadyMs <= 20000, "archive data should become visible within the 20-second smoke budget");

    console.log(JSON.stringify({
      result: "PASS",
      previewUrl,
      htmlStatus: navigation.status(),
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
