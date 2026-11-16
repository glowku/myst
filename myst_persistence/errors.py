"""Exception hierarchy for Myst.

Every failure surfaces as a MystError subclass so the CLI, the MCP server and
the git hooks can translate it into a clean message and exit code instead of
a traceback.
"""

from __future__ import annotations


class MystError(Exception):
    """Base class for all Myst failures."""

    exit_code = 1


class NotInitialized(MystError):
    """No .myst/ layer found in this project (run `myst init`)."""

    def __init__(self, searched=None):
        self.searched = searched
        super().__init__(
            "no .myst/ layer found%s — run `myst init` first"
            % (" under %s" % searched if searched else "")
        )


class IntegrityError(MystError):
    """The episodic ledger failed hash-chain verification."""

    exit_code = 2


class DataFormatError(MystError):
    """A hand-edited store file could not be parsed."""

    exit_code = 3
