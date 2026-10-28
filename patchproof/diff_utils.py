"""Strict unified-diff validation and application for one allowlisted file."""

import re
from pathlib import PurePosixPath


class PatchError(ValueError):
    """Raised when a proposed diff is malformed or outside the allowlist."""


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)$")


def _clean_diff(diff: str) -> list[str]:
    if not isinstance(diff, str) or not diff.strip():
        raise PatchError("The model returned an empty patch.")
    if len(diff) > 40_000:
        raise PatchError("Patch exceeds the 40,000 character limit.")
    text = diff.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 4 or not lines[0].startswith("```") or lines[-1] != "```":
            raise PatchError("Patch code fence is malformed.")
        text = "\n".join(lines[1:-1])
    lines = text.splitlines(keepends=True)
    if len(lines) < 3:
        raise PatchError("Patch must contain file headers and at least one hunk.")
    return lines


def _path_from_header(line: str, prefix: str, side: str) -> str:
    header = line.rstrip("\r\n")
    if not header.startswith(prefix):
        raise PatchError("Patch must contain standard unified-diff file headers.")
    raw_header_path = header[len(prefix):]
    if not raw_header_path.startswith(f"{side}/"):
        raise PatchError(f"Unified-diff path must use the {side}/ prefix.")
    raw_path = raw_header_path[2:]
    if "\t" in raw_path or " " in raw_path:
        raise PatchError("File header must contain only a relative path.")
    path = PurePosixPath(raw_path)
    if path.is_absolute() or ".." in path.parts or "\\" in raw_path or not raw_path:
        raise PatchError("Absolute paths and path traversal are not allowed.")
    return path.as_posix()


def apply_unified_diff(diff: str, source_files: dict[str, str], allowed_paths: tuple[str, ...]) -> dict[str, str]:
    """Apply a strict unified diff and return changed path-to-text values.

    Only one existing, allowlisted file can be changed. Every context and
    deletion line must match the source exactly; no fuzz or shell patch tool is
    used.
    """
    lines = _clean_diff(diff)
    old_path = _path_from_header(lines[0], "--- ", "a")
    new_path = _path_from_header(lines[1], "+++ ", "b")
    if old_path != new_path:
        raise PatchError("Renaming files is not allowed.")
    if old_path not in allowed_paths:
        raise PatchError(f"File is not allowlisted: {old_path}")
    if old_path not in source_files:
        raise PatchError(f"Patch target does not exist in the fixture: {old_path}")

    original = source_files[old_path].splitlines(keepends=True)
    output: list[str] = []
    source_cursor = 0
    index = 2
    hunk_count = 0

    while index < len(lines):
        hunk_header = lines[index].rstrip("\r\n")
        match = _HUNK.match(hunk_header)
        if not match:
            raise PatchError("Unexpected content outside a unified-diff hunk.")
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        hunk_start = old_start if old_count == 0 else old_start - 1
        expected_new_start = new_start if new_count == 0 else new_start - 1
        if hunk_start < source_cursor or hunk_start > len(original):
            raise PatchError("Patch hunks overlap or refer outside the source file.")
        output.extend(original[source_cursor:hunk_start])
        if expected_new_start != len(output):
            raise PatchError("Unified-diff new-line range does not match the patch output.")
        source_cursor = hunk_start
        index += 1
        old_seen = new_seen = 0

        while index < len(lines) and not lines[index].startswith("@@ "):
            line = lines[index]
            if line.startswith("\\ No newline at end of file"):
                raise PatchError("No-newline diff markers are not supported.")
            if not line or line[0] not in " +-":
                raise PatchError("Malformed unified-diff hunk line.")
            marker, body = line[0], line[1:]
            if marker in " -":
                if source_cursor >= len(original):
                    raise PatchError("Patch removes or matches lines beyond end of source.")
                if original[source_cursor].rstrip("\r\n") != body.rstrip("\r\n"):
                    raise PatchError("Patch context does not match the fixture source exactly.")
                if marker == " ":
                    output.append(original[source_cursor])
                    new_seen += 1
                source_cursor += 1
                old_seen += 1
            else:
                output.append(body)
                new_seen += 1
            index += 1

        if old_seen != old_count or new_seen != new_count:
            raise PatchError("Unified-diff hunk line counts do not match its header.")
        hunk_count += 1

    if hunk_count == 0:
        raise PatchError("Patch contains no hunks.")
    output.extend(original[source_cursor:])
    updated = "".join(output)
    if updated == source_files[old_path]:
        raise PatchError("Patch does not change the source file.")
    return {old_path: updated}


def make_unified_diff(path: str, before: str, after: str) -> str:
    import difflib

    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
