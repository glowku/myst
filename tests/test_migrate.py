"""v1 migration: invariants.yaml, trajectory nodes, idempotence."""

import json

import pytest

from myst_persistence import ledger
from myst_persistence.migrate import migrate
from myst_persistence.model import SemanticKind
from myst_persistence.paths import MystPaths
from myst_persistence.profile import ProjectProfile
from myst_persistence.semantic import SemanticStore


V1_INVARIANTS = """# v1 file
invariants:
  - Prefer composition over inheritance
  - Never lose the reason a path was rejected
style:
  decision_style: Explore multiple paths, document rejections clearly
  priority: Continuity of reasoning > starting from zero
anti_patterns:
  - Summarizing decisions without keeping rejected alternatives
  - Building large meta-systems before validating on real work
"""

V1_NODE = """# Rejected pure RAG

## Context
Losing the reasoning behind architecture choices

## Decision
Explicit trajectory nodes + stable invariants

## Rejected
pure RAG loses the why behind choices
"""


@pytest.fixture
def v1_layer(tmp_path):
    root = tmp_path / "v1proj"
    root.mkdir()
    layer = root / ".myst"
    layer.mkdir()
    (layer / "invariants.yaml").write_text(V1_INVARIANTS, encoding="utf-8")
    traj = layer / "trajectory"
    traj.mkdir()
    (traj / "0001-rag.md").write_text(V1_NODE, encoding="utf-8")
    (layer / "current_state.md").write_text("old state", encoding="utf-8")
    return root


def test_migration_copies_semantic(v1_layer):
    paths = MystPaths(v1_layer)
    report = migrate(paths, ProjectProfile())
    assert report["semantic_added"] == 6  # 2 inv + 2 style + 2 antipatterns

    store = SemanticStore.load(paths.semantic_file)
    kinds = {i.kind for i in store.all()}
    assert SemanticKind.INVARIANT in kinds
    assert SemanticKind.PRINCIPLE in kinds
    assert SemanticKind.ANTIPATTERN in kinds
    texts = " | ".join(i.text for i in store.all())
    assert "Prefer composition over inheritance" in texts
    assert "Never lose the reason" in texts


def test_migration_parses_trajectory(v1_layer):
    paths = MystPaths(v1_layer)
    migrate(paths, ProjectProfile())
    entries = ledger.load_entries(paths.ledger_file)
    # trajectory node + migration event
    assert len(entries) == 2
    node = entries[0]
    assert node.title == "Rejected pure RAG"
    assert "Explicit trajectory nodes" in node.decision
    assert "pure RAG loses the why" in node.rejection
    assert node.tags == ["v1-import"]


def test_migration_event_entry(v1_layer):
    paths = MystPaths(v1_layer)
    migrate(paths, ProjectProfile())
    entries = ledger.load_entries(paths.ledger_file)
    event = entries[-1]
    assert event.kind == "event"
    assert event.meta.get("had_state_file") is True


def test_migration_idempotent(v1_layer):
    paths = MystPaths(v1_layer)
    first = migrate(paths, ProjectProfile())
    again = migrate(paths, ProjectProfile())
    assert again.get("already_migrated")
    assert ledger.verify_chain(paths.ledger_file)["ok"]
    # ledger not doubled
    assert len(ledger.load_entries(paths.ledger_file)) == 2


def test_v1_files_untouched(v1_layer):
    before = (v1_layer / ".myst" / "invariants.yaml").read_text(encoding="utf-8")
    paths = MystPaths(v1_layer)
    migrate(paths, ProjectProfile())
    after = (v1_layer / ".myst" / "invariants.yaml").read_text(encoding="utf-8")
    assert before == after
    assert (v1_layer / ".myst" / "trajectory" / "0001-rag.md").exists()


def test_chain_valid_after_migration(v1_layer):
    paths = MystPaths(v1_layer)
    migrate(paths, ProjectProfile())
    report = ledger.verify_chain(paths.ledger_file)
    assert report["ok"], report["errors"]


def test_missing_v1_raises(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / ".myst").mkdir()
    from myst_persistence.migrate import MigrationError
    with pytest.raises(MigrationError):
        migrate(MystPaths(root), ProjectProfile())
