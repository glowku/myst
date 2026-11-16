"""Profile TOML, paths discovery, tokens, terminal helpers, render."""

import os

from myst_persistence.paths import MystPaths, find_root
from myst_persistence.profile import ProjectProfile, RetrievalTuning
from myst_persistence.render import render_state_compact, render_state_markdown
from myst_persistence.tokens import clamp_to_budget, estimate_tokens


# ── profile ─────────────────────────────────────────────────────────────

def test_profile_roundtrip(tmp_path):
    p = ProjectProfile(name="app", description="d")
    p.retrieval.half_life = 45.5
    f = tmp_path / "myst.toml"
    p.save(f)
    again = ProjectProfile.load(f)
    assert again.name == "app"
    assert again.retrieval.half_life == 45.5
    assert again.retrieval.default_budget == 2000


def test_profile_dashed_keys():
    text = """
[project]
name = "x"

[retrieval]
half-life = 20
recency-weight = 2
default-budget = 900
"""
    p = ProjectProfile.from_toml(text)
    assert p.retrieval.half_life == 20
    assert p.retrieval.recency_weight == 2
    assert p.retrieval.default_budget == 900


def test_profile_validation():
    with_error = RetrievalTuning(half_life=0)
    import pytest
    with pytest.raises(ValueError):
        with_error.validate()
    bad_budget = RetrievalTuning(default_budget=10)
    with pytest.raises(ValueError):
        bad_budget.validate()


# ── paths discovery ─────────────────────────────────────────────────────

def test_discover_walks_up(tmp_path):
    root = tmp_path / "repo"
    (root / ".myst").mkdir(parents=True)
    (root / ".myst" / "myst.toml").write_text("[project]\nname = 'r'\n",
                                              encoding="utf-8")
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    assert find_root(deep) == root


def test_discover_not_initialized(tmp_path):
    from myst_persistence.errors import NotInitialized
    import pytest
    with pytest.raises(NotInitialized):
        find_root(tmp_path)


def test_myst_dir_env_override(tmp_path, monkeypatch):
    layer = tmp_path / "custom-layer"
    layer.mkdir()
    (layer / "myst.toml").write_text("[project]\nname='c'\n", encoding="utf-8")
    monkeypatch.setenv("MYST_DIR", str(layer))
    assert find_root(tmp_path / "elsewhere" if (tmp_path / "elsewhere").exists()
                     else tmp_path) is not None


def test_state_file_name_sanitized(paths):
    out = paths.state_file("weird name/../x")
    assert "/" not in out.name and ".." not in out.name
    assert out.parent == paths.state_dir


# ── tokens ─────────────────────────────────────────────────────────────

def test_estimate_tokens():
    assert estimate_tokens("") == 0
    # 36 chars → 10 tokens exactly at 3.6 chars/token
    assert estimate_tokens("x" * 36) == 10


def test_clamp_marks_truncation():
    text = "word " * 200
    clamped = clamp_to_budget(text, 20)
    assert "[…clipped]" in clamped
    assert estimate_tokens(clamped) <= 25  # marker tolerance


def test_clamp_noop_when_fits():
    text = "short text"
    assert clamp_to_budget(text, 100) == text


# ── terminal ────────────────────────────────────────────────────────────

def test_painter_respects_no_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    from myst_persistence.terminal import painter_for
    p = painter_for()
    assert p.bold("x") == "x"


def test_painter_color_when_forced(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    from myst_persistence.terminal import painter_for
    p = painter_for()
    assert "\033[" in p.bold("x")


def test_truncate():
    from myst_persistence.terminal import truncate
    long = " ".join(["word"] * 30)
    out = truncate(long, 40)
    assert len(out) <= 41
    assert out.endswith("…") or len(out) <= 40


# ── render ──────────────────────────────────────────────────────────────

def _bundle():
    from myst_persistence.model import Entry
    e = Entry.create(kind="decision", title="t", decision="d", id=1)
    return {
        "project": "p", "generated": "2026-01-01T00:00:00Z",
        "objective": "obj", "tokens": 10, "total": 1,
        "semantic_items": [], "semantic_md": "",
        "entries": [e], "stats": {"total": 1, "active": 1, "closed": 0,
                                  "latest": "2026-01-01"},
    }


def test_markdown_renders_header():
    text = render_state_markdown(_bundle())
    assert text.startswith("# Cognitive state")
    assert "Objective: obj" in text


def test_compact_renders_onelines():
    text = render_state_compact(_bundle())
    assert "OBJECTIVE: obj" in text
    assert "DECISION #1" in text
