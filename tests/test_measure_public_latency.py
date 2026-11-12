import gzip
import unittest

from measure_public_latency import decode_body


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


if __name__ == "__main__":
    unittest.main()
