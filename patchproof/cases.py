"""Load and validate the repository's bundled trusted fixtures."""

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_ROOT = PROJECT_ROOT / "fixtures"
MANIFEST_PATH = FIXTURES_ROOT / "manifest.json"


@dataclass(frozen=True)
class BugCase:
    id: str
    title: str
    description: str
    root: Path
    allowed_source_files: tuple[str, ...]
    protected_test_files: tuple[str, ...]
    test_directory: str


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or ".." in path.parts or "\\" in value:
        raise ValueError(f"Unsafe path in fixture manifest: {value!r}")
    return path.as_posix()


def list_cases() -> list[BugCase]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    result = []
    seen_ids: set[str] = set()
    for entry in manifest.get("cases", []):
        case_id = entry["id"]
        if case_id in seen_ids:
            raise ValueError(f"Duplicate fixture ID: {case_id}")
        seen_ids.add(case_id)
        relative_root = _safe_relative_path(entry["root"])
        root = (FIXTURES_ROOT / relative_root).resolve()
        if not root.is_relative_to(FIXTURES_ROOT.resolve()) or not root.is_dir():
            raise ValueError(f"Fixture root is missing or outside fixtures/: {relative_root}")
        sources = tuple(_safe_relative_path(item) for item in entry["allowed_source_files"])
        protected = tuple(_safe_relative_path(item) for item in entry["protected_test_files"])
        if not sources or not protected or set(sources) & set(protected):
            raise ValueError(f"Fixture {case_id} must have separate source and protected test files.")
        for relative in (*sources, *protected):
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                raise ValueError(f"Fixture file is missing or outside its root: {case_id}/{relative}")
        result.append(
            BugCase(
                id=case_id,
                title=entry["title"],
                description=entry["description"],
                root=root,
                allowed_source_files=sources,
                protected_test_files=protected,
                test_directory=_safe_relative_path(entry["test_directory"]),
            )
        )
    if not result:
        raise ValueError("No trusted cases are configured in fixtures/manifest.json.")
    return result


def get_case(case_id: str) -> BugCase:
    for case in list_cases():
        if case.id == case_id:
            return case
    raise KeyError(f"Unknown fixture ID: {case_id}")
