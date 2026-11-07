"""AETHER public mathematical demonstration (no scientific-discovery claims)."""
import math
import os
import random
import sqlite3
import time
from collections import deque
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock

from flask import Flask, jsonify, render_template

app = Flask(__name__)
DB = os.environ.get("DATABASE_PATH", "/tmp/aether.sqlite3")

# Best-effort, per-process protection for the public demo only. This is NOT
# distributed rate limiting: multiple workers/instances each have a budget.
RUN_WINDOW_SECONDS = 60
RUN_MAX_PER_WINDOW = 20
RUN_MAX_IN_FLIGHT = 2
_run_clock = time.monotonic
_run_times = deque()
_run_lock = Lock()
_run_slots = BoundedSemaphore(RUN_MAX_IN_FLIGHT)


def connect():
    c = sqlite3.connect(DB)
    c.execute(
        "CREATE TABLE IF NOT EXISTS experiments("
        "id INTEGER PRIMARY KEY,created TEXT, hypothesis TEXT, trials INTEGER,"
        " estimate REAL, expected REAL, deviation REAL, status TEXT)"
    )
    return c


def _admit_demo_run():
    """Return seconds until retry, or 0 if this process admits the request."""
    with _run_lock:
        now = _run_clock()
        while _run_times and now - _run_times[0] >= RUN_WINDOW_SECONDS:
            _run_times.popleft()
        if len(_run_times) >= RUN_MAX_PER_WINDOW:
            return max(1, math.ceil(RUN_WINDOW_SECONDS - (now - _run_times[0])))
        _run_times.append(now)
        return 0


def _limited_response(seconds):
    response = jsonify(error="Demo temporarily busy. Please retry later.")
    response.status_code = 429
    response.headers["Retry-After"] = str(seconds)
    return response


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/results")
def results():
    with connect() as c:
        rows = c.execute(
            "SELECT id,created,hypothesis,trials,estimate,expected,deviation,status "
            "FROM experiments ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return jsonify([
        dict(zip(
            ["id", "created", "hypothesis", "trials", "estimate", "expected",
             "deviation", "status"], row
        ))
        for row in rows
    ])


@app.post("/api/run")
def run():
    # A concurrency cap prevents a single process from running unbounded
    # simultaneous samples. A rolling window caps the admitted request count.
    if not _run_slots.acquire(blocking=False):
        return _limited_response(1)
    try:
        retry_after = _admit_demo_run()
        if retry_after:
            return _limited_response(retry_after)

        # Reproducible mathematical baseline: estimate pi via uniform sampling.
        n = 20000
        inside = sum(
            random.random() ** 2 + random.random() ** 2 <= 1
            for _ in range(n)
        )
        estimate = 4 * inside / n
        deviation = abs(estimate - math.pi)
        with connect() as c:
            c.execute(
                "INSERT INTO experiments(created,hypothesis,trials,estimate,"
                "expected,deviation,status) VALUES(?,?,?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(),
                 "Monte Carlo circle-area estimate of pi", n, estimate,
                 math.pi, deviation, "completed")
            )
        return jsonify({
            "estimate": estimate, "expected": math.pi,
            "deviation": deviation, "trials": n
        })
    finally:
        _run_slots.release()


@app.get("/health")
def health():
    return jsonify(status="ok")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
