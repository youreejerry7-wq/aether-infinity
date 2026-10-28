import json
import math
import random
import pytest
from research import bernoulli, pi_test, run_research_cycle, DEFAULT_Z_THRESHOLD


def test_bernoulli_basic():
    rng = random.Random(42)
    res = bernoulli(10000, 0.5, rng=rng)
    assert res["category"] == "known_baseline"
    assert res["trials"] == 10000
    assert res["expected"] == 0.5
    assert 0.45 <= res["observed"] <= 0.55
    assert isinstance(res["z_score"], float)
    assert isinstance(res["flag"], bool)


def test_bernoulli_validation():
    with pytest.raises(ValueError, match="trials must be positive"):
        bernoulli(0, 0.5)
    with pytest.raises(ValueError, match="Probability p must be between 0 and 1"):
        bernoulli(100, 1.5)


def test_bernoulli_flagging():
    # Force extreme observed value
    class DeterministicLowRNG:
        def random(self):
            return 0.0  # Always < p, so observed = 1.0

    res = bernoulli(1000, 0.5, rng=DeterministicLowRNG(), z_threshold=3.29)
    assert res["observed"] == 1.0
    # z = (1.0 - 0.5) / sqrt(0.25/1000) = 0.5 / 0.015811 = 31.62
    assert res["z_score"] > 3.29
    assert res["flag"] is True


def test_pi_test_basic():
    rng = random.Random(42)
    res = pi_test(10000, rng=rng)
    assert res["category"] == "known_baseline"
    assert res["trials"] == 10000
    assert res["expected"] == round(math.pi, 6)
    assert 3.0 <= res["observed"] <= 3.3
    assert isinstance(res["z_score"], float)
    assert isinstance(res["flag"], bool)


def test_pi_test_validation():
    with pytest.raises(ValueError, match="trials must be positive"):
        pi_test(-10)


def test_repeatability_with_seed():
    res1 = run_research_cycle(seed=12345, out_path="/tmp/test_research_1.json")
    res2 = run_research_cycle(seed=12345, out_path="/tmp/test_research_2.json")

    assert res1["experiments"] == res2["experiments"]
    assert res1["status"] == "completed"
    assert res1["errors"] == []


def test_run_research_cycle_file_persistence(tmp_path):
    out_file = tmp_path / "research.json"
    res = run_research_cycle(seed=999, out_path=out_file)

    assert out_file.exists()
    data = json.loads(out_file.read_text())
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["time"] == res["time"]
    assert len(data[0]["experiments"]) == 4

    # Run a second cycle and verify prepending and cap
    run_research_cycle(seed=1000, out_path=out_file)
    data_updated = json.loads(out_file.read_text())
    assert len(data_updated) == 2
