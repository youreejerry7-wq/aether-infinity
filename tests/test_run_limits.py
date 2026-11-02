"""Offline, disposable-DB regression checks for public demo compute bounds."""
import os
import tempfile
import unittest
from unittest.mock import patch

import app as demo


class DemoRunLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.db_patch = patch.object(demo, "DB", os.path.join(self.temp.name, "test.sqlite3"))
        self.clock_patch = patch.object(demo, "_run_clock", lambda: self.now)
        self.db_patch.start()
        self.clock_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.clock_patch.stop)
        with demo._run_lock:
            demo._run_times.clear()
        demo.app.config["TESTING"] = True
        self.client = demo.app.test_client()

    def tearDown(self):
        with demo._run_lock:
            demo._run_times.clear()

    def test_accepted_run_retains_original_response_and_writes_one_row(self):
        response = self.client.post("/api/run")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["trials"], 20000)
        self.assertIn("estimate", response.json)
        rows = self.client.get("/api/results")
        self.assertEqual(rows.status_code, 200)
        self.assertEqual(len(rows.json), 1)

    def test_window_rejects_extra_runs_without_database_writes(self):
        for _ in range(demo.RUN_MAX_PER_WINDOW):
            self.assertEqual(self.client.post("/api/run").status_code, 200)
        rejected = self.client.post("/api/run")
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(rejected.headers["Retry-After"], "60")
        self.assertEqual(len(self.client.get("/api/results").json), demo.RUN_MAX_PER_WINDOW)
        self.assertNotIn("sqlite", rejected.get_data(as_text=True).lower())
        self.now += demo.RUN_WINDOW_SECONDS
        self.assertEqual(self.client.post("/api/run").status_code, 200)
        self.assertEqual(len(self.client.get("/api/results").json), demo.RUN_MAX_PER_WINDOW + 1)

    def test_concurrency_cap_rejects_without_consuming_window(self):
        self.assertTrue(demo._run_slots.acquire(blocking=False))
        self.assertTrue(demo._run_slots.acquire(blocking=False))
        try:
            rejected = self.client.post("/api/run")
            self.assertEqual(rejected.status_code, 429)
            self.assertEqual(rejected.headers["Retry-After"], "1")
            self.assertEqual(len(demo._run_times), 0)
        finally:
            demo._run_slots.release()
            demo._run_slots.release()
        self.assertEqual(self.client.post("/api/run").status_code, 200)

    def test_read_only_routes_work_when_demo_is_limited(self):
        for _ in range(demo.RUN_MAX_PER_WINDOW):
            self.assertEqual(self.client.post("/api/run").status_code, 200)
        self.assertEqual(self.client.post("/api/run").status_code, 429)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/results").status_code, 200)


    def test_rolling_window_expires_only_oldest_request(self):
        # This is a sliding window, not a reset at an arbitrary minute boundary.
        self.assertEqual(self.client.post("/api/run").status_code, 200)
        self.now += 1
        for _ in range(demo.RUN_MAX_PER_WINDOW - 1):
            self.assertEqual(self.client.post("/api/run").status_code, 200)
        self.now += demo.RUN_WINDOW_SECONDS - 2
        blocked = self.client.post("/api/run")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers["Retry-After"], "1")
        self.now += 1
        self.assertEqual(self.client.post("/api/run").status_code, 200)
        blocked = self.client.post("/api/run")
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers["Retry-After"], "1")

    def test_failed_computation_releases_slot_for_next_request(self):
        # A synthetic exception must not permanently exhaust concurrency.
        with patch.object(demo.random, "random", side_effect=RuntimeError("synthetic failure")):
            with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                self.client.post("/api/run")
        self.assertEqual(self.client.post("/api/run").status_code, 200)
        self.assertEqual(len(self.client.get("/api/results").json), 1)


if __name__ == "__main__":
    unittest.main()
