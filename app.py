import os
import random
import sqlite3
import math
import pathlib
import json
import time
from collections import deque
from threading import BoundedSemaphore, Lock
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template

app = Flask(__name__)
DB = os.environ.get('DATABASE_PATH', '/tmp/aether.sqlite3')
RESEARCH_JSON_PATH = pathlib.Path(__file__).resolve().parent / "data" / "research.json"

# Best-effort, per-process protection for the public demo. This is not
# distributed rate limiting: separate workers/instances have separate budgets.
RUN_WINDOW_SECONDS = 60
RUN_MAX_PER_WINDOW = 20
RUN_MAX_IN_FLIGHT = 2
_run_clock = time.monotonic
_run_times = deque()
_run_lock = Lock()
_run_slots = BoundedSemaphore(RUN_MAX_IN_FLIGHT)

def connect():
    c = sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY, created TEXT, hypothesis TEXT, trials INTEGER, estimate REAL, expected REAL, deviation REAL, status TEXT)')
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


@app.get('/')
def home():
    return render_template('index.html')

@app.get('/api/results')
def results():
    with connect() as c:
        rows = c.execute('SELECT id,created,hypothesis,trials,estimate,expected,deviation,status FROM experiments ORDER BY id DESC LIMIT 100').fetchall()
    return jsonify([dict(zip(['id','created','hypothesis','trials','estimate','expected','deviation','status'], r)) for r in rows])

@app.post('/api/run')
def run():
    # Bound both simultaneous work and admitted requests per Python process.
    if not _run_slots.acquire(blocking=False):
        return _limited_response(1)
    try:
        retry_after = _admit_demo_run()
        if retry_after:
            return _limited_response(retry_after)

        # Reproducible mathematical baseline: estimate pi via uniform sampling.
        n = 20000
        inside = sum(random.random()**2 + random.random()**2 <= 1 for _ in range(n))
        estimate = 4 * inside / n
        deviation = abs(estimate - math.pi)
        with connect() as c:
            c.execute('INSERT INTO experiments(created,hypothesis,trials,estimate,expected,deviation,status) VALUES(?,?,?,?,?,?,?)',
                      (datetime.now(timezone.utc).isoformat(), 'Monte Carlo circle-area estimate of pi', n, estimate, math.pi, deviation, 'completed'))
        return jsonify({'estimate': estimate, 'expected': math.pi, 'deviation': deviation, 'trials': n})
    finally:
        _run_slots.release()

@app.get('/api/research')
def research_data():
    """Returns local scheduled research history from data/research.json."""
    try:
        if not RESEARCH_JSON_PATH.exists():
            return jsonify([])
        data = json.loads(RESEARCH_JSON_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        # Archive errors are not public diagnostics; never return filesystem details.
        return jsonify({"error": "Research archive temporarily unavailable."}), 500
    return jsonify(data)

@app.get('/health')
def health():
    # Render supplies the deployed Git SHA. Expose only a validated revision,
    # never arbitrary environment content or configuration secrets.
    revision = os.environ.get('RENDER_GIT_COMMIT', '')
    payload = {'status': 'ok'}
    if len(revision) == 40 and all(ch in '0123456789abcdefABCDEF' for ch in revision):
        payload['revision'] = revision.lower()
    return jsonify(payload)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
