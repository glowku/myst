"""Semantic store: curated long-term memory in TOML + Markdown files.

Two representations, kept in sync by code:

- ``semantic.toml`` — the machine-readable index (one ``[[item]]`` array
  of tables). This is the source of truth for ids and metadata.
- ``semantic.d/<id>.md`` — one human-readable file per item (large items,
  rich text). Written for *reading* with `less`; never parsed back.

Design decisions (deliberate):

- TOML, not YAML: stdlib-parsed on Python 3.11+ (``tomllib``), no
  dependency, no surprising type inference (YAML's Norway problem:
  ``no`` → false). We ship a micro-parser for 3.9/3.10.
- One file per item in ``semantic.d/`` mirrors Nygard ADR practice:
  decisions live as small standalone documents.
- Semantic items carry provenance: ids of the episodic entries they were
  distilled from. Nothing appears in semantic memory without a source.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import DataFormatError
from .model import SemanticItem, SemanticKind
from .timeutil import now_iso


KIND_ORDER = (SemanticKind.INVARIANT, SemanticKind.PRINCIPLE,
              SemanticKind.PATTERN, SemanticKind.ANTIPATTERN,
              SemanticKind.FACT, SemanticKind.GLOSSARY)

_KIND_LABEL = {
    SemanticKind.INVARIANT: "Invariants",
    SemanticKind.PRINCIPLE: "Principles",
    SemanticKind.PATTERN: "Patterns",
    SemanticKind.ANTIPATTERN: "Anti-patterns",
    SemanticKind.FACT: "Facts",
    SemanticKind.GLOSSARY: "Glossary",
}


class SemanticStore:
    """The curated semantic memory of one project."""

    def __init__(self, items=None):
        self.items: dict[str, SemanticItem] = {}
        if items:
            for item in items:
                self.items[item.id] = item

    # -- queries -------------------------------------------------------------

    def get(self, item_id: str) -> SemanticItem | None:
        return self.items.get(item_id)

    def all(self) -> list:
        """Items ordered by kind then id for stable rendering."""
        return sorted(self.items.values(),
                      key=lambda i: (KIND_ORDER.index(i.kind), i.id))

    def by_kind(self, kind: str) -> list:
        return [i for i in self.all() if i.kind == kind]

    def pinned(self) -> list:
        return [i for i in self.all() if i.pinned]

    def search(self, query: str) -> list:
        """Case-insensitive substring search over text and rationale."""
        q = query.lower()
        return [i for i in self.all()
                if q in i.text.lower() or q in i.rationale.lower()]

    # -- mutation -------------------------------------------------------------

    def add(self, item: SemanticItem, replace=False) -> SemanticItem:
        item.validate()
        if item.id in self.items and not replace:
            raise ValueError("duplicate semantic id: %r (use replace=True "
                             "or a different id)" % item.id)
        if not item.ts:
            item.ts = now_iso()
        self.items[item.id] = item
        return item

    def remove(self, item_id: str) -> SemanticItem | None:
        return self.items.pop(item_id, None)

    # -- TOML serialization ----------------------------------------------------

    def to_toml(self) -> str:
        out = ["# Semantic memory — curated items distilled from the ledger.",
               "# Hand-editable; keep ids stable once committed.",
               ""]
        if not self.items:
            out.append("# (no semantic items yet)")
            return "\n".join(out) + "\n"
        for item in self.all():
            out.append("[[item]]")
            out.append('id = "%s"' % _esc(item.id))
            out.append('kind = "%s"' % _esc(item.kind))
            out.append('text = "%s"' % _esc(item.text))
            out.append('rationale = "%s"' % _esc(item.rationale))
            out.append("pinned = %s" % ("true" if item.pinned else "false"))
            out.append("weight = %g" % item.weight)
            if item.tags:
                tags = ", ".join('"%s"' % _esc(t) for t in item.tags)
                out.append("tags = [%s]" % tags)
            if item.provenance:
                prov = ", ".join(str(p) for p in item.provenance)
                out.append("provenance = [%s]" % prov)
            out.append('ts = "%s"' % _esc(item.ts or now_iso()))
            out.append("")
        return "\n".join(out) + "\n"

    @classmethod
    def from_toml(cls, text: str) -> "SemanticStore":
        try:
            data = _parse_toml_items(text)
        except ValueError as exc:
            raise DataFormatError("semantic.toml: %s" % exc) from exc
        store = cls()
        for raw in data:
            store.add(SemanticItem.from_dict(raw), replace=True)
        return store

    # -- persistence ------------------------------------------------------------

    def save(self, index_path: Path, docs_dir: Path) -> None:
        """Write semantic.toml + one .md doc per item (atomic replace)."""
        index_path = Path(index_path)
        docs_dir = Path(docs_dir)
        index_path.parent.mkdir(parents=True, exist_ok=True)
        docs_dir.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(".toml.tmp")
        tmp.write_text(self.to_toml(), encoding="utf-8")
        tmp.replace(index_path)
        # doc per item
        existing = {p.stem: p for p in docs_dir.glob("*.md")}
        for item in self.items.values():
            doc = docs_dir / (item.id + ".md")
            doc.write_text(self._render_doc(item), encoding="utf-8")
            existing.pop(item.id, None)
        # docs of removed items are deleted (store is source of truth)
        for stale in existing.values():
            stale.unlink()

    @classmethod
    def load(cls, index_path: Path) -> "SemanticStore":
        p = Path(index_path)
        if not p.exists():
            return cls()
        return cls.from_toml(p.read_text(encoding="utf-8"))

    def _render_doc(self, item: SemanticItem) -> str:
        lines = ["<!-- semantic id: %s | kind: %s -->" % (item.id, item.kind),
                 "# %s" % item.text, ""]
        if item.rationale:
            lines.append(item.rationale)
            lines.append("")
        if item.provenance:
            refs = ", ".join("#%d" % p for p in item.provenance)
            lines.append("*Provenance: %s*" % refs)
            lines.append("")
        meta = ["kind: %s" % item.kind]
        if item.tags:
            meta.append("tags: %s" % ", ".join(item.tags))
        meta.append("pinned: %s" % ("yes" if item.pinned else "no"))
        meta.append("weight: %g" % item.weight)
        lines.append("<!-- " + " | ".join(meta) + " -->")
        return "\n".join(lines) + "\n"

    # -- Markdown rendering (for injection) --------------------------------------

    def render_md(self, kinds=None) -> str:
        sections = []
        for kind in KIND_ORDER:
            if kinds and kind not in kinds:
                continue
            items = self.by_kind(kind)
            if not items:
                continue
            body = ["### %s" % _KIND_LABEL[kind], ""]
            for item in items:
                body.append(item.render_md())
            body.append("")
            sections.append("\n".join(body))
        return "\n".join(sections)


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# ---------------------------------------------------------------------------
# TOML item parsing — [[item]] arrays. tomllib first, micro-parser fallback.
# ---------------------------------------------------------------------------

def _parse_toml_items(text: str) -> list:
    try:
        import tomllib
        data = tomllib.loads(text)
        items = data.get("item", [])
        if not isinstance(items, list):
            raise ValueError("'item' must be an array of tables")
        return items
    except ImportError:
        pass

    # micro-parser: top-level scalars ignored, [[item]] blocks parsed
    items, current, header = [], None, None
    for no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[[item]]"):
            current, header = {}, line
            items.append(current)
            continue
        if line.startswith("[") and line.endswith("]"):
            current = None  # unknown table — skip its content
            continue
        if current is None:
            continue
        m = re.match(r'^([A-Za-z0-9_-]+)\s*=\s*(.+?)\s*(?:#.*)?$', line)
        if not m:
            raise ValueError("unparseable line %d: %r" % (no, raw))
        key, value = m.group(1), m.group(2)
        current[key] = _parse_toml_value(value)
    return items


def _parse_toml_value(text: str):
    t = text.strip()
    if t.startswith('"'):
        if not (t.endswith('"') and len(t) >= 2):
            raise ValueError("unterminated string: %r" % t)
        return t[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if t in ("true", "false"):
        return t == "true"
    if t.startswith("[") and t.endswith("]"):
        inner = t[1:-1].strip()
        if not inner:
            return []
        parts, buf, in_str, depth = [], [], False, 0
        for ch in inner:
            if ch == '"':
                in_str = not in_str
            if ch == "," and not in_str and depth == 0:
                parts.append("".join(buf).strip())
                buf = []
                continue
            if not in_str and ch == "[":
                depth += 1
            if not in_str and ch == "]":
                depth -= 1
            buf.append(ch)
        parts.append("".join(buf).strip())
        return [_parse_toml_value(p) for p in parts if p]
    if re.fullmatch(r"-?\d+", t):
        return int(t)
    if re.fullmatch(r"-?\d+\.\d*", t):
        return float(t)
    raise ValueError("unsupported TOML value: %r" % t)
