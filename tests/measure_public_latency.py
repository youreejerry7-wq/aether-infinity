#!/usr/bin/env python3
"""Read-only first-observation and warm-repeat latency/payload probe for AETHER.

The first sample is NOT guaranteed to be a cold start. It is simply the first
request made by this GitHub-hosted runner; subsequent requests are warm repeats.
No response bodies are printed or persisted.

Requests advertise gzip support, then count received wire bytes separately
from decoded body size. Warm summaries use the median and maximum of successful
repeat samples; they are not claims about global user experience.
"""
import gzip
import json
import statistics
import time
import urllib.error
import urllib.request

BASE = "https://aether-infinity.onrender.com"
CDN = "https://aether-cdn-preview.onrender.com"
RAW = "https://raw.githubusercontent.com/youreejerry7-wq/aether-infinity"
TARGETS = [
    # Hit the Flask homepage first so an idle-service wake-up can be observed.
    ("aether_home", BASE + "/", 55, 4),
    ("aether_health", BASE + "/health", 55, 4),
    # Measure the actual isolated static site, not just its GitHub source files.
    ("cdn_preview_home", CDN + "/", 20, 4),
    ("cdn_preview_js", CDN + "/app.js", 20, 4),
    ("public_archive", f"{RAW}/main/data/research.json", 25, 4),
]


def decode_body(body, content_encoding):
    """Decode the transfer body while keeping the original wire size measurable."""
    encoding = (content_encoding or "").strip().lower()
    if encoding in ("", "identity"):
        return body
    if encoding == "gzip":
        return gzip.decompress(body)
    raise ValueError("Unsupported content encoding: " + encoding)


def summarize_warm_samples(records):
    """Summarize successful repeat timings, excluding the first observation."""
    warm = [
        record for record in records
        if str(record.get("sample", "")).startswith("warm_repeat_")
        and isinstance(record.get("ttfb_ms"), (int, float))
        and isinstance(record.get("total_ms"), (int, float))
    ]
    if not warm:
        return None
    ttfb = [record["ttfb_ms"] for record in warm]
    total = [record["total_ms"] for record in warm]
    return {
        "count": len(warm),
        "median_ttfb_ms": round(statistics.median(ttfb), 2),
        "max_ttfb_ms": round(max(ttfb), 2),
        "median_total_ms": round(statistics.median(total), 2),
        "max_total_ms": round(max(total), 2),
    }


def request_once(label, url, sample, timeout):
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AETHER-read-only-performance-smoke/1.0",
            "Accept-Encoding": "gzip",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers_at = time.perf_counter()
            wire_body = response.read()
            finished = time.perf_counter()
            headers = response.headers
            decoded_body = decode_body(wire_body, headers.get("Content-Encoding"))
            record = {
                "target": label,
                "sample": sample,
                "status": response.status,
                "ttfb_ms": round((headers_at - started) * 1000, 2),
                "total_ms": round((finished - started) * 1000, 2),
                "bytes": len(wire_body),
                "decoded_bytes": len(decoded_body),
                "wire_fraction": round(len(wire_body) / len(decoded_body), 4)
                    if decoded_body else 1.0,
                "content_type": headers.get("Content-Type"),
                "content_encoding": headers.get("Content-Encoding") or "identity",
                "cache_control": headers.get("Cache-Control"),
                "etag_present": bool(headers.get("ETag")),
                "age": headers.get("Age"),
                "final_url": response.geturl(),
            }
            if label == "public_archive":
                archive = json.loads(decoded_body.decode("utf-8"))
                if not isinstance(archive, list) or not archive:
                    raise ValueError("Public archive must be a nonempty JSON list")
                record["archive_cycles"] = len(archive)
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
        observations = []
        for index in range(samples):
            sample = "first_observation" if index == 0 else f"warm_repeat_{index}"
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
            observations.append(record)
            if not success:
                failures.append(label + "/" + sample)
        summary = summarize_warm_samples(observations)
        if summary:
            print(json.dumps({
                "target": label,
                "sample": "warm_summary",
                **summary,
            }, sort_keys=True), flush=True)
    if failures:
        raise SystemExit("Public smoke checks failed: " + ", ".join(failures))
    print("PASS: all read-only public HTTP observations returned 2xx.")


if __name__ == "__main__":
    main()
