"""Semantic store: TOML roundtrips, ordering, provenance, docs."""

import pytest

from myst_persistence.model import SemanticItem, SemanticKind
from myst_persistence.semantic import SemanticStore


def _item(**kw):
    base = dict(id="x-1", kind=SemanticKind.INVARIANT, text="text",
                rationale="why", tags=["a"], pinned=True, weight=1.0,
                provenance=[1], ts="2026-01-01T00:00:00Z")
    base.update(kw)
    return SemanticItem(**base)


def test_add_and_get():
    s = SemanticStore()
    s.add(_item())
    assert s.get("x-1").text == "text"


def test_duplicate_id_rejected():
    s = SemanticStore()
    s.add(_item())
    with pytest.raises(ValueError):
        s.add(_item())


def test_toml_roundtrip(tmp_path):
    s = SemanticStore()
    s.add(_item(id="inv-one", text="Keep it flat"))
    s.add(_item(id="ap-two", kind=SemanticKind.ANTIPATTERN,
                text="No meta-systems", pinned=False, weight=2.0,
                provenance=[3, 5]))
    p = tmp_path / "semantic.toml"
    s.save(p, tmp_path / "semantic.d")

    s2 = SemanticStore.load(p)
    assert set(s2.items) == {"inv-one", "ap-two"}
    assert s2.get("inv-one").pinned is True
    assert s2.get("ap-two").pinned is False
    assert s2.get("ap-two").provenance == [3, 5]
    assert s2.get("ap-two").weight == 2.0


def test_doc_file_written(tmp_path):
    s = SemanticStore()
    s.add(_item(id="has-doc", text="Documented invariant",
                rationale="because reasons"))
    s.save(tmp_path / "semantic.toml", tmp_path / "semantic.d")
    doc = (tmp_path / "semantic.d" / "has-doc.md").read_text(encoding="utf-8")
    assert "Documented invariant" in doc
    assert "because reasons" in doc


def test_stale_doc_removed(tmp_path):
    s = SemanticStore()
    s.add(_item(id="keep-me", text="kept"))
    s.save(tmp_path / "semantic.toml", tmp_path / "semantic.d")
    stale = tmp_path / "semantic.d" / "stale-item.md"
    stale.write_text("orphan", encoding="utf-8")
    s.save(tmp_path / "semantic.toml", tmp_path / "semantic.d")
    assert not stale.exists()
    assert (tmp_path / "semantic.d" / "keep-me.md").exists()


def test_kind_ordering_stable():
    s = SemanticStore()
    s.add(_item(id="z-fact", kind=SemanticKind.FACT, text="f"))
    s.add(_item(id="a-inv", kind=SemanticKind.INVARIANT, text="i"))
    s.add(_item(id="m-ap", kind=SemanticKind.ANTIPATTERN, text="a"))
    order = [i.kind for i in s.all()]
    assert order == ["invariant", "antipattern", "fact"]


def test_search():
    s = SemanticStore()
    s.add(_item(id="one", text="Prefer composition over inheritance"))
    s.add(_item(id="two", text="Never lose rejections"))
    hits = s.search("composition")
    assert [i.id for i in hits] == ["one"]


def test_validation():
    with pytest.raises(ValueError):
        SemanticItem(id="", kind=SemanticKind.INVARIANT, text="x").validate()
    with pytest.raises(ValueError):
        SemanticItem(id="y", kind=SemanticKind.INVARIANT,
                     text="").validate()
    with pytest.raises(ValueError):
        SemanticItem(id="y", kind="bogus", text="x").validate()


def test_slugify():
    assert SemanticItem.slugify("Prefer Composition! Over   Inheritance") \
        == "prefer-composition-over-inheritance"
    assert SemanticItem.slugify("!!!") == "item"


def test_render_md_has_sections():
    s = SemanticStore()
    s.add(_item(id="i", kind=SemanticKind.INVARIANT, text="Inv text"))
    s.add(_item(id="a", kind=SemanticKind.ANTIPATTERN, text="Anti text"))
    md = s.render_md()
    assert "### Invariants" in md
    assert "### Anti-patterns" in md
    assert "- **Inv text**" in md
