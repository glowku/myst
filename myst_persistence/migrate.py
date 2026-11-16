"""Migration from the v1 `.myst/` layout to v2.

v1 layout (the original myst.py release):

    .myst/
      invariants.yaml      # {invariants: [...], style: {...}, anti_patterns: [...]}
      trajectory/*.md      # free-form decision nodes
      current_state.md     # last generated state (v1 injector output)

v2 layout: myst.toml / ledger.jsonl(+.head) / semantic.toml / semantic.d/.

Rules:

- **never destructive** — v1 files are left untouched; v2 files are
  written beside them. A `migrated.marker` records the run.
- v1 `invariants` → semantic items `kind=invariant`, pinned.
- v1 `style` values → semantic items `kind=principle` (one per key).
- v1 `anti_patterns` → semantic items `kind=antipattern`, pinned=False.
- v1 trajectory `.md` nodes → episodic entries `kind=decision` with the
  file's title (or stem) and extracted "## Decision"/"## Décision"
  section preserved verbatim in `decision`; nothing guessed.
- v1 `current_state.md` → one `kind=event` entry noting the migration
  timestamp (the state content itself is regenerable, not data).
- YAML is read with PyYAML when installed, else our miniyaml subset
  parser (v1 files are simple enough for the subset by construction).
"""

from __future__ import annotations

import re
from pathlib import Path

from . import ledger as _ledger
from .errors import DataFormatError, MystError
from .model import Entry, SemanticItem, SemanticKind
from .paths import MystPaths
from .profile import ProjectProfile
from .semantic import SemanticStore
from .timeutil import now_iso

MARKER = "migrated-from-v1.marker"


class MigrationError(MystError):
    pass


def _load_v1_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(text) or {}
    except ImportError:
        from .miniyaml import loads
        data = loads(text) or {}
    if not isinstance(data, dict):
        raise DataFormatError("invariants.yaml: expected a mapping")
    return data


def _parse_trajectory_node(path: Path) -> Entry:
    """Parse one v1 trajectory .md node into an episodic entry."""
    content = path.read_text(encoding="utf-8")
    title = _first_heading(content) or path.stem

    decision = _section(content, ("Decision", "Décision", "Décision retenue"))
    rejection = _section(content, ("Rejected", "Rejection", "Rejeté",
                                   "Rejet", "Why not"))
    context = _section(content, ("Context", "Contexte"))

    entry = Entry.create(kind="decision", title=title)
    if decision:
        entry.decision = decision.strip()
    if rejection:
        entry.kind = "rejection"
        entry.rejection = rejection.strip()
    if context:
        entry.context = context.strip()
    entry.tags = ["v1-import"]
    entry.meta = {"source": str(path.name), "imported": now_iso()}
    return entry


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return ""


def _section(text: str, names: tuple) -> str:
    """Extract the body under the first '## <name>' heading found."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("##"):
            continue
        heading = line.lstrip("#").strip().lower()
        for name in names:
            if heading == name.lower() or heading.startswith(name.lower()):
                body = []
                for follow in lines[i + 1:]:
                    if follow.startswith("#"):
                        break
                    body.append(follow)
                out = "\n".join(body).strip()
                if out:
                    return out
    return ""


def migrate(paths: MystPaths, profile: ProjectProfile | None = None) -> dict:
    """Run the migration. Idempotent: a second run is a no-op."""
    layer = paths.layer
    marker = layer / MARKER
    if marker.exists():
        return {"already_migrated": True, "at": marker.read_text(encoding="utf-8").strip()}

    invariants_path = layer / "invariants.yaml"
    trajectory_dir = layer / "trajectory"
    state_md = layer / "current_state.md"

    if not invariants_path.exists() and not trajectory_dir.exists():
        raise MigrationError(
            "no v1 data found in %s (expected invariants.yaml / trajectory/)" % layer)

    report = {"semantic_added": 0, "entries_added": 0, "notes": []}

    # 1. semantic store: invariants + style + anti_patterns -------------------
    store = SemanticStore.load(paths.semantic_file) \
        if paths.semantic_file.exists() else SemanticStore()
    v1 = _load_v1_yaml(invariants_path)

    for i, text in enumerate(v1.get("invariants") or [], 1):
        if not str(text).strip():
            continue
        item = SemanticItem(
            id="v1-invariant-%02d" % i,
            kind=SemanticKind.INVARIANT,
            text=str(text).strip(),
            rationale="imported from v1 invariants.yaml",
            pinned=True, weight=1.0, ts=now_iso())
        store.add(item, replace=True)
        report["semantic_added"] += 1

    style = v1.get("style") or {}
    if isinstance(style, dict):
        for key, value in style.items():
            if not str(value).strip():
                continue
            item = SemanticItem(
                id="v1-style-%s" % SemanticItem.slugify(str(key)),
                kind=SemanticKind.PRINCIPLE,
                text="%s: %s" % (key, str(value).strip()),
                rationale="imported from v1 style", pinned=False, weight=0.8,
                ts=now_iso())
            store.add(item, replace=True)
            report["semantic_added"] += 1

    for i, text in enumerate(v1.get("anti_patterns") or [], 1):
        if not str(text).strip():
            continue
        item = SemanticItem(
            id="v1-antipattern-%02d" % i,
            kind=SemanticKind.ANTIPATTERN,
            text=str(text).strip(),
            rationale="imported from v1 invariants.yaml (anti_patterns)",
            pinned=False, weight=1.0, ts=now_iso())
        store.add(item, replace=True)
        report["semantic_added"] += 1

    # 2. episodic ledger: trajectory nodes -----------------------------------
    added_entries = []
    if trajectory_dir.exists():
        for node_file in sorted(trajectory_dir.glob("*.md")):
            entry = _parse_trajectory_node(node_file)
            _ledger.append_entry(paths.ledger_file, entry)
            added_entries.append(entry.id)
            report["entries_added"] += 1

    # 3. one event entry for the migration itself ------------------------------
    event = Entry.create(kind="event", title="migrated .myst layer from v1",
                         decision="v1 files kept untouched; v2 stores created "
                                  "beside them")
    if state_md.exists():
        event.meta["had_state_file"] = True
    _ledger.append_entry(paths.ledger_file, event)
    report["entries_added"] += 1

    # 4. persist semantic store + profile + marker ------------------------------
    store.save(paths.semantic_file, paths.semantic_dir)
    if profile is None:
        profile = ProjectProfile.load(paths.profile_file)
    if not paths.profile_file.exists():
        profile.save(paths.profile_file)
    paths.ensure_dirs()
    marker.write_text(now_iso() + "\n", encoding="utf-8")

    report["entries"] = added_entries
    return report
