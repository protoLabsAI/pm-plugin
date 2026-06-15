"""Host-free test bootstrap. Register the plugin under a synthetic `pm` package so the
modules' relative imports (`from . import brain`) resolve with no protoAgent host — the
sibling modules keep host-only imports (graph.*) lazy, so importing needs only the dev deps.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = "pm"

if PKG not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        PKG, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    assert _spec and _spec.loader
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules[PKG] = _mod
    _spec.loader.exec_module(_mod)


class FakeRegistry:
    """Mirrors the registry surface register() touches."""

    def __init__(self):
        self.config = {}
        self.tools = []
        self.routers = []
        self.subagents = []
        self.skill_dirs = []

    def register_tool(self, t):
        self.tools.append(t)

    def register_router(self, router, prefix):
        self.routers.append((prefix, router))

    def register_subagent(self, cfg):
        self.subagents.append(cfg)

    def register_skill_dir(self, path):
        self.skill_dirs.append(path)


@pytest.fixture
def registry():
    return FakeRegistry()


@pytest.fixture(autouse=True)
def _isolated_brain(monkeypatch, tmp_path):
    """Every test gets a fresh, isolated PM Brain directory."""
    monkeypatch.setenv("PM_BRAIN_DIR", str(tmp_path / "brain"))
    monkeypatch.delenv("PROTOAGENT_INSTANCE", raising=False)
    monkeypatch.delenv("PM_STALE_STAKEHOLDER_DAYS", raising=False)
