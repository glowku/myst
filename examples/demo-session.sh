#!/usr/bin/env bash
# Full agent-session demo: the complete Myst lifecycle in one script.
# Run from anywhere — works on a scratch copy, never on your real layer.

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO="${1:-/tmp/myst-demo}"
MYST_BIN="${MYST_BIN:-myst}"

rm -rf "$DEMO"
mkdir -p "$DEMO"
cd "$DEMO"

b() { printf '\n\033[1;34m»» %s\033[0m\n' "$*"; }

b "1/ init the layer"
$MYST_BIN init --name demo-app --description "a demo cognitive layer"

b "2/ log the founding decisions (with rejected options)"
$MYST_BIN log "storage engine" --kind decision \
  --context "single-user desktop app, offline-first" \
  --options "sqlite=zero ops, embedded*|postgres=powerful queries|mongo=document model" \
  --decision "sqlite, WAL mode on" \
  --consequences "no server, backups = copy a file" \
  --tags db,arch

$MYST_BIN log "pure RAG memory" --kind rejection \
  --rejection "loses the reasoning behind choices; retrieves facts, not why" \
  --context "evaluated for cross-session memory" \
  --tags arch,memory

$MYST_BIN log "CLI framework" --kind rejection \
  --rejection "typer/click add deps for 14 subcommands we can argparse ourselves" \
  --tags deps

$MYST_BIN log "hash-chained ledger" --kind decision \
  --decision "sha256 chain + head sidecar; append-only forever" \
  --tags ledger,integrity --pinned

$MYST_BIN log "free-text logs lose structure" --kind insight \
  --context "observed in v1 usage" \
  --decision "tags + kind enum make retrieval deterministic" \
  --tags meta,memory

b "3/ supersede an old decision (append, never rewrite)"
$MYST_BIN log "state rendering" --kind decision \
  --decision "budgeted packing with visible truncation markers" \
  --supersedes 1 --tags state,arch

b "4/ generate the injectable state under a token budget"
$MYST_BIN state --budget 900 --focus "db ledger"

b "5/ verify integrity"
$MYST_BIN verify

b "6/ health check"
$MYST_BIN doctor

b "7/ one-line status"
$MYST_BIN status

b "8/ consolidate recurring patterns (dry run)"
$MYST_BIN consolidate --threshold 2 --no-prune

b "9/ export"
$MYST_BIN export demo-export.json

b "10/ show the ledger"
$MYST_BIN show --no-closed | head -40

printf '\nDemo layer at %s/.myst — inspect with less.\n' "$DEMO"
