"""Data model: episodic entries (ADR-grade) and semantic items.

One episodic entry = one decision event. Serialized as one JSON line in
`ledger.jsonl`. The line carries a `prev` field: SHA-256 of the previous
line's canonical bytes. Entry N's own digest is SHA-256 over (prev + canonical
JSON of entry N). Tampering with any line breaks every later digest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from .timeutil import now_iso

# ---------------------------------------------------------------------------
# Enumerations (kept as plain string constants for JSON friendliness)
# ---------------------------------------------------------------------------

class Kind:
    """Taxonomy of episodic events."""

    DECISION = "decision"
    REJECTION = "rejection"
    INSIGHT = "insight"
    RISK = "risk"
    EVENT = "event"

    ALL = (DECISION, REJECTION, INSIGHT, RISK, EVENT)

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.ALL


class Status:
    """Lifecycle of a decision entry."""

    ACTIVE = "active"          # currently in force
    SUPERSEDED = "superseded"  # replaced by a later entry (link kept)
    REVERSED = "reversed"      # abandoned, went back to previous state
    OBSOLETE = "obsolete"      # context vanished (dep removed, spec dropped)

    ALL = (ACTIVE, SUPERSEDED, REVERSED, OBSOLETE)

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls.ALL


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

@dataclass
class Option:
    """One option considered for a decision — including rejected ones.

    The rejection reason is the core of Myst: the signature of thinking is
    *why the other paths were discarded*, not only what was chosen.
    """

    name: str
    chosen: bool = False
    reason: str = ""           # why chosen / why rejected
    detail: str = ""            # optional longer notes

    def to_dict(self) -> dict:
        return {"name": self.name, "chosen": self.chosen,
                "reason": self.reason, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict) -> "Option":
        return cls(
            name=str(data.get("name", "")),
            chosen=bool(data.get("chosen", False)),
            reason=str(data.get("reason", "")),
            detail=str(data.get("detail", "")),
        )


# ---------------------------------------------------------------------------
# Episodic entry
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    """One episodic memory node (an ADR, a rejection, an insight, a risk...).

    Serialized to one JSON line. Immutable by convention: the ledger appends,
    never rewrites. Lifecycle changes are new entries linked via `supersedes`.
    """

    id: int = 0                      # 1-based sequence number, dense
    ts: str = ""                     # ISO-8601 UTC
    kind: str = Kind.DECISION
    title: str = ""
    context: str = ""                # forces at play when deciding
    options: list[Option] = field(default_factory=list)
    decision: str = ""               # what was decided (rejection → what & why)
    rejection: str = ""              # why a path was discarded (kind=rejection)
    consequences: str = ""           # expected / observed consequences
    tags: list[str] = field(default_factory=list)
    status: str = Status.ACTIVE
    supersedes: int | None = None    # id of the entry this one replaces
    pinned: bool = False             # always included in injected state
    confidence: float = 0.0          # 0..1, author's self-assessed confidence
    meta: dict[str, Any] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def create(cls, **kwargs) -> "Entry":
        """Build an entry with defaults filled (ts, kind, status)."""
        entry = cls()
        entry.ts = now_iso()
        entry.kind = Kind.DECISION
        entry.status = Status.ACTIVE
        for key, value in kwargs.items():
            if not hasattr(entry, key):
                raise TypeError("unknown Entry field: %r" % key)
            setattr(entry, key, value)
        entry._validate()
        return entry

    def _validate(self) -> None:
        if not self.title:
            raise ValueError("entry needs a title")
        if not Kind.is_valid(self.kind):
            raise ValueError("unknown kind: %r" % self.kind)
        if not Status.is_valid(self.status):
            raise ValueError("unknown status: %r" % self.status)
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be in [0, 1]")
        if self.id < 0:
            raise ValueError("id must be >= 0")

    # -- serialization ------------------------------------------------------

    def canonical(self) -> str:
        """Canonical JSON: compact, stable key order (versioned schema)."""
        data = {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "context": self.context,
            "options": [o.to_dict() for o in self.options],
            "decision": self.decision,
            "rejection": self.rejection,
            "consequences": self.consequences,
            "tags": list(self.tags),
            "pinned": self.pinned,
            "confidence": round(float(self.confidence), 3),
            "supersedes": self.supersedes,
            "meta": self.meta,
        }
        return json.dumps(data, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: dict) -> "Entry":
        entry = cls(
            id=int(data.get("id", 0)),
            ts=str(data.get("ts", "")),
            kind=str(data.get("kind", Kind.DECISION)),
            title=str(data.get("title", "")),
            context=str(data.get("context", "")),
            options=[Option.from_dict(o) for o in data.get("options", []) or []],
            decision=str(data.get("decision", "")),
            rejection=str(data.get("rejection", "")),
            consequences=str(data.get("consequences", "")),
            tags=[str(t) for t in data.get("tags", []) or []],
            status=str(data.get("status", Status.ACTIVE)),
            supersedes=data.get("supersedes"),
            pinned=bool(data.get("pinned", False)),
            confidence=float(data.get("confidence", 0.0)),
            meta=dict(data.get("meta", {}) or {}),
        )
        return entry

    def summary(self) -> str:
        """One-line human summary for `show` and hook output."""
        bits = ["#%d" % self.id, self.kind, self.status, self.title]
        if self.pinned:
            bits.append("(pinned)")
        return " ".join(b for b in bits if b)

    # -- rendering to Markdown (used by state injection and show) -----------

    def render_md(self) -> str:
        """Full ADR-grade Markdown rendering of this entry."""
        out = ["#### %s — %s" % (self._kind_label(), self.title)]
        out.append("")
        meta_bits = ["`%s`" % self.ts]
        if self.tags:
            meta_bits.append("tags: " + ", ".join("`%s`" % t for t in self.tags))
        if self.supersedes:
            meta_bits.append("supersedes `#%d`" % self.supersedes)
        out.append("*%s*" % " · ".join(meta_bits))
        out.append("")
        if self.context:
            out.append("**Context** — %s" % self.context)
            out.append("")
        if self.options:
            out.append("**Options considered**:")
            out.append("")
            for opt in self.options:
                mark = "✓" if opt.chosen else "✗"
                reason = (" — %s" % opt.reason) if opt.reason else ""
                out.append("- %s **%s**%s" % (mark, opt.name, reason))
            out.append("")
        if self.decision:
            out.append("**Decision** — %s" % self.decision)
            out.append("")
        if self.rejection:
            out.append("**Rejected because** — %s" % self.rejection)
            out.append("")
        if self.consequences:
            out.append("**Consequences** — %s" % self.consequences)
            out.append("")
        return "\n".join(out).rstrip() + "\n"

    def _kind_label(self) -> str:
        return {
            Kind.DECISION: "Decision",
            Kind.REJECTION: "Rejection",
            Kind.INSIGHT: "Insight",
            Kind.RISK: "Risk",
            Kind.EVENT: "Event",
        }.get(self.kind, self.kind)

    def status_label(self) -> str:
        return {
            Status.ACTIVE: "active",
            Status.SUPERSEDED: "superseded",
            Status.REVERSED: "reversed",
            Status.OBSOLETE: "obsolete",
        }.get(self.status, self.status)

    def asdict(self) -> dict:
        d = asdict(self)
        d["options"] = [o.to_dict() for o in self.options]
        return d


# ---------------------------------------------------------------------------
# Semantic memory
# ---------------------------------------------------------------------------

class SemanticKind:
    """Taxonomy of semantic memory items."""

    INVARIANT = "invariant"    # hard rule: violations are defects
    PRINCIPLE = "principle"    # soft guideline
    PATTERN = "pattern"        # recurring solution (do)
    ANTIPATTERN = "antipattern"  # recurring trap (don't)
    FACT = "fact"              # distilled domain fact
    GLOSSARY = "glossary"      # project vocabulary

    ALL = (INVARIANT, PRINCIPLE, PATTERN, ANTIPATTERN, FACT, GLOSSARY)


@dataclass
class SemanticItem:
    """One curated piece of long-term knowledge.

    Episodic entries are what happened; semantic items are what is true.
    Consolidation moves knowledge from episodes to semantic items (with
    provenance back-links to the source entries).
    """

    id: str = ""                    # stable slug, e.g. "prefer-composition"
    kind: str = SemanticKind.INVARIANT
    text: str = ""                  # the statement itself
    rationale: str = ""             # why it exists (provenance)
    tags: list[str] = field(default_factory=list)
    pinned: bool = True             # invariants default to pinned
    weight: float = 1.0              # relative importance for budget fights
    provenance: list[int] = field(default_factory=list)  # source entry ids
    ts: str = ""                    # created/last touched

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "text": self.text,
            "rationale": self.rationale, "tags": list(self.tags),
            "pinned": self.pinned, "weight": float(self.weight),
            "provenance": list(self.provenance), "ts": self.ts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SemanticItem":
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", SemanticKind.INVARIANT)),
            text=str(data.get("text", "")),
            rationale=str(data.get("rationale", "")),
            tags=[str(t) for t in data.get("tags", []) or []],
            pinned=bool(data.get("pinned", True)),
            weight=float(data.get("weight", 1.0)),
            provenance=[int(p) for p in data.get("provenance", []) or []],
            ts=str(data.get("ts", "")),
        )

    def validate(self) -> None:
        if not self.id:
            raise ValueError("semantic item needs an id")
        if not self.text:
            raise ValueError("semantic item needs text")
        if self.kind not in SemanticKind.ALL:
            raise ValueError("unknown semantic kind: %r" % self.kind)
        if not (0.0 <= self.weight <= 10.0):
            raise ValueError("weight must be in [0, 10]")

    @staticmethod
    def slugify(text: str) -> str:
        """Derive a stable id from text (used when consolidating)."""
        import re as _re
        slug = _re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return (slug[:48].rstrip("-")) or "item"

    def render_md(self) -> str:
        head = "- **%s**" % self.text
        tail = []
        if self.rationale:
            tail.append(self.rationale)
        if self.provenance:
            tail.append("provenance: " + ", ".join("#%d" % p for p in self.provenance))
        if tail:
            return head + " — *%s*" % "; ".join(tail)
        return head
