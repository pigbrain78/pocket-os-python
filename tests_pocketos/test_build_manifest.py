"""Build-manifest integrity test.

Recomputes the SHA-256 of every tracked source file listed in
BUILD_MANIFEST.json and fails if any file has drifted from the manifest.

Verification is against the GIT TREE AT HEAD (via `git show HEAD:<path>`), not
the working tree, so an uncommitted edit or a partial restore is detected
exactly as a committed change would be. The manifest is pinned to the commit
that introduced it; the test confirms that commit is an ancestor of HEAD so a
later commit does not false-alarm while still proving the pinned tree is intact.
"""

import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(*args):
    return subprocess.check_output(["git", "-C", ROOT, *args]).decode()


def _manifest():
    with open(os.path.join(ROOT, "BUILD_MANIFEST.json")) as fh:
        return json.load(fh)


def test_manifest_commit_is_ancestor_of_head():
    """The manifest-pinned commit must be reachable from HEAD (it introduced the
    pinned tree); later commits are fine — the tree is what is pinned."""
    m = _manifest()
    pinned = m["commit"]
    try:
        # Returns empty if pinned is an ancestor of HEAD, non-zero otherwise.
        _git("merge-base", "--is-ancestor", pinned, "HEAD")
    except subprocess.CalledProcessError:
        raise AssertionError(
            f"manifest pinned to {pinned} which is NOT an ancestor of HEAD; "
            "the pinned tree is unreachable"
        )


def test_all_manifest_files_match_git_tree_at_head():
    """Every manifest file must exist in the git tree at HEAD with the pinned
    hash. An uncommitted working-tree edit does not change HEAD, so this proves
    the committed tree is intact; the working tree is checked separately."""
    m = _manifest()
    assert m["files"], "manifest has no files"
    for rel, expected in m["files"].items():
        try:
            blob = subprocess.check_output(
                ["git", "-C", ROOT, "show", f"HEAD:{rel}"], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            raise AssertionError(f"manifest file absent from git tree at HEAD: {rel}")
        actual = _sha_bytes(blob)
        assert actual == expected, (
            f"SHA-256 drift on {rel} at HEAD:\n  manifest {expected}\n  actual   {actual}"
        )


def test_working_tree_matches_manifest_for_listed_files():
    """The on-disk working tree must match the manifest (catches partial
    restores / uncommitted edits to pinned files)."""
    m = _manifest()
    for rel, expected in m["files"].items():
        path = os.path.join(ROOT, rel)
        assert os.path.exists(path), f"manifest file missing on disk: {rel}"
        with open(path, "rb") as fh:
            actual = _sha_bytes(fh.read())
        assert actual == expected, (
            f"SHA-256 drift on disk for {rel}:\n  manifest {expected}\n  actual   {actual}"
        )
