"""Independent numerical cross-check for the antithetic-pair variance."""

import math
import unittest

from speed_lab import antithetic_unit_variance_midpoint


def independent_variance_reference(intervals=4096):
    """Composite Simpson reference after x=(1-cos(theta))/2 substitution.

    The substitution smooths the square-root endpoint behavior in the
    original x-integral. This is deliberately independent of the 16,384-point
    midpoint rule used by speed_lab.py.
    """
    if intervals <= 0 or intervals % 2:
        raise ValueError("Simpson intervals must be a positive even integer")

    step = math.pi / intervals

    def transformed(theta):
        cosine = math.cos(theta)
        sine = math.sin(theta)
        x = (1.0 - cosine) / 2.0
        complement = (1.0 + cosine) / 2.0
        product = (1.0 - x * x) * (1.0 - complement * complement)
        return math.sqrt(max(0.0, product)) * sine / 2.0

    odd = math.fsum(transformed(i * step) for i in range(1, intervals, 2))
    even = math.fsum(transformed(i * step) for i in range(2, intervals, 2))
    integral = step * (
        transformed(0.0) + transformed(math.pi) + 4.0 * odd + 2.0 * even
    ) / 3.0
    return 16.0 / 3.0 + 8.0 * integral - math.pi ** 2


class AntitheticVarianceReferenceTests(unittest.TestCase):
    def test_midpoint_pair_variance_matches_independent_simpson_reference(self):
        reference = independent_variance_reference()
        midpoint = antithetic_unit_variance_midpoint()

        # The 16,384-point midpoint approximation has ~6.6e-7 absolute
        # error against this independently transformed Simpson integral.
        self.assertAlmostEqual(midpoint, reference, delta=1e-6)
        self.assertGreater(midpoint, 0.0)

    def test_simpson_reference_rejects_invalid_resolution(self):
        for intervals in (0, -2, 3):
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                independent_variance_reference(intervals)


if __name__ == "__main__":
    unittest.main()
