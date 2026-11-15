import gzip
import unittest

from measure_public_latency import decode_body, summarize_warm_samples


class DecodeBodyTests(unittest.TestCase):
    def test_identity_body_is_unchanged(self):
        body = b'{"status":"ok"}'
        self.assertEqual(decode_body(body, None), body)
        self.assertEqual(decode_body(body, "identity"), body)

    def test_gzip_body_is_decoded(self):
        original = b'{"cycles":[1,2,3]}'
        compressed = gzip.compress(original, mtime=0)
        self.assertLess(len(compressed), len(original) + 32)
        self.assertEqual(decode_body(compressed, "gzip"), original)

    def test_unknown_encoding_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported content encoding"):
            decode_body(b"data", "br")


class WarmSummaryTests(unittest.TestCase):
    def test_summary_excludes_first_observation_and_uses_successful_warm_samples(self):
        records = [
            {"sample": "first_observation", "ttfb_ms": 900, "total_ms": 950},
            {"sample": "warm_repeat_1", "ttfb_ms": 10, "total_ms": 20},
            {"sample": "warm_repeat_2", "ttfb_ms": 30, "total_ms": 60},
            {"sample": "warm_repeat_3", "ttfb_ms": 20, "total_ms": 40},
            {"sample": "warm_repeat_4", "status": None, "total_ms": 100},
        ]
        self.assertEqual(
            summarize_warm_samples(records),
            {
                "count": 3,
                "median_ttfb_ms": 20,
                "max_ttfb_ms": 30,
                "median_total_ms": 40,
                "max_total_ms": 60,
            },
        )

    def test_summary_is_absent_without_successful_warm_timing_samples(self):
        self.assertIsNone(summarize_warm_samples([
            {"sample": "first_observation", "ttfb_ms": 900, "total_ms": 950},
            {"sample": "warm_repeat_1", "status": None, "total_ms": 100},
        ]))


if __name__ == "__main__":
    unittest.main()
