# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [2.0.0] - 2026-11-16

Complete rewrite of v1. Backwards compatible with v1 CLI verbs, forward-looking
in data model. Zero runtime dependencies (PyYAML optional with pure-Python
fallback).

### Architecture

- **Two-store memory model** derived from complementary learning systems (CLS):
  an append-only *episodic ledger* (every decision/rejection logged verbatim,
  hash-chained) and a curated *semantic store* (invariants, principles, distilled
  knowledge). Episodic memory writes are fast and lossless; semantic memory
  changes are slow, reviewed, and consolidated from episodes.
- **ADR-grade entries** following Nygard's schema: context, options considered,
  decision, consequences — including rejected options with reasons.
- **Semantic-memory files are TOML+Markdown**, no YAML parser required.
- **Integrity**: every ledger entry is hash-chained (SHA-256 of content +
  previous hash). `myst verify` detects tampering, deletions, reordering, and
  entry-subset rewriting.

### New in 2.0

- `myst init` — scaffold a `.myst/` layer with default profile and gitignore.
- `myst log` — append a decision (structured `--kind decision|rejection|insight|risk|event`,
  `--context`, `--options`, `--rejection`, `--consequences`, `--supersede`, `--status`).
- `myst show` — inspect ledger and semantic store (filter by kind, status, query text).
- `myst state` — generate injectable state **within a token budget** (`--budget`,
  `--format`, `--pinned`) with relevance-ranked retrieval (recency, frequency,
  Ebbinghaus-style decay, tag overlap, pinned always-included).
- `myst consolidate` — distill episodes into semantic memory items
  (`--from`, `--prune-after`, `--resurrect-days`).
- `myst verify` — verify hash-chain integrity of the episodic ledger.
- `myst export` — export ledger and semantic store as JSON (backup, diffing, audit).
- `myst import` — import JSON exports (merge or replace).
- `myst doctor` — check environment health and invariants.
- `myst migrate v1` — migrate a v1 `.myst/` directory to the v2 layout.
- `myst hook` — git hook integration: post-commit auto-log, pre-push verify.
- `myst server mcp` — Model Context Protocol server over stdio (JSON-RPC 2.0),
  exposing `log`, `state`, `show`, `verify`, `consolidate` as tools.
- `myst agent-file` — emit a ready-to-paste agent instruction file
  (`AGENTS.md` / `CLAUDE.md` / `SYSTEM.md`) that tells any coding agent how to
  use the layer autonomously.
- `myst status` — one-line summary for shell prompts and CI.
- `myst --version`, `myst help [command]`.

### Data guarantees

- Append-only ledger: log writes never overwrite past entries; `myst log --status`
  changes status on a *copy* of the entry with a supersede link to the old one.
- Human-readable plain text everywhere; every file inspectable with `less`.
- Everything runs offline; no network calls anywhere in the library.
- `myst verify` detects tampering, deletion, reordering, and entry-subset
  rewriting.
- Terminal adapter detection (color when TTY, plain when piped).

### Migration from v1

- v1 CLI (`init`, `log "..."`, `state`, `show`) still works; free-text logs are
  parsed into `kind=decision` entries with the text preserved in `title`.
- `myst migrate v1` imports `invariants.yaml`, trajectory `.md` nodes, and
  `current_state.md` (as a snapshot event) into the v2 stores.
- v1 data is never destroyed; migration copies, never deletes.

### Notable internals

- `myst_persistence.minyaml` — tiny safe YAML subset parser (used when PyYAML
  is absent, e.g. reading v1 files): supports plain scalars, inline lists,
  block lists, nested mappings, and comments. Refuses unsafe tags.
- `myst_persistence.timeutil` — fixed-calendar date arithmetic (leap years)
  without depending on `datetime` heavy machinery for decay math? (No — `datetime`
  is stdlib, fine to use; but timeutil gives pure functions testable without
  mocking.)
- Full test suite: unit tests for minyaml, scoring, budget, consolidate,
  verify, migration, render formats, MCP protocol, hook lifecycle, CLI arg
  parsing, doctor, export/import roundtrip.

## [1.0.0] - original release

- `myst.py` + `myst_inject.py`, YAML invariants + Markdown trajectory,
  free-text `log`, last-N-files "compression", manual copy-paste state.

## [Unreleased]

- Translations of README (fr, zh).
