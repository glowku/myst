"""miniyaml — subset parser and dumper roundtrips."""

from myst_persistence.errors import DataFormatError
from myst_persistence.miniyaml import dump, loads


DOC = """
# v1-style invariants
invariants:
  - Prefer composition over inheritance
  - 'Never lose the reason a path was rejected'
style:
  decision_style: Explore multiple paths, document rejections clearly
  priority: Continuity of reasoning > starting from zero
anti_patterns:
  - Summarizing decisions without keeping rejected alternatives
nested:
  key: value
  deeper:
    a: 1
    b: [x, y]
empty:
quoted: "hello: world"
number: 42
floaty: 3.5
flag: true
nothing: null
"""


def test_block_mapping_and_lists():
    data = loads(DOC)
    assert data["invariants"][0] == "Prefer composition over inheritance"
    assert data["invariants"][1] == "Never lose the reason a path was rejected"
    assert data["anti_patterns"][0].startswith("Summarizing")


def test_nested_mapping():
    data = loads(DOC)
    assert data["nested"]["key"] == "value"
    assert data["nested"]["deeper"]["a"] == 1
    assert data["nested"]["deeper"]["b"] == ["x", "y"]


def test_scalar_typing():
    data = loads(DOC)
    assert data["number"] == 42
    assert data["floaty"] == 3.5
    assert data["flag"] is True
    assert data["nothing"] is None
    assert data["empty"] is None
    assert data["quoted"] == "hello: world"


def test_sequence_of_mappings():
    data = loads("""
decisions:
  - kind: decision
    title: chose sqlite
  - kind: rejection
    title: dropped mongo
""")
    assert data["decisions"][0]["kind"] == "decision"
    assert data["decisions"][1]["title"] == "dropped mongo"


def test_roundtrip():
    data = loads(DOC)
    again = loads(dump(data))
    assert again == data


def test_trailing_comment_respected():
    data = loads("key: value # comment\nother: 'x # y'\n")
    assert data == {"key": "value", "other": "x # y"}


def test_tags_refused():
    import pytest
    with pytest.raises(DataFormatError):
        loads("a: !!python/object/eval:os.system")


def test_malformed_raises():
    import pytest
    with pytest.raises(DataFormatError):
        loads("just a plain sentence\nwith no colon")


def test_empty_returns_none():
    assert loads("") is None
    assert loads("# only comments\n") is None


def test_inline_map():
    data = loads("m: {a: 1, b: two}\n")
    assert data == {"m": {"a": 1, "b": "two"}}
