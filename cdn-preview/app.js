/* Read-only CDN preview. Deliberately never calls the Flask API. */
(function (root) {
  "use strict";

  const ARCHIVE_URL =
    "https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity/main/data/research.json";
  const REFRESH_MS = 5 * 60 * 1000;
  const RETRY_MS = 30 * 1000;
  const REQUEST_TIMEOUT_MS = 10 * 1000;
  const MAX_EXPERIMENTS = 50;
  const STORAGE_KEY = "aether.archive.preview.v1";

  function isUsableArchive(data) {
    const latest = Array.isArray(data) ? data[0] : null;
    return Boolean(
      latest &&
      typeof latest === "object" &&
      !Array.isArray(latest) &&
      typeof latest.time === "string" &&
      !Number.isNaN(Date.parse(latest.time)) &&
      Array.isArray(latest.experiments)
    );
  }

  function createController(options) {
    const doc = options.document;
    const fetchImpl = options.fetchImpl;
    const now = options.now || Date.now;
    const setTimeoutImpl = options.setTimeoutImpl || setTimeout;
    const clearTimeoutImpl = options.clearTimeoutImpl || clearTimeout;
    const AbortControllerImpl = options.AbortControllerImpl || AbortController;
    const storage = options.storage || null;

    let inFlight = false;
    let hasDisplayedArchive = false;
    let nextAllowedAt = -Infinity;
    let timer = null;

    function setStatus(message) {
      doc.getElementById("status").textContent = message;
    }

    function schedule(delay) {
      if (timer !== null) clearTimeoutImpl(timer);
      timer = setTimeoutImpl(function () {
        timer = null;
        void refresh(false);
      }, delay);
    }

    function render(data, statusMessage) {
      const latest = data[0];
      const timestamp = new Date(latest.time).toLocaleString();
      const summary = doc.getElementById("summary");
      const body = doc.getElementById("experiments");
      const note = doc.getElementById("note");

      summary.textContent =
        data.length + " archived cycles · latest: " + timestamp;
      setStatus(statusMessage || "Latest archive record loaded");
      body.replaceChildren();

      const experiments = latest.experiments.slice(0, MAX_EXPERIMENTS);
      for (const experiment of experiments) {
        const row = doc.createElement("tr");
        const values = [
          String(experiment && experiment.name || "Unnamed experiment"),
          experiment && experiment.category === "known_baseline"
            ? "Known baseline"
            : experiment && experiment.category === "candidate"
              ? "Unverified candidate"
              : "Simulated statistic",
          String(experiment && experiment.observed != null ? experiment.observed : ""),
          String(experiment && experiment.expected != null ? experiment.expected : ""),
          String(experiment && experiment.z_score != null ? experiment.z_score : ""),
          experiment && experiment.flag ? "Review flag" : "No flag"
        ];
        for (const value of values) {
          const cell = doc.createElement("td");
          cell.textContent = value;
          row.appendChild(cell);
        }
        body.appendChild(row);
      }

      if (experiments.length === 0) {
        const row = doc.createElement("tr");
        const cell = doc.createElement("td");
        cell.textContent = "No experiment records in the latest cycle.";
        row.appendChild(cell);
        body.appendChild(row);
      }

      const truncated = latest.experiments.length > MAX_EXPERIMENTS;
      const errorSummary = Array.isArray(latest.errors)
        ? latest.errors.length + " recorded cycle errors. "
        : "Cycle-level error details are not included in this archive. ";
      const interpretation = typeof latest.interpretation === "string"
        ? latest.interpretation + " "
        : "";
      const caution = /not discoveries/i.test(interpretation)
        ? ""
        : "Statistical flags are prompts for replication, not discoveries.";
      note.textContent =
        (truncated ? "Showing " + MAX_EXPERIMENTS + " of " + latest.experiments.length + " experiments. " : "") +
        errorSummary + interpretation + caution;
    }

    function readCachedArchive() {
      if (!storage || typeof storage.getItem !== "function") return null;
      try {
        const raw = storage.getItem(STORAGE_KEY);
        if (!raw) return null;
        const cached = JSON.parse(raw);
        return isUsableArchive(cached) ? cached : null;
      } catch (_) {
        return null;
      }
    }

    function saveCachedArchive(data) {
      if (!storage || typeof storage.setItem !== "function") return false;
      try {
        storage.setItem(STORAGE_KEY, JSON.stringify(data));
        hasDisplayedArchive = true;
        return true;
      } catch (_) {
        return false;
      }
    }

    async function refresh(force) {
      if (doc.hidden || inFlight) return false;
      if (!force && now() < nextAllowedAt) {
        schedule(nextAllowedAt - now());
        return false;
      }

      inFlight = true;
      const button = doc.getElementById("refresh");
      button.disabled = true;
      const controller = new AbortControllerImpl();
      const timeout = setTimeoutImpl(
        function () { controller.abort(); },
        REQUEST_TIMEOUT_MS
      );

      try {
        // Stable URL + normal browser caching; no cache-busting query or no-store.
        const response = await fetchImpl(ARCHIVE_URL, {
          // Automatic refreshes honor the HTTP cache; an explicit button click
          // bypasses a still-fresh cached response so it actually refreshes.
          cache: force ? "reload" : "default",
          signal: controller.signal
        });
        if (!response || !response.ok) throw new Error("archive_unavailable");
        const data = await response.json();
        if (!isUsableArchive(data)) throw new Error("archive_invalid");

        render(data);
        hasDisplayedArchive = true;
        saveCachedArchive(data);
        nextAllowedAt = now() + REFRESH_MS;
        schedule(REFRESH_MS);
        return true;
      } catch (_) {
        if (hasDisplayedArchive) {
            setStatus("Archive update unavailable; showing last good copy (may be stale). The Flask API was not contacted.");
        } else {
          doc.getElementById("summary").textContent = "";
          doc.getElementById("experiments").replaceChildren();
          doc.getElementById("note").textContent =
            "No current archive data is displayed. Statistical flags are prompts for replication, not discoveries.";
          setStatus("Archive temporarily unavailable. The Flask API was not contacted.");
        }
        nextAllowedAt = now() + RETRY_MS;
        schedule(RETRY_MS);
        return false;
      } finally {
        clearTimeoutImpl(timeout);
        inFlight = false;
        button.disabled = false;
      }
    }

    function bind() {
      doc.getElementById("refresh").addEventListener("click", function () {
        void refresh(true);
      });
      doc.addEventListener("visibilitychange", function () {
        if (!doc.hidden) return refresh(false);
      });
    }

    const cached = readCachedArchive();
    if (cached) {
      hasDisplayedArchive = true;
      render(cached, "Showing saved archive while checking for updates");
    }

    return { bind, refresh };
  }

  const api = {
    ARCHIVE_URL,
    REFRESH_MS,
    RETRY_MS,
    REQUEST_TIMEOUT_MS,
    MAX_EXPERIMENTS,
    STORAGE_KEY,
    isUsableArchive,
    createController
  };

  root.AetherCdnPreview = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }

  if (root.document && typeof root.fetch === "function") {
    let storage = null;
    try { storage = root.localStorage; } catch (_) {}
    const controller = createController({
      document: root.document,
      fetchImpl: root.fetch.bind(root),
      now: function () { return Date.now(); },
      setTimeoutImpl: root.setTimeout.bind(root),
      clearTimeoutImpl: root.clearTimeout.bind(root),
      AbortControllerImpl: root.AbortController,
      storage
    });
    controller.bind();
    void controller.refresh(false);
  }
})(globalThis);
