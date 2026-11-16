"""git hooks through commands.hook + doctor diagnostics + timeutil."""

import subprocess

from myst_persistence import commands as cmd
from myst_persistence.model import Entry
from myst_persistence.timeutil import days_between, fmt_date, now_iso, parse_ts


# ── timeutil ─────────────────────────────────────────────────────────────

def test_parse_ts_date_and_datetime():
    d = parse_ts("2026-11-16")
    assert d.year == 2026 and d.month == 11 and d.day == 16
    dt = parse_ts("2026-11-16T14:30:00")
    assert dt.hour == 14
    assert dt.tzinfo is not None


def test_parse_ts_rejects_garbage():
    import pytest
    for bad in ("", "2026/11/16", "not a date", "2026-13-01T99:00:00x"):
        with pytest.raises(ValueError):
            parse_ts(bad)


def test_days_between():
    a = parse_ts("2026-01-01T00:00:00")
    b = parse_ts("2026-01-04T12:00:00")
    assert days_between(a, b) == 3.5
    assert days_between(b, a) == -3.5


def test_fmt_date():
    assert fmt_date("2026-11-16T08:09:10Z") == "2026-11-16"


def test_now_iso_shape():
    ts = now_iso()
    assert len(ts) == 20 and ts.endswith("Z")
    parse_ts(ts)  # round-trips


# ── hook: git scenarios ──────────────────────────────────────────────────

def test_hook_post_commit_logs_event(git_project):
    paths = git_project["paths"]
    git = git_project["git"]
    subprocess.run(git + ["commit", "--allow-empty", "-m", "hook test"],
                   check=True, capture_output=True)
    code, text = cmd.hook("post-commit", paths=paths)
    assert code == 0
    from myst_persistence import ledger
    entries = ledger.load_entries(paths.ledger_file)
    event = entries[-1]
    assert event.kind == "event"
    assert "hook test" in event.context
    assert event.meta.get("sha")


def test_hook_pre_push_ok(git_project):
    paths = git_project["paths"]
    code, text = cmd.hook("pre-push", paths=paths)
    assert code == 0


def test_hook_pre_push_fails_on_corruption(git_project):
    paths = git_project["paths"]
    text = paths.ledger_file.read_text(encoding="utf-8")
    paths.ledger_file.write_text(text.replace("hook", "HOOKED"),
                                 encoding="utf-8")
    code, text = cmd.hook("pre-push", paths=paths)
    assert code == 2
    assert "aborted" in text


def test_hook_unknown_event(paths):
    code, text = cmd.hook("bogus", paths=paths)
    assert code == 1


def test_hook_post_commit_outside_git(project, paths):
    # not a git repo: stays silent, no crash
    code, text = cmd.hook("post-commit", paths=paths)
    assert code == 0
    assert text == ""


# ── doctor edge cases ─────────────────────────────────────────────────────

def test_doctor_orphan_provenance(project, paths):
    from myst_persistence.model import SemanticItem, SemanticKind
    from myst_persistence.semantic import SemanticStore
    store = SemanticStore()
    store.add(SemanticItem(id="orphan", kind=SemanticKind.FACT,
                           text="refers to missing entry", provenance=[42]))
    store.save(paths.semantic_file, paths.semantic_dir)
    code, text = cmd.doctor(paths=paths)
    assert code == 1
    assert "orphan" in text
