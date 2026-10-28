from dataclasses import asdict

from patchproof.agent import repair_case
from patchproof.contracts import AttemptLog, RepairResult


def test_result_contract_has_stable_fields_and_defaults():
    result = RepairResult(case_id="demo", baseline_output="actual baseline")
    assert result.verdict == "unable_to_verify"
    assert result.attempts == []
    assert asdict(result)["tests_integrity_verified"] is False


def test_attempt_log_records_actual_attempt_fields():
    attempt = AttemptLog(1, "actual diff", "actual pytest output", False, 0.4, "")
    assert asdict(attempt) == {
        "attempt_number": 1,
        "patch_diff": "actual diff",
        "test_output": "actual pytest output",
        "passed": False,
        "elapsed_sec": 0.4,
        "error": "",
    }


def test_missing_credentials_reports_baseline_without_claiming_repair(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    result = repair_case("empty-average", max_attempts=3)
    assert result.verdict == "unable_to_verify"
    assert "ZeroDivisionError" in result.baseline_output
    assert "No inference request was made" in result.final_test_output
    assert result.attempts == []
