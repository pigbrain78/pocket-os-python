#!/usr/bin/env python3
"""Submit a validated Chrysalis mutation as a governed PocketOS proposal.

This bridge is deliberately proposal-only. Chrysalis validates the transformed
AST and produces a manifest; PocketOS records an ordinary council-bound
proposal. Human ratification and execution remain separate server-side steps.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import chrysalis_mutation_skeletons as chrysalis


BASE_URL = os.environ.get("POCKETOS_BASE_URL", "http://127.0.0.1:8787").rstrip("/")


def request_json(path: str, *, method: str = "GET", payload: dict[str, Any] | None = None,
                 token: str | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"PocketOS {exc.code} for {path}: {detail}") from exc


def submit(strategy: str, source: Path, username: str, password: str) -> dict[str, Any]:
    diff = chrysalis.apply_diff(strategy, source)
    if not diff:
        raise ValueError(f"strategy {strategy!r} produced no validated change for {source}")
    manifest = chrysalis.mutation_manifest(strategy, source, diff)
    proposal_id = f"D-CHRYSALIS-{manifest['diff_hash'][:16].upper()}"
    title = (
        f"Chrysalis mutation review: {strategy} ({source.name}; "
        f"diff {manifest['diff_hash'][:12]})"
    )
    login = request_json("/api/login", method="POST", payload={"username": username, "password": password})
    token = login["token"]
    proposal = request_json(
        "/api/v1/decisions/propose",
        method="POST",
        token=token,
        payload={
            "title": title,
            "decision_id": proposal_id,
            "risk": "LOW" if manifest["preservation_class"] == "formal" else "MEDIUM",
            "reversible": True,
            "send_to_council": True,
        },
    )
    decision = proposal.get("decision") or {}
    return {
        "proposal_only": True,
        "source": str(source),
        "manifest": manifest,
        "decision": {
            "decision_id": decision.get("decision_id"),
            "status": decision.get("status"),
            "stage": decision.get("stage"),
            "council_approved": decision.get("council_approved"),
            "human_ratified": decision.get("human_ratified"),
            "can_execute": decision.get("can_execute"),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True, choices=chrysalis.list_registered())
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--username", default=os.environ.get("POCKETOS_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("POCKETOS_PASSWORD", "demo"))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(submit(args.strategy, args.file, args.username, args.password), indent=2))
        return 0
    except (OSError, KeyError, RuntimeError, SyntaxError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
