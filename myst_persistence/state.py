"""State generation: budgeted assembly of the injectable cognitive state.

Pipeline (pure function of (ledger, semantic, profile, options)):

    1. score entries (retrieval module) and semantic items;
    2. reserve budget sections: header, semantic core, trajectory, stats;
    3. fill trajectory with best-scoring entries until the budget is
       exhausted — whole entries preferred, tight-budget fallback to a
       one-line summary per entry, hard truncate as last resort;
    4. render into the requested format (markdown / compact / json).

Budget math uses the token *estimate* module (chars/3.6). The estimator
is deliberately approximate; the contract is that the generated state
never *claims* more tokens than the user's budget (10% safety margin on
the section accounting). When a single invariant would blow the budget,
it is truncated with a visible marker — never silently dropped.
"""

from __future__ import annotations

from .errors import MystError
from .model import Entry, Kind, SemanticItem
from .profile import ProjectProfile
from .retrieval import score_entries
from .render import render_state_markdown, render_state_compact, render_state_json
from .timeutil import now_iso, now
from .tokens import estimate_tokens, clamp_to_budget, BUDGET_SAFETY_MARGIN

FORMALS = ("markdown", "compact", "json")

HEADER_TOKENS = 60       # title + generation header
STATS_TOKENS = 60        # ledger statistics footer
OVERHEAD_TOKENS = 40     # section headings, separators, usage note

MAX_TRACKED_SELECTED = 50   # never inject more than this many entries


class StateError(MystError):
    pass


def build_state(entries: list, semantic_store, profile: ProjectProfile,
                budget: int = 2000, focus: str = "", fmt: str = "markdown",
                include_closed: bool = False,
                max_entries: int = 25) -> dict:
    """Assemble the injectable bundle. Returns the bundle dict (see render)."""
    if fmt not in FORMALS:
        raise StateError("unknown format: %r (use %s)" % (fmt, ", ".join(FORMALS)))

    # 1. select the semantic core: pinned first, then best weight ———
    semantic_items = semantic_store.all() if semantic_store else []
    pinned = [i for i in semantic_items if i.pinned]
    extra = [i for i in semantic_items if not i.pinned]
    extra.sort(key=lambda i: (-i.weight, i.id))
    semantic_sel = pinned + extra

    # 2. score the trajectory
    usable = [e for e in entries if include_closed or e.status == "active"]
    scored = score_entries(usable, profile.retrieval, focus=focus)
    top = scored[:max(0, min(max_entries, MAX_TRACKED_SELECTED))]

    # 3. budget accounting
    effective = max(120, int(budget * (1.0 - BUDGET_SAFETY_MARGIN)))
    remaining = effective - HEADER_TOKENS - STATS_TOKENS - OVERHEAD_TOKENS

    semantic_md = _render_semantic(semantic_sel)
    remaining -= estimate_tokens(semantic_md)

    selected, dropped_full = [], []
    for entry, score, reason in top:
        if remaining <= 30:
            dropped_full.append(entry)
            continue
        body = entry.render_md()
        cost = estimate_tokens(body)
        if cost <= remaining:
            selected.append((entry, reason, body))
            remaining -= cost
        elif estimate_tokens(_summary_line(entry)) <= remaining:
            # demote to summary line
            selected.append((entry, reason, _summary_line(entry)))
            remaining -= estimate_tokens(_summary_line(entry))
        else:
            clamped = clamp_to_budget(body, max(40, remaining))
            selected.append((entry, reason, clamped))
            remaining = 0

    # 4. bundle
    stats = _stats(entries)
    bundle = {
        "project": profile.name,
        "generated": now_iso(),
        "objective": focus or "",
        "budget": budget,
        "tokens": 0,  # computed after render
        "total": len(entries),
        "semantic_items": semantic_sel,
        "semantic_md": semantic_md,
        "entries": [e for e, _, _ in selected],
        "reasons": {e.id: r for e, r, _ in selected},
        "bodies": {e.id: b for e, _, b in selected},
        "stats": stats,
        "dropped": [e.id for e in dropped_full],
    }
    if fmt == "markdown":
        text = render_state_markdown(bundle)
    elif fmt == "compact":
        text = render_state_compact(bundle)
    else:
        text = render_state_json(bundle)
    bundle["text"] = text
    bundle["tokens"] = estimate_tokens(text)
    return bundle


def _render_semantic(items: list) -> str:
    if not items:
        return ""
    from .semantic import SemanticStore  # local import: avoid cycle at module load
    tmp = SemanticStore(items)
    return tmp.render_md()


def _summary_line(entry: Entry) -> str:
    what = entry.decision or entry.rejection or entry.title
    return "#### %s #%d — %s: %s\n" % (
        entry._kind_label(), entry.id, entry.title, " ".join(what.split()))


def _stats(entries: list) -> dict:
    active = sum(1 for e in entries if e.status == "active")
    latest = entries[-1].ts[:10] if entries else ""
    return {
        "total": len(entries),
        "active": active,
        "closed": len(entries) - active,
        "latest": latest or "—",
        "rejections": sum(1 for e in entries if e.kind == Kind.REJECTION),
    }


# ---------------------------------------------------------------------------
# Write-through helper used by the CLI
# ---------------------------------------------------------------------------

def generate_and_save(paths, profile: ProjectProfile, entries: list,
                      semantic_store, fmt: str = "markdown",
                      focus: str = "", budget: int | None = None,
                      name: str = "current") -> dict:
    """Build the state and persist it under .myst/state/<name>.md.

    Returns the bundle (with the saved path inside).
    """
    b = budget if budget is not None else profile.retrieval.default_budget
    bundle = build_state(entries, semantic_store, profile,
                         budget=b, focus=focus, fmt=fmt)
    ext = "md" if fmt in ("markdown", "compact") else "json"
    path = paths.state_file(name).with_suffix("." + ext)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(bundle["text"], encoding="utf-8")
    bundle["path"] = str(path)
    return bundle
