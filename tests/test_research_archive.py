"""Read-only integrity checks for the scheduled, simulated research archive.

Do not import research.py here: importing it executes a new research cycle
and rewrites the archive. These tests inspect committed JSON only.
"""
import json
import math
import unittest
from datetime import datetime
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "data" / "research.json"
EXPECTED_NAMES = [
    "Fair coin frequency",
    "Uniform threshold frequency",
    "Monte Carlo pi estimation",
    "Rare-event frequency",
]


class ResearchArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = json.loads(ARCHIVE.read_text(encoding="utf-8"))

    def test_cycle_structure_and_order(self):
        self.assertIsInstance(self.records, list)
        self.assertGreater(len(self.records), 0)
        self.assertLessEqual(len(self.records), 100)
        previous = None
        for index, cycle in enumerate(self.records):
            with self.subTest(cycle=index):
                timestamp = datetime.fromisoformat(cycle["time"])
                self.assertIsNotNone(timestamp.tzinfo)
                self.assertIsNotNone(timestamp.utcoffset())
                if previous is not None:
                    self.assertLessEqual(timestamp, previous)
                previous = timestamp
                self.assertEqual(
                    [item["name"] for item in cycle["experiments"]],
                    EXPECTED_NAMES,
                )
                self.assertIsInstance(cycle["interpretation"], str)
                self.assertTrue(cycle["interpretation"].strip())

    def test_experiment_field_types(self):
        for index, cycle in enumerate(self.records):
            for item in cycle["experiments"]:
                with self.subTest(cycle=index, experiment=item["name"]):
                    for field in ("observed", "expected", "z_score"):
                        value = item[field]
                        self.assertIsInstance(value, (int, float))
                        self.assertNotIsInstance(value, bool)
                        self.assertTrue(math.isfinite(value))
                    self.assertIsInstance(item["trials"], int)
                    self.assertNotIsInstance(item["trials"], bool)
                    self.assertGreater(item["trials"], 0)
                    self.assertIsInstance(item["flag"], bool)


if __name__ == "__main__":
    unittest.main()
