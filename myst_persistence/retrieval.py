"""Retrieval scoring: which episodic entries deserve context slots?

The score combines five signals, all cheap (no embeddings, no model calls):

    relevance(e) = w_recency · recency(e)
                 + w_freq     · topic_frequency(e)
                 + w_pin      · pinned(e)
                 + w_kind     · kind_bias(e)
                 + w_query    · query_overlap(e)

- **recency** — Ebbinghaus-style exponential decay with a configurable
  half-life (default 30 days). Power-law-ish behavior: an entry from
  yesterday scores ~1.0, from 30 days ago ~0.5, from 90 days ~0.125.
- **topic frequency** — how often the project's *recent* entries touch
  the same tags: hot topics stay available, cold topics fade even when
  recent (an isolated one-off note is less load-bearing than a theme).
- **pinned** — the author's explicit "always keep this" flag.
- **kind bias** — decisions and rejections carry more long-term value
  than events; insights sit in between; risks are boosted slightly
  (losing a known risk is expensive).
- **query overlap** — token overlap with the optional focus query
  (`myst state --focus "payments"`): a cheap BM25-lite term match.

Everything is a pure function of (entries, profile, now) — deterministic,
fully testable, zero network. Superseded/reversed entries are downweighted
by a status factor rather than excluded: *how* a decision died is part of
the reasoning signature, but it should not crowd out living decisions.
"""

from __future__ import annotations

import math
import re

from .model import Entry, Kind
from .profile import RetrievalTuning
from .timeutil import now, parse_ts, days_between

# Default signal weights (overridable per-kind via tuning fields).
KIND_BIAS = {
    Kind.DECISION: 1.0,
    Kind.REJECTION: 1.0,     # the signature of thinking
    Kind.INSIGHT: 0.8,
    Kind.RISK: 0.9,
    Kind.EVENT: 0.5,
}

STATUS_FACTOR = {
    "active": 1.0,
    "superseded": 0.45,
    "reversed": 0.35,
    "obsolete": 0.2,
}

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall(text.lower()))


def recency_component(entry: Entry, reference, half_life: float) -> float:
    """Exponential decay: 2^(−age/half_life), age in days (>= 0)."""
    try:
        ts = parse_ts(entry.ts)
    except ValueError:
        return 0.0  # undated entry: decay to zero, never crash
    age_days = max(0.0, days_between(ts, reference))
    return math.pow(2.0, -age_days / max(half_life, 1e-9))


def topic_frequencies(entries: list, horizon: int = 60) -> dict:
    """Tag → frequency over the `horizon`-day tail of the ledger (0..1)."""
    reference = now()
    counts, total = {}, 0
    for e in entries:
        try:
            age = days_between(parse_ts(e.ts), reference)
        except ValueError:
            continue
        if age < -1 or age > horizon:
            continue
        for tag in e.tags:
            counts[tag] = counts.get(tag, 0) + 1
            total += 1
    if not total:
        return {}
    return {tag: n / total for tag, n in counts.items()}


def score_entries(entries: list, tuning: RetrievalTuning,
                  focus: str = "", reference=None) -> list:
    """Return [(entry, score, reason)] sorted by score desc, id asc.

    `reason` is a short human-readable string ("pinned; hot tag 'db';
    focus match 3") — the state renderer can show *why* each entry was
    selected, which makes the layer auditable instead of magical.
    """
    reference = reference or now()
    focus_terms = _tokens(focus) if focus else set()
    freqs = topic_frequencies(entries)
    scored = []

    for entry in entries:
        parts, reasons = 0.0, []

        rec = recency_component(entry, reference, tuning.half_life)
        parts += tuning.recency_weight * rec
        if rec > 0.6:
            reasons.append("recent")

        if tuning.frequency_weight:
            tag_freq = max((freqs.get(t, 0.0) for t in entry.tags), default=0.0)
            parts += tuning.frequency_weight * tag_freq
            hot = [t for t in entry.tags if freqs.get(t, 0.0) > 0.34]
            if hot:
                reasons.append("hot " + "/".join(sorted(hot)[:3]))

        if entry.pinned:
            parts += tuning.pin_weight
            reasons.append("pinned")

        kind_bias = KIND_BIAS.get(entry.kind, 0.5)
        parts += 0.25 * kind_bias  # small constant bias, always on

        if focus_terms:
            text_terms = _tokens(" ".join([
                entry.title, entry.context, entry.decision, entry.rejection,
                entry.consequences] + [o.name for o in entry.options]
                + entry.tags))
            overlap = len(focus_terms & text_terms)
            if overlap:
                parts += 0.35 * min(overlap, 5) / 5.0 + 0.15 * overlap
                reasons.append("focus×%d" % overlap)

        parts *= STATUS_FACTOR.get(entry.status, 0.5)

        scored.append((entry, round(parts, 4), "; ".join(reasons)))

    scored.sort(key=lambda pair: (-pair[1], pair[0].id))
    return scored
