"""Consolidation: distill proposals, prune archive, resurrection."""

import json
from datetime import timedelta

from myst_persistence import consolidate, ledger
from myst_persistence.model import Entry
from myst_persistence.paths import MystPaths
from myst_persistence.timeutil import now


def _entry(**kw):
    base = dict(kind="decision", title="t", id=0,
                ts=now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    base.update(kw)
    return Entry.create(**base)


def _days_ago(n):
    return (now() - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_distill_needs_threshold(paths):
    entries = [
        _entry(title="db a", id=1, tags=["db"], decision="use sqlite"),
        _entry(title="db b", id=2, tags=["db"], decision="use sqlite again"),
    ]
    assert consolidate.distill(entries, threshold=3) == []
    props = consolidate.distill(entries, threshold=2)
    assert len(props) == 1
    assert props[0].id == "pattern-db"
    assert set(props[0].provenance) == {1, 2}


def test_distill_ignores_events(paths):
    entries = [
        _entry(kind="event", title="e1", id=1, tags=["git"]),
        _entry(kind="event", title="e2", id=2, tags=["git"]),
        _entry(kind="event", title="e3", id=3, tags=["git"]),
    ]
    assert consolidate.distill(entries, threshold=3) == []


def test_distill_uses_latest_formulation(paths):
    entries = [
        _entry(title="old", id=1, tags=["db"], decision="first wording"),
        _entry(title="new", id=2, tags=["db"], decision="final wording"),
        _entry(title="newer", id=3, tags=["db"], decision="latest wording"),
    ]
    props = consolidate.distill(entries, threshold=3)
    assert "latest wording" in props[0].text


def test_apply_proposals_adds_and_merges():
    from myst_persistence.semantic import SemanticStore
    entries = [
        _entry(title="a", id=1, tags=["db"], decision="x"),
        _entry(title="b", id=2, tags=["db"], decision="y"),
        _entry(title="c", id=3, tags=["db"], decision="z"),
    ]
    props = consolidate.distill(entries, threshold=3)
    store = SemanticStore()
    r1 = consolidate.apply_proposals(store, props)
    assert r1["added"] == 1
    # re-apply with extended provenance → merge, not duplicate
    props2 = consolidate.distill(entries + [_entry(title="d", id=4,
                                                   tags=["db"], decision="w")],
                                 threshold=3)
    r2 = consolidate.apply_proposals(store, props2)
    assert r2["added"] == 0
    assert r2["merged"] == 1
    assert len(store.items) == 1


def test_prune_moves_cold_closed_old(paths):
    old = _entry(title="dead", tags=["cold-topic"],
                 ts=_days_ago(400), status="obsolete")
    fresh = _entry(title="live", tags=["db"], ts=_days_ago(1))
    for e in (old, fresh):
        ledger.append_entry(paths.ledger_file, e)

    report = consolidate.prune(paths, [old, fresh], prune_after=365.0)
    assert report["pruned"] == [old.id]
    remaining = ledger.load_entries(paths.ledger_file)
    assert [e.title for e in remaining] == ["live"]
    # archive file got the pruned entry
    archived = json.loads(consolidate.archive_file(paths)
                          .read_text(encoding="utf-8"))
    assert archived["entry"]["title"] == "dead"


def test_prune_keeps_active_even_old(paths):
    old_active = _entry(title="still binding", tags=["core"],
                         ts=_days_ago(700))
    ledger.append_entry(paths.ledger_file, old_active)
    report = consolidate.prune(paths, [old_active], prune_after=365.0)
    assert report["pruned"] == []
    assert len(ledger.load_entries(paths.ledger_file)) == 1


def test_prune_keeps_hot(paths):
    hot = _entry(title="hot topic", tags=["db"], status="obsolete",
                 ts=_days_ago(400))
    recent = _entry(title="recent db", tags=["db"], ts=_days_ago(2))
    ledger.append_entry(paths.ledger_file, recent)
    report = consolidate.prune(paths, [hot, recent], prune_after=365.0)
    assert report["pruned"] == []


def test_prune_keeps_pinned(paths):
    pinned = _entry(title="pinned old", tags=["x"], pinned=True,
                    status="obsolete", ts=_days_ago(500))
    report = consolidate.prune(paths, [pinned], prune_after=365.0)
    assert report["pruned"] == []


def test_resurrect_hot_topic(paths):
    archived = _entry(title="db from the past", id=5, tags=["db"],
                      ts=_days_ago(300))
    with consolidate.archive_file(paths).open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"entry": archived.asdict()}) + "\n")
    live = [_entry(title="current db work", id=1, tags=["db"],
                   ts=_days_ago(1))]
    revived = consolidate.resurrect(paths, live)
    assert len(revived) == 1
    entries = ledger.load_entries(paths.ledger_file)
    assert any(e.title == "db from the past" for e in entries)


def test_resurrect_skips_duplicates(paths):
    archived = _entry(title="dup title", id=5, tags=["db"],
                      ts=_days_ago(300))
    with consolidate.archive_file(paths).open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({"entry": archived.asdict()}) + "\n")
    live = [_entry(title="dup title", id=1, tags=["db"], ts=_days_ago(1))]
    assert consolidate.resurrect(paths, live) == []


def test_prune_empty_ledger_noop(paths):
    report = consolidate.prune(paths, [], prune_after=365.0)
    assert report["pruned"] == []
