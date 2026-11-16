"""Consolidation: distill episodic episodes into semantic memory.

Two processes, mirroring complementary learning systems:

1. **prune** — episodic entries decay in retrieval value; once an entry
   is older than `prune_after` days, has no pinned flag, is superseded
   or obsolete, and its topic is cold, it is *archived* (moved out of
   the live ledger file into `archive.jsonl`, chain restarted). The
   episode is not deleted — it moves to cold storage; the hash chain
   stays verifiable via the head sidecar.

2. **distill** — patterns that recur across `>= threshold` distinct
   episodic entries (same tag cluster or similar decision text) are
   proposed as semantic items, with provenance = source entry ids. The
   proposals are *written into the store as unpinned draft items with
   `kind=principle`* only when `--apply` is passed; otherwise printed
   for review. Distillation never overwrites an existing item: it
   merges provenance instead (semantic memory is conservative).

Resurrection rule: if an archived entry's topic becomes hot again
(tag frequency over recent horizon), it is copied back into the live
ledger — spaced-retrieval style (re-learn before full forgetting).
"""

from __future__ import annotations

from pathlib import Path

from .errors import MystError
from .model import Entry, SemanticItem, SemanticKind
from .paths import MystPaths
from .retrieval import topic_frequencies
from .timeutil import now, parse_ts, days_between, now_iso


class ConsolidateError(MystError):
    pass


ARCHIVE_NAME = "archive.jsonl"


def archive_file(paths: MystPaths) -> Path:
    return paths.layer / ARCHIVE_NAME


def prune(paths: MystPaths, entries: list, prune_after: float = 365.0,
          hot_horizon: int = 60) -> dict:
    """Move dead-cold entries to archive.jsonl. Returns a report.

    An entry is prunable when ALL of:
      - older than `prune_after` days;
      - status in (superseded, reversed, obsolete) — active decisions
        stay in the live ledger even when old (they still bind behavior);
      - not pinned;
      - no hot tags (tags with recent frequency > 0.15).
    """
    from . import ledger as _ledger  # late import: state functions need paths

    reference = now()
    freqs = topic_frequencies(entries, horizon=hot_horizon)
    keep, prune_ids = [], []
    for e in entries:
        try:
            age = days_between(parse_ts(e.ts), reference)
        except ValueError:
            keep.append(e)
            continue
        hot = any(freqs.get(t, 0.0) > 0.15 for t in e.tags)
        prunable = (
            age > prune_after
            and e.status in ("superseded", "reversed", "obsolete")
            and not e.pinned
            and not hot
        )
        if prunable:
            prune_ids.append(e.id)
        else:
            keep.append(e)

    if not prune_ids:
        return {"pruned": [], "kept": len(keep), "archive": str(archive_file(paths))}

    # Rewrite live ledger with kept entries as a fresh chain, and append
    # pruned entries to the archive (also a hash chain, GENESIS-headed).
    _rewrite_ledger(paths.ledger_file, keep)
    with archive_file(paths).open("a", encoding="utf-8") as fh:
        for e in entries:
            if e.id in prune_ids:
                fh.write(_entry_line(e) + "\n")
    _ledger._write_head(paths.ledger_file, _last_digest_of(paths.ledger_file))
    return {"pruned": prune_ids, "kept": len(keep),
            "archive": str(archive_file(paths))}


def resurrect(paths: MystPaths, live_entries: list,
              hot_threshold: float = 0.25, horizon: int = 60) -> list:
    """Return archived entry ids whose topics became hot again, and copy
    them back into the live ledger (spaced retrieval)."""
    from . import ledger as _ledger

    if not archive_file(paths).exists():
        return []
    freqs = topic_frequencies(live_entries, horizon=horizon)
    hot = {t for t, f in freqs.items() if f >= hot_threshold}
    if not hot:
        return []

    import json
    archived = []
    text = archive_file(paths).read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip():
            archived.append(Entry.from_dict(json.loads(line)["entry"]))
    # keep archive order (ids chronological)

    revived = []
    live_ids = {e.id for e in live_entries}
    live_titles = {e.title.strip().lower() for e in live_entries}
    for e in archived:
        if not any(t in hot for t in e.tags):
            continue
        if e.id in live_ids:          # id collision: skip, provenance kept
            continue
        if e.title.strip().lower() in live_titles:  # already re-logged
            continue
        copy = Entry.from_dict(e.asdict())
        copy.pinned = False
        _ledger.append_entry(paths.ledger_file, copy)
        live_ids.add(copy.id)
        revived.append(copy.id)
    return revived


def distill(entries: list, threshold: int = 3) -> list:
    """Propose semantic items from recurring episodic patterns.

    A pattern = a tag shared by >= threshold distinct entries with
    decision text; the proposal text is the most recent entry's
    decision (the latest formulation), rationale summarizes count and
    span. Proposals are returned, not applied — `--apply` in the CLI
    adds them as `kind=principle`, `pinned=False` drafts with
    provenance. Duplicate ids merge provenance only.
    """
    by_tag = {}
    for e in entries:
        if e.kind not in ("decision", "rejection", "insight"):
            continue
        for t in e.tags:
            by_tag.setdefault(t, []).append(e)

    proposals = []
    for tag, group in sorted(by_tag.items()):
        if len(group) < threshold:
            continue
        decided = [e for e in group if e.decision]
        if not decided:
            continue
        latest = max(decided, key=lambda e: (e.ts, e.id))
        ids = sorted(e.id for e in group)
        proposals.append(SemanticItem(
            id="pattern-%s" % SemanticItem.slugify(tag),
            kind=SemanticKind.PRINCIPLE,
            text="Recurring theme '%s': %s" % (tag, _oneline(latest.decision)),
            rationale="%d entries across #%d–#%d treat this tag; latest "
                      "formulation #%d" % (len(group), ids[0], ids[-1], latest.id),
            tags=[tag],
            pinned=False,
            weight=1.0 + 0.1 * min(len(group), 10),
            provenance=ids,
            ts=now_iso(),
        ))
    return proposals


def apply_proposals(store, proposals: list) -> dict:
    """Add proposals to the semantic store (merge provenance on duplicate)."""
    added, merged = 0, 0
    for prop in proposals:
        existing = store.get(prop.id)
        if existing:
            existing.provenance = sorted(set(existing.provenance)
                                          | set(prop.provenance))
            merged += 1
        else:
            store.add(prop)
            added += 1
    return {"added": added, "merged": merged}


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------

def _rewrite_ledger(ledger_path: Path, entries: list) -> None:
    """Rewrite the live ledger with `entries` as a fresh chain (preserve ids)."""
    import json
    from . import ledger as _ledger

    prev = _ledger.GENESIS
    lines = []
    for e in entries:
        digest = _ledger.compute_digest(prev, e)
        record = {"prev": prev, "digest": digest,
                  "entry": json.loads(json.dumps(e.asdict(), ensure_ascii=False))}
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        prev = digest
    tmp = Path(ledger_path).with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(ledger_path)


def _entry_line(entry: Entry) -> str:
    import json
    return json.dumps({"entry": json.loads(json.dumps(entry.asdict(),
                                                      ensure_ascii=False))},
                      ensure_ascii=False, separators=(",", ":"))


def _last_digest_of(ledger_path: Path) -> str:
    from . import ledger as _ledger
    lines = _ledger.load_raw_lines(ledger_path)
    return lines[-1][1] if lines else _ledger.GENESIS


def _oneline(text: str) -> str:
    return " ".join(text.split())
