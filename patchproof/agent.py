"""Bounded baseline, inference, validation, and test-feedback repair loop."""

import time

from patchproof.cases import get_case
from patchproof.contracts import AttemptLog, RepairResult
from patchproof.diff_utils import PatchError, apply_unified_diff, make_unified_diff
from patchproof.nebius_client import MissingCredentialsError, NebiusClient, NebiusRequestError
from patchproof.runner import TestRun, run_fixture_tests


def _format_run(run: TestRun) -> str:
    return run.output


def _read_sources(case_id: str) -> tuple[str, str]:
    case = get_case(case_id)
    relative = case.allowed_source_files[0]
    source = (case.root / relative).read_text(encoding="utf-8")
    return relative, source


def repair_case(case_id: str, max_attempts: int = 3) -> RepairResult:
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3.")
    started = time.perf_counter()
    case = get_case(case_id)
    baseline = run_fixture_tests(case_id)
    result = RepairResult(
        case_id=case_id,
        baseline_output=_format_run(baseline),
        final_test_output=_format_run(baseline),
        verdict="unable_to_verify",
        tests_integrity_verified=baseline.tests_integrity_verified,
    )
    if baseline.infrastructure_error or baseline.timed_out:
        result.final_test_output = _format_run(baseline)
        result.elapsed_sec = time.perf_counter() - started
        return result
    if baseline.passed:
        result.final_test_output = "Baseline tests already pass; this fixture does not demonstrate a reproducible bug.\n" + _format_run(baseline)
        result.verdict = "failed"
        result.elapsed_sec = time.perf_counter() - started
        return result
    if not baseline.tests_integrity_verified:
        result.final_test_output = "Protected tests changed during baseline execution. Repair stopped.\n" + _format_run(baseline)
        result.verdict = "unable_to_verify"
        result.elapsed_sec = time.perf_counter() - started
        return result
    try:
        client = NebiusClient.from_environment()
    except MissingCredentialsError as exc:
        result.final_test_output = f"{exc} Set it locally, then rerun. No inference request was made.\n\n" + _format_run(baseline)
        result.verdict = "unable_to_verify"
        result.elapsed_sec = time.perf_counter() - started
        return result
    except ValueError as exc:
        result.final_test_output = f"Invalid Nebius configuration: {exc}\n\n" + _format_run(baseline)
        result.verdict = "unable_to_verify"
        result.elapsed_sec = time.perf_counter() - started
        return result

    relative_source, original_source = _read_sources(case_id)
    current_source = original_source
    feedback = baseline.output
    for attempt_number in range(1, max_attempts + 1):
        attempt_started = time.perf_counter()
        try:
            inference = client.generate_patch(issue=case.description, source=current_source, test_output=feedback)
        except NebiusRequestError as exc:
            result.attempts.append(
                AttemptLog(attempt_number, "", "", False, time.perf_counter() - attempt_started, str(exc))
            )
            result.final_test_output = f"{exc}\n\nLatest actual test output:\n{feedback}"
            result.verdict = "unable_to_verify"
            break

        proposed_diff = inference.text
        try:
            updated = apply_unified_diff(
                proposed_diff,
                {relative_source: current_source},
                case.allowed_source_files,
            )[relative_source]
        except PatchError as exc:
            elapsed = time.perf_counter() - attempt_started
            result.attempts.append(AttemptLog(attempt_number, proposed_diff, "", False, elapsed, str(exc)))
            result.final_diff = proposed_diff
            result.final_test_output = f"Patch rejected before tests ran: {exc}"
            feedback = f"Patch validation failed: {exc}. Return a corrected unified diff for bug.py only."
            if attempt_number == max_attempts:
                result.verdict = "failed"
            continue

        # Each attempt is tested from a fresh copy of the original fixture, so
        # provide the cumulative diff from that original to the candidate.
        actual_diff = make_unified_diff(relative_source, original_source, updated)
        run = run_fixture_tests(case_id, actual_diff)
        elapsed = time.perf_counter() - attempt_started
        attempt_error = ""
        if run.infrastructure_error:
            attempt_error = run.infrastructure_error
        elif run.timed_out:
            attempt_error = "Test command timed out."
        elif not run.tests_integrity_verified:
            attempt_error = "Protected test files changed during test execution."
        attempt_output = f"Inference model: {inference.model} · inference: {inference.elapsed_sec:.2f}s\n\n{_format_run(run)}"
        result.attempts.append(AttemptLog(attempt_number, actual_diff, attempt_output, run.passed, elapsed, attempt_error))
        result.final_diff = actual_diff
        result.final_test_output = attempt_output
        result.tests_integrity_verified = result.tests_integrity_verified and run.tests_integrity_verified
        if run.passed:
            result.verdict = "verified"
            break
        if run.infrastructure_error or run.timed_out or not run.tests_integrity_verified:
            result.verdict = "unable_to_verify"
            break
        result.verdict = "failed"
        current_source = updated
        feedback = run.output

    result.elapsed_sec = time.perf_counter() - started
    return result
