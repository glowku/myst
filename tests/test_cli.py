"""CLI end-to-end: every subcommand through main(argv)."""

import json

import pytest

from myst_persistence import commands as cmd
from myst_persistence.cli import main
from myst_persistence.paths import MystPaths


def run(cwd, argv):
    import os
    from myst_persistence import paths as paths_mod
    old = os.getcwd()
    os.chdir(cwd)
    try:
        return main(argv)
    finally:
        os.chdir(old)


def test_init_creates_layout(tmp_path):
    code = run(tmp_path, ["init", "--name", "x", "--description", "y"])
    assert code == 0
    layer = tmp_path / ".myst"
    assert (layer / "myst.toml").exists()
    assert (layer / "ledger.jsonl").exists()
    assert (layer / "semantic.toml").exists()
    assert (layer / "ledger.jsonl.head").exists()


def test_init_idempotent(tmp_path):
    assert run(tmp_path, ["init", "--name", "x"]) == 0
    assert run(tmp_path, ["init", "--name", "x"]) == 1  # refuses to clobber
    assert run(tmp_path, ["init", "--name", "x", "--force"]) == 0


def test_log_and_show(tmp_path):
    run(tmp_path, ["init", "--name", "t"])
    code = run(tmp_path, ["log", "db choice", "--kind", "decision",
                          "--decision", "sqlite", "--tags", "db,arch",
                          "--options", "sqlite=zero-ops*|pg=powerful"])
    assert code == 0
    code, _ = 0, None
    entries = json.loads(run_out(tmp_path, ["export"]))
    assert entries["ledger"][0]["title"] == "db choice"
    assert entries["ledger"][0]["tags"] == ["db", "arch"]
    assert entries["ledger"][0]["options"][0]["chosen"] is True


def run_out(cwd, argv, cap=None):
    """Run main() capturing stdout text."""
    import contextlib, io
    buf = io.StringIO()
    import os
    old = os.getcwd()
    os.chdir(cwd)
    try:
        with contextlib.redirect_stdout(buf):
            main(argv)
    finally:
        os.chdir(old)
    return buf.getvalue()


def test_state_saves_file(tmp_path):
    run(tmp_path, ["init", "--name", "s"])
    run(tmp_path, ["log", "a decision", "--kind", "decision"])
    code = run(tmp_path, ["state", "--budget", "500"])
    assert code == 0
    assert (tmp_path / ".myst" / "state" / "current.md").exists()


def test_verify_reports_integrity(tmp_path):
    run(tmp_path, ["init"])
    run(tmp_path, ["log", "one", "--kind", "decision"])
    run(tmp_path, ["log", "two", "--kind", "decision"])
    ledger_file = tmp_path / ".myst" / "ledger.jsonl"
    text = ledger_file.read_text(encoding="utf-8")
    ledger_file.write_text(text.replace("two", "TWO"), encoding="utf-8")
    code = run(tmp_path, ["verify"])
    assert code == 2


def test_export_import_roundtrip(tmp_path):
    run(tmp_path, ["init", "--name", "round"])
    run(tmp_path, ["log", "entry one", "--kind", "decision"])
    run(tmp_path, ["log", "entry two", "--kind", "rejection"])
    out = tmp_path / "bak.json"
    assert run(tmp_path, ["export", str(out)]) == 0

    other = tmp_path / "other"
    other.mkdir()
    run(other, ["init", "--name", "dest"])
    assert run(other, ["import", str(out), "--mode", "merge"]) == 0
    exported = json.loads(run_out(other, ["export"]))
    titles = [e["title"] for e in exported["ledger"]]
    assert "entry one" in titles and "entry two" in titles


def test_import_replace_backs_up(tmp_path):
    run(tmp_path, ["init"])
    run(tmp_path, ["log", "original", "--kind", "decision"])
    out = tmp_path / "bak.json"
    run(tmp_path, ["export", str(out)])
    run(tmp_path, ["log", "extra", "--kind", "decision"])
    assert run(tmp_path, ["import", str(out), "--mode", "replace"]) == 0
    backups = list((tmp_path / ".myst" / "backups").iterdir())
    assert backups


def test_doctor_reports_ok(tmp_path):
    run(tmp_path, ["init"])
    run(tmp_path, ["log", "fine", "--kind", "decision"])
    assert run(tmp_path, ["doctor"]) == 0


def test_doctor_fails_on_dangling_supersede(tmp_path):
    run(tmp_path, ["init"])
    # The CLI refuses invalid links (returns 1, logs nothing) — the
    # dangling case must be injected at the ledger level.
    assert run(tmp_path, ["log", "a", "--kind", "decision",
                          "--supersedes", "99"]) == 1
    run(tmp_path, ["log", "base", "--kind", "decision"])
    from myst_persistence import ledger as L
    from myst_persistence.model import Entry
    L.append_entry(tmp_path / ".myst" / "ledger.jsonl",
                   Entry.create(kind="decision", title="dangling",
                                supersedes=99))
    assert run(tmp_path, ["doctor"]) == 1


def test_status_line(tmp_path):
    run(tmp_path, ["init", "--name", "st"])
    out = run_out(tmp_path, ["status"])
    assert "myst:" in out
    run(tmp_path, ["log", "one", "--kind", "decision"])
    out = run_out(tmp_path, ["status"])
    assert "1 entries" in out


def test_consolidate_apply(tmp_path):
    run(tmp_path, ["init"])
    for i in range(3):
        run(tmp_path, ["log", "db %d" % i, "--kind", "decision",
                       "--decision", "use sqlite", "--tags", "db"])
    code = run(tmp_path, ["consolidate", "--apply", "--threshold", "3",
                          "--no-prune"])
    assert code == 0
    sem = (tmp_path / ".myst" / "semantic.toml").read_text(encoding="utf-8")
    assert "pattern-db" in sem


def test_hook_post_commit_and_pre_push(tmp_path):
    run(tmp_path, ["init"])
    # outside a git repo: both hooks stay silent (exit 0, no crash)
    assert run(tmp_path, ["hook", "post-commit"]) == 0
    assert run(tmp_path, ["hook", "pre-push"]) == 0


def test_agent_file(tmp_path):
    run(tmp_path, ["init"])
    assert run(tmp_path, ["agent-file"]) == 0
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "cognitive persistence" in text
    assert run(tmp_path, ["agent-file"]) == 0  # second run: already there


def test_no_command_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "init" in out


def test_not_initialized_error(tmp_path):
    code = run(tmp_path, ["status"])
    # empty project → NotInitialized → exit 1
    assert code == 1
