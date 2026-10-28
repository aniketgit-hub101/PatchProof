"""Execute fixed tests for trusted bundled fixtures in temporary workspaces."""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from stat import S_ISREG

from patchproof.cases import PROJECT_ROOT, BugCase, get_case
from patchproof.diff_utils import apply_unified_diff


TEST_TIMEOUT_SECONDS = 10
OUTPUT_LIMIT = 12_000
TEMP_ROOT = PROJECT_ROOT / ".patchproof-tmp"


@dataclass
class TestRun:
    exit_code: int | None
    stdout: str
    stderr: str
    elapsed_sec: float
    timed_out: bool = False
    infrastructure_error: str = ""
    tests_integrity_verified: bool = False

    @property
    def passed(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.infrastructure_error and self.tests_integrity_verified

    @property
    def output(self) -> str:
        status = "TIMED OUT" if self.timed_out else f"exit code: {self.exit_code}"
        parts = [f"Test command: {sys.executable} -m pytest -q -p no:cacheprovider {self._test_path}", status, f"Duration: {self.elapsed_sec:.2f}s"]
        if self.infrastructure_error:
            parts.append(f"Runner error: {self.infrastructure_error}")
        parts.append(f"Protected test integrity: {'PASS' if self.tests_integrity_verified else 'FAIL / NOT VERIFIED'}")
        if self.stdout.strip():
            parts.extend(("--- stdout ---", self.stdout))
        if self.stderr.strip():
            parts.extend(("--- stderr ---", self.stderr))
        return "\n".join(parts)[-OUTPUT_LIMIT:]

    _test_path: str = "tests"


def _restricted_environment() -> dict[str, str]:
    """Pass only platform variables needed to start Python, excluding secrets."""
    allowed_names = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL")
    environment = {name: os.environ[name] for name in allowed_names if name in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _hash_files(root: Path, relative_paths: tuple[str, ...]) -> dict[str, str]:
    hashes = {}
    for relative in relative_paths:
        target = root / Path(relative)
        try:
            file_stat = target.lstat()
            if not S_ISREG(file_stat.st_mode):
                hashes[relative] = "INVALID_FILE_TYPE"
                continue
            hashes[relative] = sha256(target.read_bytes()).hexdigest()
        except OSError:
            hashes[relative] = "MISSING_OR_UNREADABLE"
    return hashes


def _copy_trusted_fixture(case: BugCase, workspace: Path) -> None:
    for relative in (*case.allowed_source_files, *case.protected_test_files):
        source = case.root / Path(relative)
        target = workspace / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def run_fixture_tests(case_id: str, patch_diff: str | None = None, timeout_seconds: int = TEST_TIMEOUT_SECONDS) -> TestRun:
    """Run only a manifest-listed fixture's fixed pytest suite in a temp copy."""
    case = get_case(case_id)
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
        raise ValueError("Test timeout must be an integer from 1 to 60 seconds.")

    TEMP_ROOT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="patchproof-", dir=TEMP_ROOT) as temp_dir:
        workspace = Path(temp_dir)
        _copy_trusted_fixture(case, workspace)
        if patch_diff is not None:
            source_files = {
                relative: (workspace / Path(relative)).read_text(encoding="utf-8")
                for relative in case.allowed_source_files
            }
            changes = apply_unified_diff(patch_diff, source_files, case.allowed_source_files)
            for relative, content in changes.items():
                (workspace / Path(relative)).write_text(content, encoding="utf-8")

        before_hashes = _hash_files(workspace, case.protected_test_files)
        started = time.perf_counter()
        test_path = case.test_directory
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_path],
                cwd=workspace,
                env=_restricted_environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
            stdout = completed.stdout[-OUTPUT_LIMIT:]
            stderr = completed.stderr[-OUTPUT_LIMIT:]
            exit_code = completed.returncode
            timed_out = False
            infra_error = ""
            combined = stdout + stderr
            if "No module named pytest" in combined or "No module named 'pytest'" in combined:
                infra_error = "pytest is not installed in the active Python environment."
        except subprocess.TimeoutExpired as exc:
            stdout = _as_text(exc.stdout)[-OUTPUT_LIMIT:]
            stderr = _as_text(exc.stderr)[-OUTPUT_LIMIT:]
            exit_code = None
            timed_out = True
            infra_error = ""
        except OSError as exc:
            stdout = ""
            stderr = ""
            exit_code = None
            timed_out = False
            infra_error = f"Could not start pytest ({type(exc).__name__})."
        elapsed = time.perf_counter() - started
        after_hashes = _hash_files(workspace, case.protected_test_files)
        return TestRun(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            elapsed_sec=elapsed,
            timed_out=timed_out,
            infrastructure_error=infra_error,
            tests_integrity_verified=before_hashes == after_hashes,
            _test_path=test_path,
        )


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
