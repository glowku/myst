"""Rendering of the injectable state (Markdown / JSON / compact text).

`state.py` (retrieval + budget) produces a *selection*; this module turns a
selection into bytes an LLM (or a human) consumes. All formats are
deterministic: the same inputs always render to the same output, so the
file can be diffed, cached and hash-pinned in CI.
"""

from __future__ import annotations

import json

from .model import Entry


def render_state_markdown(bundle: dict) -> str:
    """Render the full injectable state (the canonical format)."""
    project = bundle["project"]
    generated = bundle["generated"]
    lines = []

    lines.append("# Cognitive state — %s" % (project or "this project"))
    lines.append("")
    lines.append("<!-- myst-persistence v2 state | generated %s | "
                 "est. %d tokens | %d entries selected of %d -->"
                 % (generated, bundle.get("tokens", 0),
                    len(bundle.get("entries", [])), bundle.get("total", 0)))
    lines.append("")

    if bundle.get("objective"):
        lines.append("> Objective: %s" % bundle["objective"])
        lines.append("")

    # -- semantic core first: invariants bind every later choice -------------
    if bundle.get("semantic_md"):
        lines.append(bundle["semantic_md"].rstrip())
        lines.append("")

    if bundle.get("entries"):
        lines.append("## Recent trajectory (most relevant episodes)")
        lines.append("")
        for entry in bundle["entries"]:
            lines.append(entry.render_md())
        lines.append("")

    if bundle.get("stats"):
        s = bundle["stats"]
        lines.append("## Ledger statistics")
        lines.append("")
        lines.append("- total entries: %d" % s.get("total", 0))
        lines.append("- active: %d · superseded/reversed/obsolete: %d"
                    % (s.get("active", 0), s.get("closed", 0)))
        lines.append("- most recent: %s" % (s.get("latest", "—")))
        lines.append("")

    lines.append("<!-- How to use: keep this block in context. When a "
                 "decision is made or rejected, log it with `myst log`. "
                 "Before ending a task, run `myst state` again to refresh. -->")
    lines.append("")
    return "\n".join(lines)


def render_state_compact(bundle: dict) -> str:
    """Ultra-compact plain-text variant for tight budgets.

    Rules compressed to one line each, entries to a single line of
    kind+title+decision. No Markdown syntax — survives any paste target.
    """
    lines = []
    if bundle.get("objective"):
        lines.append("OBJECTIVE: %s" % bundle["objective"])
    for item in bundle.get("semantic_items", []):
        tag = {"invariant": "RULE", "principle": "PRINCIPLE",
               "pattern": "DO", "antipattern": "DONT", "fact": "FACT",
               "glossary": "TERM"}.get(item.kind, item.kind.upper())
        lines.append("%s: %s" % (tag, item.text))
    for entry in bundle.get("entries", []):
        decision = entry.decision or entry.rejection or entry.title
        lines.append("%s #%d: %s — %s"
                     % (entry.kind.upper(), entry.id, entry.title,
                        _oneline(decision)))
    lines.append("(myst state · %d/%d entries · %d tokens)"
                 % (len(bundle.get("entries", [])), bundle.get("total", 0),
                    bundle.get("tokens", 0)))
    return "\n".join(lines)


def render_state_json(bundle: dict) -> str:
    """Machine-readable state: full structured objects, no rendering."""
    data = {
        "project": bundle.get("project"),
        "generated": bundle.get("generated"),
        "objective": bundle.get("objective"),
        "tokens": bundle.get("tokens", 0),
        "total": bundle.get("total", 0),
        "budget": bundle.get("budget"),
        "semantic_items": [i.to_dict() for i in bundle.get("semantic_items", [])],
        "entries": [e.asdict() for e in bundle.get("entries", [])],
        "stats": bundle.get("stats", {}),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _oneline(text: str) -> str:
    return " ".join(text.split())


# ---------------------------------------------------------------------------
# CLI-facing `show` renderer (rich, human, terminal-oriented)
# ---------------------------------------------------------------------------

def render_show(entries: list, semantic: "SemanticStore | None",
                project: str) -> str:
    """`myst show` output: a readable ledger digest."""
    lines = ["%s — cognitive ledger" % (project or "project"), ""]

    if not entries and not (semantic and semantic.items):
        lines.append("(empty — log something with `myst log`)")

    if semantic and semantic.items:
        lines.append(semantic.render_md())
        lines.append("")

    if entries:
        by_status = {}
        for e in entries:
            by_status.setdefault(e.status, []).append(e)
        for status in ("active", "superseded", "reversed", "obsolete"):
            group = by_status.get(status, [])
            if not group:
                continue
            lines.append("## %s (%d)" % (status, len(group)))
            lines.append("")
            for e in group:
                marker = ""
                if e.pinned:
                    marker += " 📌"
                lines.append("- #%d %s — %s%s"
                             % (e.id, e.kind, e.title, marker))
                if e.decision:
                    lines.append("    decision: %s" % _oneline(e.decision))
                if e.rejection:
                    lines.append("    rejected: %s" % _oneline(e.rejection))
                if e.supersedes:
                    lines.append("    supersedes: #%d" % e.supersedes)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
