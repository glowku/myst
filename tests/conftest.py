"""Shared fixtures: scratch project roots with initialized layers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from myst_persistence.commands import init, log  # noqa: E402
from myst_persistence.model import Entry  # noqa: E402
from myst_persistence.paths import MystPaths  # noqa: E402
from myst_persistence.profile import ProjectProfile  # noqa: E402
from myst_persistence.semantic import SemanticStore  # noqa: E402


@pytest.fixture
def project(tmp_path):
    """A scratch project with an initialized .myst/ layer."""
    root = tmp_path / "proj"
    root.mkdir()
    init("test-proj", "pytest scratch", root=root)
    return root


@pytest.fixture
def paths(project):
    return MystPaths(project)


@pytest.fixture
def profile(paths):
    return ProjectProfile.load(paths.profile_file)


@pytest.fixture
def git_project(tmp_path):
    """A scratch git repo with an initialized myst layer.

    Requires git on PATH; skipped when unavailable.
    """
    root = tmp_path / "gitproj"
    root.mkdir()
    try:
        subprocess.run(["git", "init", str(root)], check=True,
                       capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git not available")
    env_cmd = ["git", "-C", str(root)]
    subprocess.run(env_cmd + ["config", "user.email", "t@example.com"],
                   check=True, capture_output=True)
    subprocess.run(env_cmd + ["config", "user.name", "Test"],
                   check=True, capture_output=True)
    init("git-proj", "hook test bed", root=root)
    from myst_persistence import ledger
    entry = Entry.create(kind="event", title="seed", context="hook works")
    ledger.append_entry(root / ".myst" / "ledger.jsonl", entry)
    return {"root": root, "paths": MystPaths(root),
            "git": ["git", "-C", str(root)]}


@pytest.fixture
def seeded(project, paths):
    """Project with a small realistic ledger + semantic store."""
    log("chose sqlite over postgres", kind="decision",
        decision="embedded, zero ops", tags=["db", "storage"],
        paths=MystPaths(project))
    log("dropped mongo", kind="rejection",
        rejection="ops cost too high", tags=["db"],
        paths=MystPaths(project))
    log("sync-first offline layer", kind="decision",
        decision="no network dep", tags=["arch"],
        paths=MystPaths(project))
    log("sqlite again for cache", kind="decision",
        decision="same tooling", tags=["db", "cache"],
        paths=MystPaths(project))
    store = SemanticStore()
    from myst_persistence.model import SemanticItem, SemanticKind
    store.add(SemanticItem(id="inv-flat", kind=SemanticKind.INVARIANT,
                           text="Keep the layer flat and inspectable"))
    store.save(paths.semantic_file, paths.semantic_dir)
    return project


def make_entry(**kwargs) -> Entry:
    return Entry.create(**kwargs)
