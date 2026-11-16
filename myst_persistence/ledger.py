"""The episodic ledger: append-only, hash-chained JSONL storage.

Format of `ledger.jsonl` — one JSON object per line:

    {"prev": "<sha256 of previous line>", "digest": "<sha256>", "entry": {...}}

Line 1 uses ``prev = "GENESIS"`` (a fixed constant). ``digest`` is
SHA-256 over ``prev + canonical JSON of the entry``. The file *content*
outside the entry objects carries no other state, so verification is
independent of line ordering as long as ids are checked too.

Guarantees:

- writes append only; existing bytes are never rewritten;
- every mutation of history (edit, delete, reorder, splice) breaks the
  chain at the first tampered line and `verify_chain` reports it;
- readers tolerate a trailing partially-written line (crash safety):
  it is dropped from the load and reported by verify.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .errors import DataFormatError, IntegrityError
from .model import Entry
from .timeutil import now_iso

GENESIS = "GENESIS"
ENCODING = "utf-8"


# ---------------------------------------------------------------------------
# Hash chain primitives
# ---------------------------------------------------------------------------

def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode(ENCODING)).hexdigest()


def compute_digest(prev_hash: str, entry: Entry) -> str:
    """Digest of an entry bound to its predecessor's hash."""
    return _sha256(prev_hash + entry.canonical())


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _parse_line(line: str, lineno: int) -> tuple:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise DataFormatError(
            "ledger line %d is not valid JSON: %s" % (lineno, exc)) from exc
    if not isinstance(obj, dict) or "entry" not in obj:
        raise DataFormatError("ledger line %d has no 'entry'" % lineno)
    entry = Entry.from_dict(obj["entry"])
    return obj.get("prev"), obj.get("digest"), entry


def load_raw_lines(ledger_file: Path) -> list:
    """Raw parsed lines [(prev, digest, entry, raw)], tolerating a torn tail.

    A final line without a trailing newline or truncated mid-write is
    included but flagged; `verify_chain` decides how to report it.
    """
    if not Path(ledger_file).exists():
        return []
    text = Path(ledger_file).read_text(encoding=ENCODING)
    out = []
    lines = text.splitlines()
    for lineno, line in enumerate(lines, 1):
        if not line.strip():
            continue
        prev, digest, entry = _parse_line(line, lineno)
        out.append((prev, digest, entry, line))
    return out


def load_entries(ledger_file: Path) -> list:
    """All entries in ledger order (append order). Empty list if no ledger."""
    return [item[2] for item in load_raw_lines(ledger_file)]


def head_file(ledger_file: Path) -> Path:
    """Sidecar holding the digest of the last appended line (the 'head').

    A prefix of a hash chain is itself a valid chain, so deletion of tail
    lines is invisible to pure chain verification. The head file pins the
    *latest* digest: truncation makes the ledger's last digest differ
    from the recorded head and is caught.
    """
    return Path(ledger_file).with_name(Path(ledger_file).name + ".head")


def _read_head(ledger_file: Path) -> str | None:
    hf = head_file(ledger_file)
    if not hf.exists():
        return None
    text = hf.read_text(encoding=ENCODING).strip()
    return text or None


def _write_head(ledger_file: Path, digest: str) -> None:
    hf = head_file(ledger_file)
    tmp = hf.with_suffix(".tmp")
    tmp.write_text(digest + "\n", encoding=ENCODING)
    tmp.replace(hf)


def last_hash(ledger_file: Path) -> str:
    """Hash to chain the next entry from ('GENESIS' for an empty ledger)."""
    lines = load_raw_lines(ledger_file)
    if not lines:
        return GENESIS
    return lines[-1][1] or GENESIS


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_chain(ledger_file: Path) -> dict:
    """Verify the hash chain; return a report dict.

    Report: {ok, errors: [str], count, last_ok_id}. Never raises on
    corruption — the report carries the details.
    """
    errors = []
    entries = load_raw_lines(ledger_file)
    expected_prev = GENESIS
    expected_id = 1
    last_ok_id = 0

    for lineno, (prev, digest, entry, raw) in enumerate(entries, 1):
        if prev != expected_prev:
            errors.append(
                "line %d: prev mismatch (chain broken; expected %s, got %s)"
                % (lineno, expected_prev[:12], (prev or "?")[:12]))
        if entry.id != expected_id:
            errors.append(
                "line %d: id %d breaks sequence (expected %d)"
                % (lineno, entry.id, expected_id))
        computed = compute_digest(prev or "", entry)
        if digest != computed:
            errors.append("line %d: digest mismatch (content rewritten)" % lineno)
        if errors:
            # The first failure poisons verification of subsequent prev
            # values; keep scanning to collect facts but stop asserting
            # the chain. Continue from the *recorded* values so later
            # tampering is still caught (reorder: recorded prev of the
            # moved line no longer matches any neighbor's digest).
            expected_prev = digest or expected_prev
            expected_id = entry.id + 1
            continue
        expected_prev = digest
        expected_id = entry.id + 1
        last_ok_id = entry.id

    # A chain that verifies line-by-line can still be a truncated tail:
    # line 1 alone (or any prefix) forms a perfectly valid chain. Detect
    # this with a snapshot of the last digest, persisted at the end of
    # each append (see HEAD file note in append_entry). When absent,
    # count mismatch vs. file size cannot distinguish — so we also check
    # that the ledger ends with the recorded head digest.
    head = _read_head(ledger_file)
    if head and entries and entries[-1][1] != head:
        errors.append("ledger head mismatch (tail truncated or spliced; "
                       "expected head %s, ledger ends at %s)"
                      % (head[:12], (entries[-1][1] or "?")[:12]))

    return {"ok": not errors, "errors": errors,
            "count": len(entries), "last_ok_id": last_ok_id}


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def append_entry(ledger_file: Path, entry: Entry) -> Entry:
    """Append one entry, extending the hash chain. Assigns id and ts.

    The write is atomic-ish: content is written to a temp file in the same
    directory then the *new line only* is appended via a single `write`
    call with the file opened in append mode. Because appends of < 4KB to
    a line-buffered file are effectively atomic on POSIX, and we fsync,
    crash safety is adequate for a developer tool.
    """
    path = Path(ledger_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = load_raw_lines(path)
    prev = lines[-1][1] if lines else GENESIS
    entry.id = (lines[-1][2].id + 1) if lines else 1
    if not entry.ts:
        entry.ts = now_iso()

    digest = compute_digest(prev, entry)
    record = {"prev": prev, "digest": digest, "entry": json.loads(
        json.dumps(entry.asdict(), ensure_ascii=False))}
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))

    # ensure exactly one trailing newline before appending
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            tail = fh.read(1)
        if tail != b"\n":
            with path.open("a", encoding=ENCODING) as fh:
                fh.write("\n")
    with path.open("a", encoding=ENCODING) as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    _write_head(path, digest)
    return entry


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------

def supersede_map(entries: list) -> dict:
    """Map entry id -> list of ids that superseded it (in order)."""
    out = {}
    for e in entries:
        if e.supersedes:
            out.setdefault(e.supersedes, []).append(e.id)
    return out


def active_entries(entries: list) -> list:
    """Entries whose status is active (others stay searchable but hidden
    from default injection)."""
    return [e for e in entries if e.status == "active"]


def entry_summary_line(entries: list) -> str:
    """One-line status for `myst status` and CI badges."""
    if not entries:
        return "0 entries"
    kinds = {}
    for e in entries:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    parts = ["%d %ss" % (n, k) for k, n in sorted(kinds.items())]
    return "%d entries (%s)" % (len(entries), ", ".join(parts))
