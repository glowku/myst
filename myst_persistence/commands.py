"""High-level command layer used by the CLI, the MCP server and hooks.

Each command is a pure-ish function over MystPaths + arguments and
returns (exit_code, printable_output) or structured data. Keeping the
logic here (not in argparse) means the MCP server exposes the exact same
semantics as the terminal, and tests exercise one code path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import ledger as _ledger
from .consolidate import (distill as _distill, apply_proposals,
                          prune as _prune, resurrect as _resurrect)
from .errors import MystError, NotInitialized, IntegrityError
from .model import Entry, Option, Kind, Status, SemanticItem, SemanticKind
from .paths import MystPaths
from .profile import ProjectProfile
from .render import render_show
from .semantic import SemanticStore
from .state import build_state, generate_and_save
from .terminal import painter_for, truncate
from .timeutil import now_iso

DEFAULT_PROFILE_NAME = "project"


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def init(project_name: str = "", description: str = "",
         root: Path | None = None, force: bool = False) -> tuple:
    """Create the .myst/ layer. Idempotent unless files exist (force)."""
    root = Path(root) if root else Path.cwd()
    paths = MystPaths(root)

    if paths.layer.exists() and any(paths.layer.iterdir()) and not force:
        existing = sorted(p.name for p in paths.layer.iterdir())
        return 1, (".myst/ already exists (%s) — use --force to complete "
                   "missing parts; existing files are kept"
                   % ", ".join(existing[:6]))

    paths.ensure_dirs()

    profile = ProjectProfile.load(paths.profile_file)
    if not paths.profile_file.exists():
        profile.name = project_name or root.resolve().name or DEFAULT_PROFILE_NAME
        profile.description = description or ""
        profile.save(paths.profile_file)

    if not paths.ledger_file.exists():
        paths.ledger_file.write_text("", encoding="utf-8")
        _ledger._write_head(paths.ledger_file, _ledger.GENESIS)

    if not paths.semantic_file.exists():
        SemanticStore().save(paths.semantic_file, paths.semantic_dir)

    # keep the layer out of source control noise
    gitignore = root / ".gitignore"
    if gitignore.exists():
        text = gitignore.read_text(encoding="utf-8")
        if ".myst/" not in text:
            with gitignore.open("a", encoding="utf-8") as fh:
                fh.write("\n# myst cognitive layer (local state)\n.myst/\n")

    return 0, ("initialized .myst/ for %r (%s)\n"
                "  profile: %s\n"
                "  next: myst log \"first decision\"" % (
                    profile.name, paths.layer, paths.profile_file))


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

def log(text: str, kind: str = Kind.DECISION, context: str = "",
        decision: str = "", rejection: str = "", consequences: str = "",
        options: list | None = None, tags: list | None = None,
        status: str = Status.ACTIVE, supersedes: int | None = None,
        pinned: bool = False, confidence: float = 0.0,
        paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Append one entry (free text OR structured fields)."""
    paths = paths or MystPaths.discover(root)
    profile = ProjectProfile.load(paths.profile_file)

    title = text
    if options:
        opts = [Option(name=str(o.get("name", "")), chosen=bool(o.get("chosen")),
                      reason=str(o.get("reason", "")),
                      detail=str(o.get("detail", "")))
                for o in options if str(o.get("name", "")).strip()]
    else:
        opts = []
        # free-text heuristics: "Rejected X — reason" style
        if kind == Kind.REJECTION and not rejection and not decision:
            rejection = text

    if supersedes is not None:
        entries = _ledger.load_entries(paths.ledger_file)
        target = next((e for e in entries if e.id == supersedes), None)
        if target is None:
            return 1, "no entry #%d to supersede" % supersedes
        if not status:
            status = Status.SUPERSEDED
        # the OLD entry keeps its bytes: mark by writing a tombstone copy
        # — we cannot rewrite. Instead the new entry records `supersedes`
        # and retrieval downweights old status via the supersede map.
        if target.status == Status.ACTIVE and status == Status.ACTIVE:
            status = Status.SUPERSEDED

    entry = Entry.create(kind=kind, title=title, context=context,
                         options=opts, decision=decision, rejection=rejection,
                         consequences=consequences, tags=tags or [],
                         status=status, supersedes=supersedes,
                         pinned=pinned, confidence=confidence)
    entry.meta["via"] = "cli"
    _ledger.append_entry(paths.ledger_file, entry)

    # When superseding, also stamp the old entry as superseded WITHOUT
    # rewriting bytes: impossible in an append-only file — instead the
    # supersede map is derived at read time (see supersede_map). We log
    # the link only, which the renderer surfaces.
    return 0, ("logged #%d (%s) %s\n  %s" % (
        entry.id, entry.kind, entry.tags and " ".join("#" + t for t in entry.tags) or "",
        truncate(title)))


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------

