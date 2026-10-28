"""Shared result contracts for the repair workflow and Streamlit UI."""

from dataclasses import dataclass, field


@dataclass
class AttemptLog:
    attempt_number: int
    patch_diff: str
    test_output: str
    passed: bool
    elapsed_sec: float = 0.0
    error: str = ""


@dataclass
class RepairResult:
    case_id: str
    baseline_output: str
    attempts: list[AttemptLog] = field(default_factory=list)
    final_diff: str = ""
    final_test_output: str = ""
    verdict: str = "unable_to_verify"
    elapsed_sec: float = 0.0
    tests_integrity_verified: bool = False
