"""Retrieval scoring: recency decay, frequency, pin, focus, status."""

from datetime import timedelta

from myst_persistence.model import Entry
from myst_persistence.profile import RetrievalTuning
from myst_persistence.retrieval import (
    recency_component, score_entries, topic_frequencies)
from myst_persistence.timeutil import now


def _entry(**kw):
    base = dict(kind="decision", title="t", ts=now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    base.update(kw)
    return Entry.create(**base)


TUNING = RetrievalTuning()


def test_recency_halflife():
    ref = now()
    fresh = _entry(ts=(ref - timedelta(days=0)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    month = _entry(ts=(ref - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    quarter = _entry(ts=(ref - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert recency_component(fresh, ref, 30.0) == pytest.approx(1.0)
    assert recency_component(month, ref, 30.0) == pytest.approx(0.5, rel=0.02)
    assert recency_component(quarter, ref, 30.0) == pytest.approx(0.125, rel=0.02)


import pytest


def test_undated_entry_never_crashes():
    e = _entry()
    e.ts = "not-a-date"
    assert recency_component(e, now(), 30.0) == 0.0


def test_pinned_outranks_unpinned():
    pinned = _entry(title="pinned", pinned=True,
                    ts=(now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    plain = _entry(title="plain",
                   ts=(now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    scored = score_entries([plain, pinned], TUNING)
    assert scored[0][0] is pinned


def test_recency_dominates():
    old = _entry(title="old",
                 ts=(now() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    new = _entry(title="new",
                 ts=now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    scored = score_entries([old, new], TUNING)
    assert scored[0][0] is new


def test_topic_frequency_hot_tags():
    ref = now()
    entries = [
        _entry(title="a", tags=["db"], ts=now().strftime("%Y-%m-%dT%H:%M:%SZ")),
        _entry(title="b", tags=["db"], ts=now().strftime("%Y-%m-%dT%H:%M:%SZ")),
        _entry(title="c", tags=["arch"], ts=now().strftime("%Y-%m-%dT%H:%M:%SZ")),
    ]
    freqs = topic_frequencies(entries)
    assert freqs["db"] == pytest.approx(2 / 3)
    assert freqs["arch"] == pytest.approx(1 / 3)


def test_focus_boosts_matching_entries():
    db_entry = _entry(title="sqlite choice", decision="db decision",
                      tags=["db"])
    other = _entry(title="ui choice", decision="css work", tags=["ui"])
    scored = score_entries([db_entry, other], TUNING, focus="db sqlite")
    assert scored[0][0] is db_entry
    assert "focus" in scored[0][2]


def test_superseded_downweighted():
    live = _entry(title="live decision")
    dead = _entry(title="dead decision")
    dead.status = "superseded"
    scored = score_entries([dead, live], TUNING)
    assert scored[0][0] is live


def test_reason_string_mentions_pin():
    e = _entry(title="p", pinned=True)
    scored = score_entries([e], TUNING)
    assert "pinned" in scored[0][2]


def test_stable_sort_tiebreak():
    a = _entry(title="a", id=1)
    b = _entry(title="b", id=2)
    scored = score_entries([b, a], TUNING)
    assert [x[0].title for x in scored] == ["a", "b"]  # same score → id order