def show(kind: str | None = None, status: str | None = None,
         query: str = "", include_closed: bool = True,
         paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Inspect the ledger + semantic store."""
    paths = paths or MystPaths.discover(root)
    profile = ProjectProfile.load(paths.profile_file)
    entries = _ledger.load_entries(paths.ledger_file)
    store = SemanticStore.load(paths.semantic_file)

    if kind:
        entries = [e for e in entries if e.kind == kind]
    if status:
        entries = [e for e in entries if e.status == status]
    if query:
        q = query.lower()
        entries = [e for e in entries
                   if q in e.title.lower() or q in e.decision.lower()
                   or q in e.rejection.lower() or q in (e.context or "").lower()]
    if not include_closed:
        sup = _ledger.supersede_map(_ledger.load_entries(paths.ledger_file))
        entries = [e for e in entries
                   if e.status == "active" or e.id in sup]

    text = render_show(entries, store, profile.name)
    return 0, text


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def state(budget: int | None = None, focus: str = "", fmt: str = "markdown",
          include_closed: bool = False, max_entries: int = 25,
          save: bool = True, name: str = "current",
          paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Generate the injectable state; returns (code, text)."""
    paths = paths or MystPaths.discover(root)
    profile = ProjectProfile.load(paths.profile_file)
    entries = _ledger.load_entries(paths.ledger_file)
    store = SemanticStore.load(paths.semantic_file)

    b = budget if budget is not None else profile.retrieval.default_budget
    bundle = build_state(entries, store, profile, budget=b, focus=focus,
                         fmt=fmt, include_closed=include_closed,
                         max_entries=max_entries)
    if save:
        ext = "md" if fmt in ("markdown", "compact") else "json"
        out = paths.state_file(name).with_suffix("." + ext)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(bundle["text"], encoding="utf-8")
        bundle["path"] = str(out)
    return 0, bundle["text"] if not save else (
        bundle["text"] + "\n[saved to %s]" % bundle.get("path", ""))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def verify(paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Verify ledger integrity (hash chain + head)."""
    paths = paths or MystPaths.discover(root)
    if not paths.ledger_file.exists():
        return 1, "no ledger at %s — nothing to verify" % paths.ledger_file
    report = _ledger.verify_chain(paths.ledger_file)
    if report["ok"]:
        return 0, ("OK — %d entries, chain intact (head %s…)"
                   % (report["count"], _ledger.head_file(paths.ledger_file)
                      .read_text(encoding="utf-8").strip()[:12]))
    return 2, "INTEGRITY FAILURE\n" + "\n".join("  - " + e for e in report["errors"])


# ---------------------------------------------------------------------------
# consolidate
# ---------------------------------------------------------------------------

def consolidate(paths: MystPaths | None = None, apply: bool = False,
                threshold: int = 3, prune_after: float = 365.0,
                resurrect_days: int = 0, root: Path | None = None) -> tuple:
    """Distill episodes → semantic items; optionally prune/resurrect."""
    paths = paths or MystPaths.discover(root)
    entries = _ledger.load_entries(paths.ledger_file)
    store = SemanticStore.load(paths.semantic_file)

    out = []
    proposals = _distill(entries, threshold=threshold)
    if proposals:
        out.append("proposals from %d recurring patterns:" % len(proposals))
        for p in proposals:
            out.append("  - [%s] %s" % (p.kind, truncate(p.text)))
        if apply:
            result = apply_proposals(store, proposals)
            out.append("applied: %d added, %d merged (pinned=false drafts — "
                       "review, then `myst semantic.pin <id>` if they deserve it)"
                       % (result["added"], result["merged"]))
            store.save(paths.semantic_file, paths.semantic_dir)
        else:
            out.append("(dry-run — pass --apply to write into semantic memory)")
    else:
        out.append("no recurring patterns at threshold %d" % threshold)

    if prune_after and prune_after > 0:
        pr = _prune(paths, entries, prune_after=prune_after)
        if pr["pruned"]:
            out.append("pruned %d cold entries → %s"
                       % (len(pr["pruned"]), pr["archive"]))
        else:
            out.append("nothing prunable (all %d kept)" % pr["kept"])

    if resurrect_days:
        revived = _resurrect(paths, entries)
        out.append("resurrected %d archived entries (hot topics)" % len(revived))

    return 0, "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# export / import
# ---------------------------------------------------------------------------

def export_json(out_path: Path | None = None,
                paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Dump ledger + semantic + profile as one JSON document."""
    paths = paths or MystPaths.discover(root)
    profile = ProjectProfile.load(paths.profile_file)
    entries = _ledger.load_entries(paths.ledger_file)
    store = SemanticStore.load(paths.semantic_file)
    data = {
        "format": "myst-export",
        "version": 2,
        "exported": now_iso(),
        "project": {
            "name": profile.name, "description": profile.description,
            "retrieval": {
                "half-life": profile.retrieval.half_life,
                "recency-weight": profile.retrieval.recency_weight,
                "frequency-weight": profile.retrieval.frequency_weight,
                "pin-weight": profile.retrieval.pin_weight,
                "default-budget": profile.retrieval.default_budget,
            },
        },
        "ledger": [e.asdict() for e in entries],
        "chain": {
            "head": _ledger.head_file(paths.ledger_file).read_text(
                encoding="utf-8").strip() if _ledger.head_file(
                paths.ledger_file).exists() else None,
        },
        "semantic": [i.to_dict() for i in store.all()],
    }
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return 0, "exported %d entries + %d semantic items → %s" % (
            len(entries), len(store.items), out)
    return 0, text


def import_json(in_path: Path, mode: str = "merge",
                paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Import an export: merge (append, re-id) or replace (backup first)."""
    paths = paths or MystPaths.discover(root)
    data = json.loads(Path(in_path).read_text(encoding="utf-8"))
    if data.get("format") != "myst-export" or data.get("version") != 2:
        return 1, "not a myst v2 export (format=%r version=%r)" % (
            data.get("format"), data.get("version"))

    incoming_entries = [Entry.from_dict(raw) for raw in data.get("ledger", [])]
    incoming_items = [SemanticItem.from_dict(raw)
                      for raw in data.get("semantic", [])]

    if mode == "replace":
        import shutil as _sh
        stamp = now_iso().replace(":", "")
        backup = paths.backup_dir / ("pre-import-%s" % stamp)
        backup.mkdir(parents=True, exist_ok=True)
        for f in (paths.ledger_file, paths.semantic_file, paths.profile_file):
            if f.exists():
                _sh.copy2(f, backup / f.name)
        paths.ledger_file.write_text("", encoding="utf-8")
        _ledger._write_head(paths.ledger_file, _ledger.GENESIS)
        store = SemanticStore()
    else:
        store = SemanticStore.load(paths.semantic_file)

    added = 0
    for raw in incoming_entries:
        entry = Entry.from_dict(raw.asdict()) if isinstance(raw, Entry) else raw
        fresh = Entry.create(kind=entry.kind, title=entry.title,
                             context=entry.context,
                             options=[Option.from_dict(o.to_dict())
                                      for o in entry.options],
                             decision=entry.decision, rejection=entry.rejection,
                             consequences=entry.consequences,
                             tags=list(entry.tags), status=entry.status,
                             supersedes=entry.supersedes, pinned=entry.pinned,
                             confidence=entry.confidence)
        fresh.meta = dict(entry.meta)
        fresh.meta["imported_from"] = str(in_path)
        if entry.ts:
            fresh.ts = entry.ts
        _ledger.append_entry(paths.ledger_file, fresh)
        added += 1

    merged_items = 0
    for item in incoming_items:
        try:
            store.add(item, replace=True)
            merged_items += 1
        except ValueError:
            existing = store.get(item.id)
            if existing:
                existing.provenance = sorted(
                    set(existing.provenance) | set(item.provenance))
                merged_items += 1

    store.save(paths.semantic_file, paths.semantic_dir)
    if data.get("project"):
        prof = ProjectProfile.load(paths.profile_file)
        prof.name = data["project"].get("name", prof.name)
        prof.description = data["project"].get("description", prof.description)
        prof.save(paths.profile_file)

    return 0, "imported %d entries, %d semantic items (mode=%s)" % (
        added, merged_items, mode)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def doctor(paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Health check: layout, chain, orphan references, semantic validity."""
    paths = paths or MystPaths.discover(root)
    checks = []

    def check(name, ok, detail=""):
        checks.append(("ok" if ok else "FAIL", name, detail))

    check("layer layout", paths.layer.exists() and paths.profile_file.exists(),
          str(paths.layer))
    report = _ledger.verify_chain(paths.ledger_file) \
        if paths.ledger_file.exists() else {"ok": False, "errors": ["no ledger"]}
    check("ledger chain", report["ok"],
          "; ".join(report["errors"][:3]) if not report["ok"]
          else "%d entries" % report["count"])

    entries = _ledger.load_entries(paths.ledger_file)
    ids = {e.id for e in entries}
    dangling = [e.id for e in entries if e.supersedes and e.supersedes not in ids]
    check("supersede links", not dangling,
          "dangling: %s" % dangling if dangling else "%d links" % sum(
              1 for e in entries if e.supersedes))

    store = SemanticStore.load(paths.semantic_file)
    orphan = [i.id for i in store.all()
              if i.provenance and not set(i.provenance) <= ids]
    check("semantic provenance", not orphan,
          "orphan refs: %s" % orphan if orphan else "%d items" % len(store.items))

    check("torn tail", not paths.ledger_file.exists()
          or paths.ledger_file.read_text(encoding="utf-8").endswith("\n")
          or paths.ledger_file.stat().st_size == 0, "missing final newline")

    fails = [c for c in checks if c[0] != "ok"]
    lines = ["myst doctor — %s" % ("ALL OK" if not fails
                                   else "%d FAILURES" % len(fails))]
    for status, name, detail in checks:
        lines.append("  [%s] %s%s" % (status, name,
                                       " — " + detail if detail else ""))
    if not fails:
        lines.append("  %d entries, %d semantic items — layer healthy"
                     % (len(entries), len(store.items)))
    return (0 if not fails else 1), "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# status (one-liner for prompts/CI)
# ---------------------------------------------------------------------------

def status(paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    paths = paths or MystPaths.discover(root)
    entries = _ledger.load_entries(paths.ledger_file)
    store = SemanticStore.load(paths.semantic_file)
    if not entries and not store.items:
        return 0, "myst: empty (no history yet)"
    line = _ledger.entry_summary_line(entries)
    inv = len(store.by_kind(SemanticKind.INVARIANT))
    return 0, "myst: %s · %d invariants" % (line, inv)


# ---------------------------------------------------------------------------
# hook (git integration)
# ---------------------------------------------------------------------------

def hook(event: str, payload: dict | None = None,
         paths: MystPaths | None = None, root: Path | None = None) -> tuple:
    """Git hook entry point.

    post-commit: log an event entry for the commit (subject + hash).
    pre-push: verify chain — a broken chain aborts the push (exit 2).
    """
    paths = paths or MystPaths.discover(root)

    if event == "post-commit":
        info = _git_commit_info(paths.root)
        if info is None:
            return 0, ""  # not a git repo / git missing: stay silent
        subject, sha = info
        entry = Entry.create(kind=Kind.EVENT,
                             title="commit %s" % sha[:8],
                             context=subject, tags=["git"])
        entry.meta = {"sha": sha, "subject": subject}
        _ledger.append_entry(paths.ledger_file, entry)
        return 0, ""

    if event == "pre-push":
        code, text = verify(paths=paths)
        if code != 0:
            return 2, "myst: ledger integrity failed — push aborted\n" + text
        return 0, ""

    return 1, "unknown hook event: %r (use post-commit|pre-push)" % event


def _git_commit_info(root: Path | None = None):
    """HEAD subject+sha of the repo at `root` (cwd by default)."""
    base = ["git"] if root is None else ["git", "-C", str(root)]
    try:
        sha = subprocess.run(
            base + ["rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10,
            check=True).stdout.strip()
        subject = subprocess.run(
            base + ["log", "-1", "--pretty=%s"],
            capture_output=True, text=True, timeout=10,
            check=True).stdout.strip()
    except Exception:
        return None
    return subject, sha


# ---------------------------------------------------------------------------
# agent-file
# ---------------------------------------------------------------------------

AGENT_FILE_TEMPLATE = """# Myst — cognitive persistence rules for this repo

This repository keeps a `.myst/` cognitive layer (ledger + semantic memory).
Any AI agent working here MUST use it to preserve reasoning across sessions.

## Rules

1. **Before starting a task** — read `.myst/state/current.md` if present
   (or run `python -m myst_persistence state` / `myst state`). Invariants
   listed there bind every choice you make in this repo.
2. **When you decide or reject something architectural** — log it:
   `myst log "<title>" --kind decision|rejection --decision "..." --tags a,b`
   Always record *why alternatives were rejected* — that is the point.
3. **When a decision changes** — log the new one with `--supersedes <id>`;
   never edit history: the ledger is append-only and hash-chained.
4. **Before ending a session** — run `myst state` and keep the output in
   the working notes; run `myst consolidate` weekly to distill patterns.
5. **Never** rewrite `.myst/ledger.jsonl` or `.myst/semantic.toml` by hand
   to "clean things up" — use the CLI, or you will break `myst verify`.

## Quick reference

    myst init                     # once per repo
    myst log "title" [options]    # append an episode
    myst state [--focus "..."]    # injectable state (token-budgeted)
    myst show [--kind decision]   # inspect
    myst verify                   # integrity
    myst consolidate --apply      # episodic → semantic distillation
"""


def agent_file(target: str = "AGENTS.md", root: Path | None = None,
               paths: MystPaths | None = None) -> tuple:
    """Write the agent instruction file into the repo root."""
    root = Path(root) if root else Path.cwd()
    paths = paths or MystPaths(root)
    out = root / target
    if out.exists():
        existing = out.read_text(encoding="utf-8")
        if "cognitive persistence" in existing:
            return 0, "%s already carries myst rules" % out.name
        with out.open("a", encoding="utf-8") as fh:
            fh.write("\n\n---\n\n" + AGENT_FILE_TEMPLATE)
        return 0, "appended myst rules to %s" % out.name
    out.write_text(AGENT_FILE_TEMPLATE, encoding="utf-8")
    return 0, "wrote %s" % out.name
