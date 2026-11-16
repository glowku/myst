# Myst Persistence

**Universal cognitive persistence layer for AI agents — any agent, any project.**

Most tools remember *what* you decided. Almost none remember *why you rejected
the other options*. Myst keeps both, and turns them into an injectable state
that survives session boundaries, model switches and team handovers.

> A small local layer (`.myst/`) that stores your invariants and decision
> trajectory, then injects a compressed state into any model — ChatGPT, Claude,
> Cursor, local LLMs, whatever you use. No cloud. No framework. **Zero runtime
> dependencies.** Project-local: one `.myst/` per repository.

---

## Quick start

### Option A — pip package (recommended)

```bash
pip install .            # from this repo, or pip install myst-persistence
myst init
myst log "Rejected pure RAG — loses the reasoning behind architecture choices" --kind rejection
myst log "Going with explicit trajectory nodes + stable invariants" --kind decision
myst state
```

### Option B — single file, no install

Drop `myst_standalone.py` into any project. Python 3.9+, nothing else.

```bash
python myst_standalone.py init
python myst_standalone.py log "..." --kind decision
python myst_standalone.py state --budget 1500
```

Regenerate the standalone after editing the package:
`python tools/build_standalone.py`

### Option C — MCP server (Claude, Cursor, any MCP client)

```json
{
  "mcpServers": {
    "myst": {
      "command": "myst",
      "args": ["server", "mcp"]
    }
  }
}
```

The agent then gets `myst_log`, `myst_state`, `myst_show`, `myst_verify`,
`myst_consolidate`, `myst_doctor`, `myst_status` as first-class tools.

---

## Commands

```
myst init                       create the .myst/ layer here
myst log TEXT [options]         append an episode (decision/rejection/insight/risk/event)
myst show [--kind --status --query]   inspect ledger + semantic memory
myst state [--budget N --focus "..."]  generate injectable state (token-budgeted)
myst verify                     hash-chain integrity check
myst consolidate [--apply]      distill recurring patterns → semantic memory
myst export [FILE]              everything as JSON (backup / diff / audit)
myst import FILE [--mode merge|replace]
myst doctor                     health check of the layer
myst status                     one-line summary (shell prompts, CI)
myst migrate v1                 import a v1 .myst/ layer, non-destructively
myst hook post-commit|pre-push  git integration bridge
myst agent-file [--target AGENTS.md]  write agent rules for this repo
myst server mcp                 run the MCP stdio server
```

`log` options: `--kind`, `--context`, `--decision`, `--rejection`,
`--consequences`, `--options "name=reason|chosen-name*|other=reason"`,
`--tags a,b`, `--supersedes ID`, `--pinned`, `--confidence 0..1`, `--status`.

Exit codes: `0` ok · `1` usage/runtime error · `2` integrity failure ·
`3` data-format error.

---

## The data model (30 seconds)

Two stores, one distinction — what *happened* vs what is *true*:

| | Episodic ledger (`ledger.jsonl`) | Semantic store (`semantic.toml`) |
|---|---|---|
| holds | every decision, rejection, insight, risk, event | invariants, principles, patterns, anti-patterns, facts |
| write speed | instant, append-only | reviewed, curated |
| truth level | verbatim record | distilled rule with provenance |
| integrity | hash-chained (SHA-256) | human-editable TOML |
| decays? | yes — retrieval-scored | no — pinned or weight-ranked |

Every ledger entry is ADR-grade (Nygard schema): context, options considered
(✓/✗ with reasons), decision, consequences — **including why the alternatives
were rejected**, which is the actual signature of how you think.

The state injector ranks entries by a retrieval score (recency decay,
topic frequency, pin flag, kind bias, focus match), packs the best ones into
a **token budget** you set, and renders Markdown / compact / JSON. Invariants
always ride first — they bind every future choice.

Consolidation mirrors memory research: episodes older than a year that are
closed, cold and unpinned are archived (not deleted); patterns recurring
across ≥3 entries are proposed as semantic items *with provenance links*;
hot topics can resurrect archived episodes before they're fully forgotten.

Full theoretical grounding: **[THEORY.md](THEORY.md)** — complementary
learning systems, episodic/semantic memory, Ebbinghaus decay, spaced
retrieval, ADRs, tamper-evident logs, and how each maps to a design decision.

---

## Layout

