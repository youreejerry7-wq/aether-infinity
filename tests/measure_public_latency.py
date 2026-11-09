#!/usr/bin/env python3
"""Read-only first-observation/repeat latency and payload probe for AETHER.

The first sample is NOT guaranteed to be a cold start. It is simply the first
request made by this GitHub-hosted runner; the immediate repeat is a warm
follow-up candidate. No response bodies are printed or persisted.
"""
import json
import time
import urllib.error
import urllib.request

BASE = "https://aether-infinity.onrender.com"
RAW = "https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity"
BRANCH = "review/cdn-readonly-preview-20261107"
TARGETS = [
    # Hit the homepage first so this run's first request can reveal a sleeping-service delay.
    ("aether_home", BASE + "/", 55, 2),
    ("aether_health", BASE + "/health", 55, 2),
    ("preview_html_source", f"{RAW}/{BRANCH}/cdn-preview/index.html", 25, 1),
    ("preview_js_source", f"{RAW}/{BRANCH}/cdn-preview/app.js", 25, 1),
    ("public_archive", f"{RAW}/main/data/research.json", 25, 1),
]


def request_once(label, url, sample, timeout):
    started = time.perf_counter()
    request = urllib.request.Request(
        url, headers={"User-Agent": "AETHER-read-only-performance-smoke/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers_at = time.perf_counter()
            body = response.read()
            finished = time.perf_counter()
            headers = response.headers
            record = {
                "target": label,
                "sample": sample,
                "status": response.status,
                "ttfb_ms": round((headers_at - started) * 1000, 2),
                "total_ms": round((finished - started) * 1000, 2),
                "bytes": len(body),
                "content_type": headers.get("Content-Type"),
                "content_encoding": headers.get("Content-Encoding"),
                "cache_control": headers.get("Cache-Control"),
                "etag_present": bool(headers.get("ETag")),
                "age": headers.get("Age"),
                "final_url": response.geturl(),
            }
            return record, 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        body = exc.read()
        finished = time.perf_counter()
        return ({
            "target": label, "sample": sample, "status": exc.code,
            "total_ms": round((finished - started) * 1000, 2),
            "bytes": len(body), "error": "HTTP response was not 2xx",
        }, False)
    except Exception as exc:  # DNS/TLS/connect/read errors are transport failures, not HTTP status.
        finished = time.perf_counter()
        return ({
            "target": label, "sample": sample, "status": None,
            "total_ms": round((finished - started) * 1000, 2),
            "error_type": type(exc).__name__,
            "error": str(exc)[:240],
        }, False)


def main():
    failures = []
    for label, url, timeout, samples in TARGETS:
        for index in range(samples):
            sample = "first_observation" if index == 0 else "immediate_repeat"
            success = False
            for attempt in range(1, 3):
                record, success = request_once(label, url, sample, timeout)
                record["attempt"] = attempt
                print(json.dumps(record, sort_keys=True), flush=True)
                if success:
                    break
                # Retry one transient transport error or gateway/rate-limit response.
                status = record.get("status")
                transient = status is None or status in (429, 502, 503, 504)
                if attempt == 1 and transient:
                    time.sleep(2)
                    continue
                break
            if not success:
                failures.append(label + "/" + sample)
    if failures:
        raise SystemExit("Public smoke checks failed: " + ", ".join(failures))
    print("PASS: all read-only public HTTP observations returned 2xx.")


if __name__ == "__main__":
    main()
