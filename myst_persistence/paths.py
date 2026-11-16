"""Filesystem layout of the .myst/ layer and project discovery.

Layout (v2):

    .myst/
      myst.toml          — project profile: name, description, decay tuning
      ledger.jsonl       — append-only episodic memory (hash-chained)
      semantic.toml      — curated semantic memory (invariants etc.)
      semantic.d/        — one file per semantic item (large items)
      state/             — generated injectable states (gitignored)
      backups/           — copies made before destructive ops (import --replace)

Discovery walks up from the working directory until a directory containing
a `myst.toml` or `ledger.jsonl` (v1 fallback: `invariants.yaml`) is found.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import NotInitialized

# Sentinel files that mark a .myst/ layer, v2 first, v1 fallback.
_MARKERS = ("myst.toml", "ledger.jsonl", "invariants.yaml")

# Directories that never contain a project layer.
_SKIP_DIRS = {".git", ".hg", "node_modules", "__pycache__", ".venv", "venv"}


def _dir_has_marker(path: Path) -> bool:
    try:
        names = {e.name for e in os.scandir(path)}
    except OSError:
        return False
    return any(m in names for m in _MARKERS)


def find_root(start: Path | None = None) -> Path:
    """Return the project root containing .myst/, or raise NotInitialized.

    Walks up from `start` (default: cwd). Also honors MYST_DIR override.
    """
    if start is None:
        start = Path.cwd()
    start = Path(start).resolve()

    override = os.environ.get("MYST_DIR")
    if override:
        candidate = Path(override)
        if _dir_has_marker(candidate):
            return candidate.parent
        raise NotInitialized(searched=str(candidate))

    current = start
    while True:
        if current.name in _SKIP_DIRS:
            current = current.parent
            if current == current.parent:
                break
            continue
        candidate = current / ".myst"
        if _dir_has_marker(candidate):
            return current
        if current == current.parent:
            break
        current = current.parent
    raise NotInitialized(searched=str(start))


class MystPaths:
    """Resolved locations for one project's cognitive layer."""

    LAYER = ".myst"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.layer = self.root / self.LAYER
        self.profile_file = self.layer / "myst.toml"
        self.ledger_file = self.layer / "ledger.jsonl"
        self.semantic_file = self.layer / "semantic.toml"
        self.semantic_dir = self.layer / "semantic.d"
        self.state_dir = self.layer / "state"
        self.backup_dir = self.layer / "backups"

    @classmethod
    def discover(cls, start: Path | None = None) -> "MystPaths":
        """Find the project root by walking up from `start` and build paths."""
        return cls(find_root(start))

    # -- layer lifecycle ---------------------------------------------------

    def exists(self) -> bool:
        return _dir_has_marker(self.layer)

    def ensure_dirs(self) -> None:
        """Create every directory of the layer (idempotent)."""
        self.layer.mkdir(parents=True, exist_ok=True)
        self.semantic_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    # -- state files --------------------------------------------------------

    def state_file(self, name: str) -> Path:
        """Path of a generated state snapshot, `name` sanitized."""
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        if not safe:
            safe = "state"
        return self.state_dir / (safe + ".md")
