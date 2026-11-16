# Theory — why Myst is built the way it is

This document grounds every design decision in memory science, protocol
design and software-engineering practice. Each section states the source
principle, the citation, and the concrete mechanism in this repository.
Nothing here is decorative: if a mechanism exists, a principle demanded it.

---

## 1. Two memory systems (complementary learning systems)

**Principle.** The brain does not have one memory; it has two with opposite
trade-offs. The hippocampal system stores individual episodes fast, at full
fidelity, interfering with nothing. The neocortical system integrates slowly,
extracting structure that generalizes — but cannot bind individual events
quickly without catastrophic interference.McClelland, McNaughton & O'Reilly
(1995) argued this division is *why* complementary systems exist at all:
rapid learning and slow structure-building cannot share a mechanism.

> McClelland, J. L., McNaughton, B. L., & O'Reilly, R. C. (1995). *Why there
> are complementary learning systems in the hippocampus and neocortex:
> insights from the successes and failures of connectionist models of
> learning and memory.* Psychological Review, 102(3), 419–457.
> https://pubmed.ncbi.nlm.nih.gov/7624455/

**In Myst.** The episodic ledger (`ledger.jsonl`) is the hippocampal system:
one append per decision, verbatim, no curation, no rewriting. The semantic
store (`semantic.toml` + `semantic.d/`) is the neocortical system: curated
invariants and principles, changed deliberately, generalized from many
episodes. Consolidation (`myst consolidate`) is the interleaved transfer
between them — and just as in CLS, it is *slow and conservative* (proposals
are drafts; existing items only gain provenance links).

The analogy also dictates what we refuse to do: no "smart" automatic rewrite
of history, no deduplication of episodes, no silent merging. Interference
is the cost hippocampus pays for fidelity, and we accept it on purpose —
`grep .myst/ledger.jsonl` must always be a truthful search.

---

## 2. Episodic vs semantic memory (Tulving)

**Principle.** Episodic memory is memory *of events* situated in time
("we chose SQLite on Tuesday"); semantic memory is memory *of facts*
decoupled from acquisition ("SQLite is embedded and needs zero ops").
The systems have different failure modes and different refresh rules.

> Tulving, E. (1972). *Episodic and semantic memory.* In E. Tulving & W.
> Donaldson (Eds.), Organization of Memory (pp. 381–403). Academic Press.
> https://psycnet.apa.org/record/1973-08477-007

**In Myst.** An entry keeps its timestamp, its context, its options and its
consequences — it *is* an episode. A semantic item (`SemanticItem`) states
something that was never time-bound in the first place (an invariant), or
became time-independent through repetition (a distilled pattern, with
provenance back-links to the episodes it came from). The state injector
renders the two differently: invariants as binding rules, episodes as
"recent trajectory" narrative.

This is also why `SemanticItem.validate` forbids empty rationale-by-provenance:
a semantic fact without provenance in this system is a hallucination risk,
so provenance is either present or the item is flagged by `myst doctor`.

---

## 3. Forgetting as retrieval decay (Ebbinghaus)

**Principle.** Memory strength decays with time, roughly logarithmically.
The exact function matters less than the shape: rapid initial loss,
long tail. Any retrieval system that scores memories must weight recency
or drown in its own history.

> Ebbinghaus, H. (1885/1913). *Memory: A Contribution to Experimental
> Psychology.* (H. A. Ruger & C. E. Bussenius, Trans.). Teachers College,
> Columbia University. https://psychclassics.yorku.ca/Ebbinghaus/index.htm

**In Myst.** `recency_component()` computes `2^(−age/half_life)` with a
configurable half-life (default 30 days): yesterday ≈ 1.0, a month ago ≈ 0.5,
a season ago ≈ 0.125. We choose exponential decay over a power law because
the profile knob stays interpretable ("half-life in days") for developers
who will tune it; Ebbinghaus's own savings-function is closer to a power
law, and the profile allows shrinking the half-life to approximate it.

Crucially, decay affects *retrieval priority*, never *existence*: the entry
stays in the ledger byte-for-byte. Forgetting in Myst means "not injected
into the next context", not "destroyed" — an important divergence from
biological memory that we take deliberately, because developer tooling
must be auditable.

---

## 4. Spaced retrieval and resurrection

**Principle.** Reviewing material at expanding intervals slows forgetting
more than massed review — and retrieval success is a function of study
schedule, not just strength. Cepeda et al.'s meta-analysis of 254 studies
quantified that spacing effects are large and robust.

> Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T., & Rohrer, D. (2006).
> *Distributed practice in verbal recall tasks: A review and quantitative
> synthesis.* Psychological Bulletin, 132(3), 354–380.
> https://pubmed.ncbi.nlm.nih.gov/16719566/

**In Myst.** Archived episodes are not dead: `resurrect()` computes topic
frequencies over the *live* ledger horizon, and when an archived entry's
tags become hot again (a theme you are actively working on), it is copied
back into the live ledger. The memory is "re-learned" exactly when it is
about to be needed — spaced retrieval applied to a project's own history.
The threshold (0.25) is deliberately conservative: resurrection costs
budget, so only clearly-hot topics resurface.

---

## 5. Decisions as records (ADRs)

**Principle.** An architecture decision is only useful if the *forces* and
the *rejected options* survive alongside the choice. Nygard's ADR format —
title, status, context, decision, consequences — became the industry
standard precisely because it captures the reasoning, not just the result.

