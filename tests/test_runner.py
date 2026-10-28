from pathlib import Path

import pytest
import subprocess

from patchproof.diff_utils import make_unified_diff
from patchproof.runner import run_fixture_tests


@pytest.mark.parametrize("case_id", ["empty-average", "punctuation-palindrome", "lower-bound-clamp"])
def test_bundled_baselines_fail_and_leave_protected_tests_intact(case_id):
    result = run_fixture_tests(case_id)
    assert result.exit_code != 0
    assert not result.timed_out
    assert result.tests_integrity_verified
    intended_failure = {
        "empty-average": "ZeroDivisionError",
        "punctuation-palindrome": "test_ignores_case_and_punctuation",
        "lower-bound-clamp": "test_values_below_lower_bound",
    }[case_id]
    assert intended_failure in result.output


def test_valid_patch_runs_in_temporary_copy_and_passes():
    source_path = Path("fixtures/empty_average/bug.py")
    original = source_path.read_text(encoding="utf-8")
    corrected = 'def average(values):\n    """Return the arithmetic mean of values."""\n    if not values:\n        return 0.0\n    return sum(values) / len(values)\n'
    patch = make_unified_diff("bug.py", original, corrected)
    result = run_fixture_tests("empty-average", patch)
    assert result.passed
    assert "2 passed" in result.stdout
    assert source_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize(
    ("case_id", "corrected"),
    [
        (
            "empty-average",
            'def average(values):\n    """Return the arithmetic mean of values."""\n'
            '    if not values:\n        return 0.0\n    return sum(values) / len(values)\n',
        ),
        (
            "punctuation-palindrome",
            'def is_palindrome(text):\n    """Return whether text reads the same forward and backward."""\n'
            '    normalized = "".join(char.casefold() for char in text if char.isalnum())\n'
            '    return normalized == normalized[::-1]\n',
        ),
        (
            "lower-bound-clamp",
            'def clamp(value, lower, upper):\n    """Constrain value to the inclusive interval [lower, upper]."""\n'
            '    return max(lower, min(value, upper))\n',
        ),
    ],
)
def test_reference_repairs_pass_real_fixture_tests(case_id, corrected):
    source_path = Path("fixtures") / {
        "empty-average": "empty_average",
        "punctuation-palindrome": "punctuation_palindrome",
        "lower-bound-clamp": "lower_bound_clamp",
    }[case_id] / "bug.py"
    original = source_path.read_text(encoding="utf-8")
    patch = make_unified_diff("bug.py", original, corrected)
    result = run_fixture_tests(case_id, patch)
    assert result.passed
    assert "passed" in result.stdout


def test_model_cannot_patch_protected_test_file():
    source_path = Path("fixtures/empty_average/bug.py")
    test_path = Path("fixtures/empty_average/tests/test_bug.py")
    source_before = source_path.read_bytes()
    tests_before = test_path.read_bytes()
    patch = "--- a/tests/test_bug.py\n+++ b/tests/test_bug.py\n@@ -1 +1 @@\n-import pytest\n+assert True\n"
    with pytest.raises(ValueError, match="not allowlisted"):
        run_fixture_tests("empty-average", patch)
    assert source_path.read_bytes() == source_before
    assert test_path.read_bytes() == tests_before


def test_runner_reports_invalid_timeout():
    with pytest.raises(ValueError, match="timeout"):
        run_fixture_tests("empty-average", timeout_seconds=0)


def test_subprocess_timeout_is_reported_as_not_passed(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("pytest", 1, output="partial output", stderr="")

    monkeypatch.setattr("patchproof.runner.subprocess.run", timeout)
    result = run_fixture_tests("empty-average", timeout_seconds=1)

    assert result.timed_out
    assert result.exit_code is None
    assert not result.passed
    assert "TIMED OUT" in result.output
    assert "partial output" in result.output
