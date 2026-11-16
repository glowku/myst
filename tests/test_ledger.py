"""Episodic ledger: append, load, hash chain, tamper detection."""

import json

import pytest

from myst_persistence import ledger
from myst_persistence.model import Entry
from myst_persistence.paths import MystPaths


def _add(paths, **kwargs):
    return ledger.append_entry(paths.ledger_file, Entry.create(**kwargs))


def test_append_assigns_dense_ids(paths):
    e1 = _add(paths, kind="decision", title="first")
    e2 = _add(paths, kind="rejection", title="second")
    assert e1.id == 1 and e2.id == 2
    entries = ledger.load_entries(paths.ledger_file)
    assert [e.id for e in entries] == [1, 2]


def test_chain_verifies(paths):
    for i in range(5):
        _add(paths, kind="decision", title="d%d" % i)
    report = ledger.verify_chain(paths.ledger_file)
    assert report["ok"], report["errors"]
    assert report["count"] == 5


def test_genesis_first(paths):
    _add(paths, kind="decision", title="x")
    lines = ledger.load_raw_lines(paths.ledger_file)
    assert lines[0][0] == ledger.GENESIS


def test_content_tamper_detected(paths):
    _add(paths, kind="decision", title="alpha", decision="original")
    _add(paths, kind="decision", title="beta", decision="also original")
    text = paths.ledger_file.read_text(encoding="utf-8")
    paths.ledger_file.write_text(
        text.replace("original", "rewritten"), encoding="utf-8")
    report = ledger.verify_chain(paths.ledger_file)
    assert not report["ok"]
    assert any("digest" in e for e in report["errors"])


def test_reorder_detected(paths):
    _add(paths, kind="decision", title="a")
    _add(paths, kind="decision", title="b")
    lines = paths.ledger_file.read_text(encoding="utf-8").splitlines()
    paths.ledger_file.write_text(lines[1] + "\n" + lines[0] + "\n",
                                 encoding="utf-8")
    report = ledger.verify_chain(paths.ledger_file)
    assert not report["ok"]


def test_tail_deletion_detected(paths):
    for i in range(3):
        _add(paths, kind="decision", title="n%d" % i)
    lines = paths.ledger_file.read_text(encoding="utf-8").splitlines()
    paths.ledger_file.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    report = ledger.verify_chain(paths.ledger_file)
    assert not report["ok"]
    assert any("head" in e for e in report["errors"])


def test_supersede_map(paths):
    e1 = _add(paths, kind="decision", title="original choice")
    e2 = _add(paths, kind="decision", title="revised choice")
    e2.supersedes = e1.id
    # rewrite would break chain — instead simulate via append directly
    e3 = Entry.create(kind="decision", title="third", supersedes=e1.id)
    ledger.append_entry(paths.ledger_file, e3)
    entries = ledger.load_entries(paths.ledger_file)
    smap = ledger.supersede_map(entries)
    assert smap == {e1.id: [e3.id]}


def test_entry_summary_line():
    entries = [
        Entry.create(kind="decision", title="a"),
        Entry.create(kind="decision", title="b"),
        Entry.create(kind="rejection", title="c"),
    ]
    line = ledger.entry_summary_line(entries)
    assert "3 entries" in line
    assert "2 decisions" in line and "1 rejections" in line


def test_load_missing_ledger(tmp_path):
    assert ledger.load_entries(tmp_path / "nope.jsonl") == []
    assert ledger.verify_chain(tmp_path / "nope.jsonl")["ok"]


def test_append_after_manual_edit_without_newline(paths):
    _add(paths, kind="decision", title="first")
    text = paths.ledger_file.read_text(encoding="utf-8").rstrip("\n")
    paths.ledger_file.write_text(text, encoding="utf-8")
    _add(paths, kind="decision", title="second")
    entries = ledger.load_entries(paths.ledger_file)
    assert len(entries) == 2
    assert ledger.verify_chain(paths.ledger_file)["ok"]


def test_json_serializable(paths):
    _add(paths, kind="decision", title="x", tags=["a", "b"],
         decision="d", context="c")
    for line in paths.ledger_file.read_text(encoding="utf-8").splitlines():
        json.loads(line)  # must not raise