> Nygard, M. (2011). *Documenting Architecture Decisions.*
> https://www.cognitect.com/blog/2011/11/15/documenting-architecture-decisions

**In Myst.** Every `Entry` carries `context`, `options[]` (each with
`chosen`, `reason`), `decision`, `rejection`, `consequences`. The renderer
prints options as `✓ chosen — reason` / `✗ rejected — reason`. The v1
project's founding insight — *rejected paths are the signature of how you
think* — is preserved here as a first-class schema field rather than free
text. Status (`active/superseded/reversed/obsolete`) mirrors ADR lifecycle,
with one crucial divergence: changing status never edits the old record
(append-only), it appends a new entry with `supersedes`, which retrieval
downweights via the supersede map.

---

## 6. Tamper-evidence (hash chains / append-only logs)

**Principle.** An append-only log where each record commits to the hash of
its predecessor gives cheap, local, offline integrity: any edit, deletion
or reorder breaks the chain at the first affected line. This is the same
construction that underpins blockchains and Certificate Transparency —
here used with no distributed consensus, just as a tamper-*evident* seal.

**In Myst.** Line *N* stores `prev = digest(line N−1)` and
`digest = SHA-256(prev + canonical JSON of entry)`. Line 1 chains from the
constant string `GENESIS`. Because *any prefix of a hash chain is itself a
valid chain*, tail truncation is invisible to the chain alone — so a
`.head` sidecar pins the latest digest and `myst verify` compares it.
Residual limits, stated honestly:

- an attacker who rewrites the ledger *and* the head file produces a
  consistent state (defense: git history, or backups + timestamps);
- `import --replace` legitimately rewrites, so it always snapshots into
  `.myst/backups/pre-import-<timestamp>/` first and says so.

We do not claim tamper-*proofness*; we claim that ordinary accidents
(hand-edits, partial writes, truncated copies, botched merges) are always
detected, and that is what a developer tool needs.

---

## 7. Bounded context injection (token budgets)

**Principle.** LLM context windows are finite and attention degrades with
filler; injecting "everything" is the failure mode of naive memory systems.
The engineering answer is a budgeted pack: fixed-priority sections first,
then best-value items until the budget is exhausted.

**In Myst.** `build_state()` reserves header/statistics overhead, renders the
semantic core first (pinned invariants are never dropped — they are
truncated with a visible `[…clipped]` marker instead, so a violation of
"invariant present" is impossible to miss), then fills the trajectory with
best-scoring entries. Under tight budgets whole entries demote to one-line
summaries before being dropped. Token counts are estimates (chars/3.6 —
cross-tokenizer average for English prose and code); the contract is that
the *claimed* budget is respected with a 10% safety margin, and the state
header carries the estimate so the injecting agent can sanity-check it.

The alternative — calling out to a real tokenizer — would add a dependency
and pin us to one vendor's notion of a token; both violate design principle
#1 (zero dependencies) and the vendor-neutrality requirement.

---

## 8. Why the rejected options matter more than the decisions

A decision record tells a future agent what to do; a rejection record tells
it what *not to try again and why*. In long-running projects the second is
worth more: the failure modes are where time actually goes, and "we tried
that in March and it broke" is the single most expensive fact to lose.

Psychologically this is negative transfer avoidance; operationally it is
the difference between an agent that re-litigates settled questions every
session and one that inherits the shape of prior reasoning. Myst's scoring
gives `rejection` entries the same kind-bias as `decision`, and the MCP
tool description says it outright: *"Always record why alternatives were
rejected."*

---

## 9. What Myst is not

- **Not a vector store.** No embeddings, no similarity search. Tags,
  recency, frequency and focus terms do the retrieval work deterministically
  and offline. For most projects' decision volumes (< 10⁴ entries) this is
  sufficient, and it never breaks in surprising ways.
- **Not a knowledge graph.** Two stores, one relation type (provenance).
  The deliberate smallness is itself an anti-pattern guard: "letting the
  memory system become more important than the actual project" was listed
  as an anti-pattern in v1's own invariants, and v2 enforces it.
- **Not automatic.** Logging is one command; consolidation is explicit;
  semantic drafts are reviewed by a human before they bind behavior.
  Effortless-seeming automation is how memory layers rot into noise.

---

## Source map

| Mechanism | File(s) | Source principle |
|---|---|---|
| episodic/semantic split | `model.py`, `semantic.py` | Tulving (1972); McClelland et al. (1995) |
| append-only consolidation | `consolidate.py` | McClelland et al. (1995) — slow interleaved transfer |
| recency decay | `retrieval.py:recency_component` | Ebbinghaus (1885/1913) |
| topic-frequency boost | `retrieval.py:topic_frequencies` | spacing/spacing-adjacent retrieval scheduling |
| resurrection of archived topics | `consolidate.py:resurrect` | Cepeda et al. (2006) — spaced retrieval |
| ADR-grade entries | `model.py:Entry` | Nygard (2011) |
| status lifecycle via append | `model.py:Status`, `commands.py:log` | Nygard (2011) + append-only logs |
| hash chain + head pin | `ledger.py` | tamper-evident logs (CT-style) |
| budgeted packing | `state.py`, `tokens.py` | bounded context windows |
| provenance on semantic items | `model.py:SemanticItem`, `commands.py:doctor` | auditability requirement |
| miniyaml safe subset | `miniyaml.py` | zero-dependency constraint; YAML tags refused |
