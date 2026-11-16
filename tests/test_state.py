"""State generation: budget enforcement, formats, selection order."""

import json

import pytest

from myst_persistence.model import SemanticItem, SemanticKind
from myst_persistence.profile import ProjectProfile
from myst_persistence.semantic import SemanticStore
from myst_persistence.state import build_state, generate_and_save
from myst_persistence.tokens import estimate_tokens


@pytest.fixture
def entries():
    from myst_persistence.model import Entry
    out = []
    for i, (title, kind, tags, decision) in enumerate([
        ("chose sqlite", "decision", ["db"], "embedded zero ops"),
        ("dropped mongo", "rejection", ["db"], "ops cost"),
        ("sync-first arch", "decision", ["arch"], "offline"),
        ("indexes matter", "insight", ["db"], "add early"),
        ("cache in sqlite", "decision", ["db", "cache"], "same tooling"),
    ], 1):
        out.append(Entry.create(kind=kind, title=title, tags=tags,
                                decision=decision))
    return out


@pytest.fixture
def store():
    s = SemanticStore()
    s.add(SemanticItem(id="inv-1", kind=SemanticKind.INVARIANT,
                       text="Prefer composition over inheritance"))
    s.add(SemanticItem(id="ap-1", kind=SemanticKind.ANTIPATTERN,
                       text="No meta-systems before real work", pinned=False))
    return s


PROFILE = ProjectProfile(name="t")


def test_budget_respected(entries, store):
    for budget in (200, 600, 1500, 3000):
        bundle = build_state(entries, store, PROFILE, budget=budget)
        assert bundle["tokens"] <= budget, (budget, bundle["tokens"])
        assert bundle["text"]


def test_focus_changes_selection(entries, store):
    no_focus = build_state(entries, store, PROFILE, budget=1500)
    db_focus = build_state(entries, store, PROFILE, budget=1500, focus="db")
    assert [e.id for e in db_focus["entries"]] != []  # non-empty
    # db-focus top entry must mention db topics
    assert "db" in db_focus["entries"][0].tags


def test_formats_all_valid(entries, store):
    md = build_state(entries, store, PROFILE, budget=800, fmt="markdown")
    comp = build_state(entries, store, PROFILE, budget=400, fmt="compact")
    js = build_state(entries, store, PROFILE, budget=800, fmt="json")

    assert md["text"].startswith("# Cognitive state")
    assert "RULE" in comp["text"] or "DECISION" in comp["text"]
    data = json.loads(js["text"])  # valid JSON
    assert data["project"] == "t"
    assert isinstance(data["entries"], list)


def test_pinned_semantic_always_included(entries, store):
    bundle = build_state(entries, store, PROFILE, budget=2000)
    ids = [i.id for i in bundle["semantic_items"]]
    assert "inv-1" in ids
    assert "ap-1" in ids  # not pinned but still included (weight order)


def test_semantic_before_trajectory(entries, store):
    text = build_state(entries, store, PROFILE, budget=1500)["text"]
    inv_pos = text.find("Prefer composition")
    traj_pos = text.find("Recent trajectory")
    assert 0 <= inv_pos < traj_pos


def test_stats_computed(entries, store):
    bundle = build_state(entries, store, PROFILE, budget=1500)
    assert bundle["stats"]["total"] == 5
    assert bundle["stats"]["rejections"] == 1


def test_tight_budget_still_renders(entries, store):
    bundle = build_state(entries, store, PROFILE, budget=200)
    assert bundle["text"]
    assert bundle["tokens"] <= 200


def test_generate_and_save_writes_file(entries, store, tmp_path):
    from myst_persistence.paths import MystPaths
    root = tmp_path / "p"
    root.mkdir()
    paths = MystPaths(root)
    paths.ensure_dirs()
    bundle = generate_and_save(paths, PROFILE, entries, store, budget=700)
    assert bundle["path"].endswith("current.md")
    import pathlib
    assert pathlib.Path(bundle["path"]).exists()


def test_include_closed_false_hides_superseded(entries, store):
    entries[0].status = "superseded"
    b = build_state(entries, store, PROFILE, budget=1500,
                    include_closed=False)
    assert all(e.status == "active" for e in b["entries"])
    b2 = build_state(entries, store, PROFILE, budget=1500,
                     include_closed=True)
    assert any(e.status == "superseded" for e in b2["entries"])


def test_token_estimate_positive():
    assert estimate_tokens("") == 0
    assert estimate_tokens("word " * 100) > 0
