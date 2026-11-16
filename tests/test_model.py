"""Entry model: construction, validation, serialization, rendering."""

import json

import pytest

from myst_persistence.model import Entry, Kind, Option, Status


def test_create_defaults():
    e = Entry.create(title="t")
    assert e.kind == Kind.DECISION
    assert e.status == Status.ACTIVE
    assert e.ts  # auto-stamped
    assert e.confidence == 0.0


def test_create_rejects_empty_title():
    with pytest.raises(ValueError):
        Entry.create(title="")


def test_create_rejects_bad_kind():
    with pytest.raises(ValueError):
        Entry.create(title="t", kind="mystery")


def test_create_rejects_bad_confidence():
    with pytest.raises(ValueError):
        Entry.create(title="t", confidence=1.5)


def test_unknown_field():
    with pytest.raises(TypeError):
        Entry.create(title="t", nonsense=1)


def test_option_roundtrip():
    o = Option(name="sqlite", chosen=True, reason="zero ops")
    d = o.to_dict()
    again = Option.from_dict(d)
    assert again == o


def test_canonical_json_stable():
    e = Entry.create(title="t", kind="rejection", decision="d",
                    tags=["b", "a"], options=[Option(name="x")])
    e.ts = "2026-01-01T00:00:00Z"
    c1, c2 = e.canonical(), e.canonical()
    assert c1 == c2  # deterministic
    data = json.loads(c1)
    assert data["tags"] == ["b", "a"]
    assert data["kind"] == "rejection"


def test_asdict_jsonable():
    e = Entry.create(title="t")
    json.dumps(e.asdict())  # must not raise


def test_from_dict_roundtrip():
    e = Entry.create(title="t", kind="insight", decision="d",
                     rejection="r", consequences="c", tags=["x"],
                     pinned=True, confidence=0.7, supersedes=3)
    e.ts = "2026-05-05T05:05:05Z"
    again = Entry.from_dict(e.asdict())
    assert again.canonical() == e.canonical()


def test_render_md_contains_sections():
    e = Entry.create(
        title="chose sqlite", kind="decision", context="need a db",
        decision="sqlite embedded", consequences="zero ops",
        rejection="mongo too heavy",
        options=[Option(name="sqlite", chosen=True, reason="ops"),
                 Option(name="mongo", reason="heavy")])
    md = e.render_md()
    assert "**Context**" in md
    assert "**Options considered**" in md
    assert "✓ **sqlite**" in md and "✗ **mongo**" in md
    assert "**Decision**" in md
    assert "**Rejected because**" in md
    assert "**Consequences**" in md


def test_summary_line():
    e = Entry.create(title="short", kind="risk", pinned=True)
    e.id = 7
    s = e.summary()
    assert "#7" in s and "risk" in s and "(pinned)" in s


def test_kind_and_status_enums():
    assert Kind.is_valid("decision") and not Kind.is_valid("bogus")
    assert Status.is_valid("reversed") and not Status.is_valid("zombie")
