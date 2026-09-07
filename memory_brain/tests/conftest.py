"""Conftest -- shared fixtures for the memory_brain test suite."""

import sys
import os
import sqlite3

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_WS = os.path.dirname(_ROOT)

# Ensure the package is importable when tests run from the package root.
sys.path.insert(0, _ROOT)
# Make the Pocket OS council contract importable (convergence for the gate).
sys.path.insert(0, os.path.join(_WS, "scripts"))

# Demo signing on BEFORE any import so the council gate's env-read is correct.
os.environ["POCKETOS_COUNCIL_DEMO_SIGNING"] = "1"

import pytest
from memory_brain.core import MemoryBrain
from memory_brain.models import Confidence


@pytest.fixture
def brain():
    """A fresh in-memory MemoryBrain per test (deterministic isolation)."""
    b = MemoryBrain(":memory:")
    yield b
    b.conn.close()


@pytest.fixture
def api_brain():
    """Fresh in-memory MemoryBrain with an active source registered."""
    from memory_brain.api import MemoryAPI
    b = MemoryBrain(":memory:")
    src = b.register_source("document", "spec.md", "slick", "2026-09-07T00:00:00Z")
    api = MemoryAPI(brain=b)
    return api, b, src


def make_conf(source=0.9, extraction=0.8, inference=0.0):
    return Confidence(source=source, extraction=extraction, inference=inference)