```
.myst/
  myst.toml            project profile + retrieval tuning (hand-editable)
  ledger.jsonl         append-only episodic memory, hash-chained
  ledger.jsonl.head    latest digest (detects tail truncation)
  semantic.toml        curated semantic memory (index)
  semantic.d/*.md      one human-readable doc per item
  state/current.md     generated injectable state (gitignored)
  backups/             copies before destructive ops
  archive.jsonl        cold storage after prune
```

Everything is plain text. `less .myst/ledger.jsonl` is a legitimate audit.

---

## Integrity model

Each ledger line is `{"prev": <hash of previous line>, "digest": <sha256 of
prev + entry>, "entry": {...}}`. Line 1 chains from the constant `GENESIS`.
`myst verify` detects:

- **rewriting** — digest no longer matches content;
- **reordering** — prev links no longer chain;
- **tail truncation** — the `.head` sidecar pins the last digest, so any
  prefix that doesn't end there fails;
- **splicing** — a fresh internally-consistent chain still fails the head
  check (and, in a git repo, the diff).

Known limit: a full rewrite *including a new head file* is indistinguishable
from legitimate recovery from backup — by design, `import --replace` makes
a backup first and tells you where it is. The chain is tamper-*evident*,
not tamper-*proof* against an attacker who controls the whole directory.

---

## Agent integration

### AGENTS.md / CLAUDE.md rule set

```bash
myst agent-file          # writes AGENTS.md rules for any coding agent
myst agent-file --target CLAUDE.md
```

The generated block tells the agent: read state at task start, log decisions
and rejections with reasons, supersede — never rewrite — and refresh state
before finishing.

### Git hooks

```bash
cp .github/hooks/post-commit .git/hooks/post-commit && chmod +x .git/hooks/post-commit
cp .github/hooks/pre-push   .git/hooks/pre-push   && chmod +x .git/hooks/pre-push
```

- `post-commit` — records each commit as an event entry (async, never blocks).
- `pre-push` — runs `myst verify`; a corrupted ledger aborts the push.

### CI

`.github/workflows/ci.yml` runs the test suite on Python 3.9–3.13, builds the
standalone file and smoke-tests it in a scratch project, then replays a full
agent workflow (init → log → state → verify → doctor → export → consolidate).

---

## v1 compatibility

The original v1 interface still works:

```bash
myst init            # same
myst log "..."       # free text → kind=decision entry, text becomes title
myst state           # same idea, now budgeted and relevance-ranked
myst show            # same
```

`myst migrate v1` imports `invariants.yaml` (→ invariants/principles/
anti-patterns), trajectory `*.md` nodes (→ decision/rejection entries with
the v1 sections preserved verbatim) and writes a marker. v1 files are never
modified or deleted.

---

## Configuration

`.myst/myst.toml`:

```toml
[project]
name = "my-app"
description = "…"

[retrieval]
half-life = 30          # days; decay half-life for recency scoring
recency-weight = 1.0
frequency-weight = 0.6
pin-weight = 2.0
default-budget = 2000   # tokens for `myst state` when --budget is absent
```

Environment: `MYST_DIR` overrides the layer location. `NO_COLOR` /
`FORCE_COLOR` control terminal styling (pipe-safe by default).

---

## Design principles

1. **Zero runtime dependencies.** Stdlib only. PyYAML is optional and only
   used to read v1 files; a built-in mini-parser (`miniyaml`) covers the
   subset v1 files actually contain.
2. **Append-only human-readable stores.** `less` is an audit tool. Nothing
   hides in a binary format.
3. **The layer must never become the project.** Overhead per decision is
   one CLI call. Consolidation is explicit, proposals are drafts until
   reviewed, anti-pattern "building large meta-systems before validating on
   real work" is enforced by the tool's own smallness.
4. **Offline forever.** No network calls exist in the codebase.
5. **Provenance or it didn't happen.** Semantic items carry links to the
   episodes they came from; `myst doctor` flags orphans.

## Development

```bash
pip install -e .[dev]   # pytest
python -m pytest tests/ -q     # 132 tests, <1s
python tools/build_standalone.py   # regenerate myst_standalone.py
```

Project layout: `myst_persistence/` (core + CLI + MCP), `tests/`,
`tools/`, `examples/`, `.github/` (CI + hooks).

## License

MIT — see [LICENSE](LICENSE).
