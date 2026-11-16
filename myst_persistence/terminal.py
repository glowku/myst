"""Terminal output helpers: colors when TTY, plain when piped.

The layer must be pipe-friendly: `myst state | wl-copy` must produce
zero ANSI bytes. Detection is done once per process and can be forced
via NO_COLOR / FORCE_COLOR (https://no-color.org convention).
"""

from __future__ import annotations

import os
import sys


def _supports_color(stream) -> bool:
    # Explicit forcing wins over disabling; otherwise honor NO_COLOR
    # (https://no-color.org), then fall back to TTY detection.
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR"):
        return False
    if not hasattr(stream, "isatty"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        return stream.isatty()
    except Exception:  # pragma: no cover - defensive
        return False


class Painter:
    """ANSI painter that degrades to no-ops on non-TTY streams."""

    def __init__(self, enabled: bool):
        self.enabled = enabled

    def _wrap(self, code: str, text: str) -> str:
        if not self.enabled or text == "":
            return text
        return "\033[%sm%s\033[0m" % (code, text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def blue(self, text: str) -> str:
        return self._wrap("34", text)

    def magenta(self, text: str) -> str:
        return self._wrap("35", text)

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)


def painter_for(stream=None) -> Painter:
    stream = stream or sys.stdout
    return Painter(_supports_color(stream))


def truncate(text: str, width: int = 72) -> str:
    """Single-line ellipsis truncation for summaries."""
    one = " ".join(text.split())
    if len(one) <= width:
        return one
    return one[: width - 1].rstrip() + "…"
