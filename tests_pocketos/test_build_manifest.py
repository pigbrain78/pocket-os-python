"""Build-manifest integrity test.

Recomputes the SHA-256 of every tracked source file listed in
BUILD_MANIFEST.json and fails if any hash (or the git commit) has drifted.
This makes the checksum contract enforceable rather than advisory: a workspace
reset, an uncommitted edit, or a partial restore is detected immediately.
"""

import hashlib
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest():
    with open(os.path.join(ROOT, "BUILD_MANIFEST.json")) as fh:
        return json.load(fh)


def test_manifest_commit_matches_head():
    m = _manifest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    assert m["commit"] == head, (
        f"manifest pinned to {m['commit']} but HEAD is {head}; "
        "recompute BUILD_MANIFEST.json after committing"
    )


def test_all_manifest_files_exist_and_hash_match():
    m = _manifest()
    assert m["files"], "manifest has no files"
    for rel, expected in m["files"].items():
        path = os.path.join(ROOT, rel)
        assert os.path.exists(path), f"manifest file missing: {rel}"
        actual = _sha(path)
        assert actual == expected, (
            f"SHA-256 drift on {rel}:\n  manifest {expected}\n  actual   {actual}"
        )
