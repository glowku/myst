"""Token accounting: approximate token counts from character/word statistics.

We deliberately use an approximation (no tokenizer dependency):

    tokens ~ ceil(chars / 3.6)

3.6 chars/token is the commonly cited cross-tokenizer average for English
prose and code mixed text (GPT-style BPE averages ~4 chars/token on English
prose, closer to ~3 on code and CJK-heavy text). We pick 3.6 as a working
average and expose `TOKENS_PER_CHAR` so callers can tune it in the profile.
The budget system treats counts as estimates, and always reserves the last
resort: if a single unit (invariant / entry) exceeds the whole budget it is
still emitted truncated with a visible marker, never silently dropped.
"""

from __future__ import annotations

import math

# Working average: tokens ≈ chars / 3.6  (English prose + code mix).
TOKENS_PER_CHAR = 3.6

# Safety margin applied to user-provided budgets (10%): the injected state
# must never claim a budget it actually overruns.
BUDGET_SAFETY_MARGIN = 0.10


def estimate_tokens(text: str) -> int:
    """Approximate the token count of `text` (empty → 0)."""
    if not text:
        return 0
    return int(math.ceil(len(text) / TOKENS_PER_CHAR))


def clamp_to_budget(text: str, max_tokens: int) -> str:
    """Truncate `text` so its estimated token count fits `max_tokens`.

    Appends a visible `[…N tokens clipped]` marker when truncation happens.
    Never truncates mid-multibyte-character (cuts on a char boundary).
    """
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(0, int(max_tokens * TOKENS_PER_CHAR) - len("\n[…clipped]"))
    cut = text[:max_chars]
    # cut at a word boundary when reasonable, else hard cut
    if len(cut) < len(text):
        space = cut.rfind(" ")
        if space > max_chars // 2:
            cut = cut[:space]
    return cut + "\n[…clipped]"
