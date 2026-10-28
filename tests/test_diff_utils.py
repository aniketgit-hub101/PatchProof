import pytest

from patchproof.diff_utils import PatchError, apply_unified_diff, make_unified_diff


def test_applies_unified_diff_when_context_matches():
    before = 'def average(values):\n    return sum(values) / len(values)\n'
    after = 'def average(values):\n    if not values:\n        return 0.0\n    return sum(values) / len(values)\n'
    patch = make_unified_diff("bug.py", before, after)
    assert apply_unified_diff(patch, {"bug.py": before}, ("bug.py",)) == {"bug.py": after}


@pytest.mark.parametrize(
    "patch",
    [
        "--- a/../secrets.txt\n+++ b/../secrets.txt\n@@ -1 +1 @@\n-old\n+new\n",
        "--- a/tests/test_bug.py\n+++ b/tests/test_bug.py\n@@ -1 +1 @@\n-old\n+new\n",
        "--- a/bug.py\n+++ b/bug.py\n@@ -1 +1 @@\n-not the source\n+new\n",
        "--- a/bug.py\n+++ b/bug.py\n@@ -1 +9 @@\n-old\n+new\n",
        "not a unified diff",
    ],
)
def test_rejects_unsafe_or_malformed_diff(patch):
    with pytest.raises(PatchError):
        apply_unified_diff(patch, {"bug.py": "original\n"}, ("bug.py",))


def test_rejects_a_second_file_or_rename():
    patch = "--- a/bug.py\n+++ b/other.py\n@@ -1 +1 @@\n-old\n+new\n"
    with pytest.raises(PatchError, match="Renaming"):
        apply_unified_diff(patch, {"bug.py": "old\n"}, ("bug.py",))
