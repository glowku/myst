"""Myst Persistence — a universal cognitive persistence layer for AI agents.

Two-store memory (episodic ledger + semantic store), ADR-grade logging,
relevance-ranked injectable state under a token budget, hash-chain integrity,
and a zero-runtime-dependency stdlib-only implementation.
"""

__version__ = "2.0.0"

from .errors import MystError, NotInitialized, IntegrityError
from .paths import MystPaths
from .model import Entry, Option, Kind, Status, SemanticItem, SemanticKind
from .ledger import append_entry, load_entries, verify_chain, supersede_map
from .semantic import SemanticStore
from .profile import ProjectProfile

__all__ = [
    "MystError", "NotInitialized", "IntegrityError",
    "MystPaths", "Entry", "Option", "Kind", "Status",
    "SemanticItem", "SemanticKind",
    "append_entry", "load_entries", "verify_chain", "supersede_map",
    "SemanticStore", "ProjectProfile",
    "__version__",
]
