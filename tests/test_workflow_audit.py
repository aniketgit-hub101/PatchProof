from pathlib import Path

import pytest
from openai import APIConnectionError
from types import SimpleNamespace
import httpx

import patchproof.agent as agent
from patchproof.diff_utils import make_unified_diff
from patchproof.nebius_client import InferenceResponse, NebiusClient, NebiusRequestError


class ValidationFailureClient:
    def __init__(self, response="not a unified diff"):
        self.calls = 0
        self.response = response

    def generate_patch(self, **_kwargs):
        self.calls += 1
        return InferenceResponse("test-only-stub", self.response, 0.01)


class ApiFailureClient:
    def __init__(self):
        self.calls = 0

    def generate_patch(self, **_kwargs):
        self.calls += 1
        raise NebiusRequestError("Nebius authentication failed. Check the configured API key.")


def test_invalid_model_diffs_stop_at_configured_attempt_limit(monkeypatch):
    client = ValidationFailureClient()
    monkeypatch.setattr(agent.NebiusClient, "from_environment", lambda: client)

    result = agent.repair_case("empty-average", max_attempts=2)

    assert client.calls == 2
    assert [attempt.attempt_number for attempt in result.attempts] == [1, 2]
    assert result.verdict == "failed"
    assert all(not attempt.passed for attempt in result.attempts)
    assert "Patch rejected before tests ran" in result.final_test_output


@pytest.mark.parametrize("attempts", [0, 4, -1])
def test_attempt_limit_rejects_out_of_range_values(attempts):
    with pytest.raises(ValueError, match="between 1 and 3"):
        agent.repair_case("empty-average", max_attempts=attempts)


def test_api_failure_is_recorded_once_and_never_verified(monkeypatch):
    client = ApiFailureClient()
    monkeypatch.setattr(agent.NebiusClient, "from_environment", lambda: client)

    result = agent.repair_case("empty-average", max_attempts=3)

    assert client.calls == 1
    assert len(result.attempts) == 1
    assert result.verdict == "unable_to_verify"
    assert "authentication failed" in result.attempts[0].error.lower()
    assert not result.attempts[0].passed


def test_sdk_connection_failure_is_translated_without_leaking_credentials():
    secret = "test-only-secret-value"
    client = NebiusClient(api_key=secret)

    def fail(*_args, **_kwargs):
        raise APIConnectionError(request=httpx.Request("POST", "https://example.invalid"))

    client.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fail))
    )
    with pytest.raises(NebiusRequestError, match="Could not connect") as exc_info:
        client.generate_patch(issue="issue", source="source", test_output="actual output")
    assert secret not in str(exc_info.value)


def test_verified_requires_actual_passing_tests_and_integrity(monkeypatch):
    source_path = Path("fixtures/empty_average/bug.py")
    original = source_path.read_text(encoding="utf-8")
    corrected = 'def average(values):\n    """Return the arithmetic mean of values."""\n    if not values:\n        return 0.0\n    return sum(values) / len(values)\n'
    patch = make_unified_diff("bug.py", original, corrected)

    class PassingClient:
        def generate_patch(self, **_kwargs):
            return InferenceResponse("test-only-stub", patch, 0.01)

    monkeypatch.setattr(agent.NebiusClient, "from_environment", lambda: PassingClient())
    result = agent.repair_case("empty-average", max_attempts=1)

    assert result.verdict == "verified"
    assert len(result.attempts) == 1
    assert result.attempts[0].passed
    assert result.tests_integrity_verified
    assert "2 passed" in result.final_test_output
    assert source_path.read_text(encoding="utf-8") == original
