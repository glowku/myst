"""CLI entry point — argparse-based, no external deps.

Subcommands: init, log, show, state, verify, consolidate, export, import,
doctor, status, migrate, hook, agent-file, server.

Exit codes: 0 ok · 1 usage/runtime error · 2 integrity failure · 3 data
format error. `main()` returns an int (testable); the console script
wrapper sys.exit()s it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import commands as _cmd
from .errors import MystError
from .model import Kind, Status
from .terminal import painter_for


def _comma_list(raw: str) -> list:
    return [p.strip() for p in raw.split(",") if p.strip()]


def _parse_options(raw: str) -> list:
    """Parse 'name=reason|chosen' option specs: name[=reason][*]."""
    out = []
    for chunk in raw.split("|") if raw else []:
        chunk = chunk.strip()
        if not chunk:
            continue
        chosen = chunk.endswith("*")
        if chosen:
            chunk = chunk[:-1].strip()
        name, _, reason = chunk.partition("=")
        out.append({"name": name.strip(),
                    "reason": reason.strip(), "chosen": chosen})
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="myst",
        description="Universal cognitive persistence layer for AI agents.",
        epilog="Docs: README.md · THEORY.md · `myst help <command>`")
    p.add_argument("--version", action="version",
                   version="myst-persistence %s" % __version__)
    sub = p.add_subparsers(dest="command")

    # init ---------------------------------------------------------------
    sp = sub.add_parser("init", help="create the .myst/ layer here")
    sp.add_argument("--name", default="", help="project name (default: dir name)")
    sp.add_argument("--description", default="", help="one-line description")
    sp.add_argument("--force", action="store_true",
                    help="complete missing parts even if .myst exists")

    # log ------------------------------------------------------------------
    sp = sub.add_parser("log", help="append a decision / rejection / insight")
    sp.add_argument("text", help="short title of the episode")
    sp.add_argument("--kind", default=Kind.DECISION,
                    choices=list(Kind.ALL), help="type of episode")
    sp.add_argument("--context", default="", help="forces at play")
    sp.add_argument("--decision", default="", help="what was decided")
    sp.add_argument("--rejection", default="", help="why a path was discarded")
    sp.add_argument("--consequences", default="", help="expected fallout")
    sp.add_argument("--options", default="",
                    help="options: 'name=reason|chosen-name*|other=reason'")
    sp.add_argument("--tags", default="", help="comma-separated tags")
    sp.add_argument("--status", default=Status.ACTIVE,
                    choices=list(Status.ALL))
    sp.add_argument("--supersedes", type=int, default=None,
                    help="entry id this one replaces")
    sp.add_argument("--pinned", action="store_true",
                    help="always include in injected state")
    sp.add_argument("--confidence", type=float, default=0.0,
                    help="0..1 self-assessed")

    # show -----------------------------------------------------------------
    sp = sub.add_parser("show", help="inspect ledger and semantic memory")
    sp.add_argument("--kind", choices=list(Kind.ALL))
    sp.add_argument("--status", choices=list(Status.ALL))
    sp.add_argument("--query", default="", help="substring filter")
    sp.add_argument("--no-closed", action="store_true",
                    help="hide superseded/reversed/obsolete entries")

    # state ------------------------------------------------------------------
    sp = sub.add_parser("state", help="generate the injectable cognitive state")
    sp.add_argument("--budget", type=int, default=None,
                    help="token budget (default: profile default-budget)")
    sp.add_argument("--focus", default="",
                    help="topic focus (boosts matching entries)")
    sp.add_argument("--format", default="markdown",
                    choices=["markdown", "compact", "json"])
    sp.add_argument("--include-closed", action="store_true")
    sp.add_argument("--max-entries", type=int, default=25)
    sp.add_argument("--no-save", action="store_true",
                    help="do not write .myst/state/current.*")
    sp.add_argument("--name", default="current", help="state file name")

    # verify ------------------------------------------------------------------
    sp = sub.add_parser("verify", help="verify ledger hash-chain integrity")

    # consolidate ---------------------------------------------------------------
    sp = sub.add_parser("consolidate",
                        help="distill episodes into semantic memory")
    sp.add_argument("--apply", action="store_true",
                    help="write proposals into the semantic store")
    sp.add_argument("--threshold", type=int, default=3)
    sp.add_argument("--prune-after", type=float, default=365.0,
                    help="days before cold closed entries are archived")
    sp.add_argument("--no-prune", action="store_true")
    sp.add_argument("--resurrect-days", type=int, default=0)

    # export / import -----------------------------------------------------------
    sp = sub.add_parser("export", help="export everything as JSON")
    sp.add_argument("out", nargs="?", default=None,
                    help="output path (default: stdout)")

    sp = sub.add_parser("import", help="import a JSON export")
    sp.add_argument("path", help="export file to import")
    sp.add_argument("--mode", choices=["merge", "replace"], default="merge")

    # doctor / status --------------------------------------------------------------
    sub.add_parser("doctor", help="environment health check")
    sub.add_parser("status", help="one-line summary (prompts, CI)")

    # migrate --------------------------------------------------------------------
    sp = sub.add_parser("migrate", help="migrate legacy data")
    sp.add_argument("from_version", choices=["v1"],
                    help="source version")

    # hook -----------------------------------------------------------------------
    sp = sub.add_parser("hook", help="git hook bridge")
    sp.add_argument("event", choices=["post-commit", "pre-push"])

    # agent-file --------------------------------------------------------------------
    sp = sub.add_parser("agent-file", help="write agent rules (AGENTS.md…)")
    sp.add_argument("--target", default="AGENTS.md")

    # server -------------------------------------------------------------------------
    sp = sub.add_parser("server", help="run protocol servers")
    ssp = sp.add_subparsers(dest="server_kind")
    ssp.add_parser("mcp", help="MCP stdio server (JSON-RPC 2.0)")

    return p


def main(argv: list | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    paint = painter_for(sys.stdout)

    try:
        if args.command == "init":
            code, text = _cmd.init(args.name, args.description,
                                    force=args.force)
        elif args.command == "log":
            code, text = _cmd.log(
                args.text, kind=args.kind, context=args.context,
                decision=args.decision, rejection=args.rejection,
                consequences=args.consequences,
                options=_parse_options(args.options) or None,
                tags=_comma_list(args.tags), status=args.status,
                supersedes=args.supersedes, pinned=args.pinned,
                confidence=args.confidence)
        elif args.command == "show":
            code, text = _cmd.show(kind=args.kind, status=args.status,
                                   query=args.query,
                                   include_closed=not args.no_closed)
        elif args.command == "state":
            code, text = _cmd.state(budget=args.budget, focus=args.focus,
                                    fmt=args.format,
                                    include_closed=args.include_closed,
                                    max_entries=args.max_entries,
                                    save=not args.no_save, name=args.name)
        elif args.command == "verify":
            code, text = _cmd.verify()
        elif args.command == "consolidate":
            code, text = _cmd.consolidate(
                apply=args.apply, threshold=args.threshold,
                prune_after=0.0 if args.no_prune else args.prune_after,
                resurrect_days=args.resurrect_days)
        elif args.command == "export":
            code, text = _cmd.export_json(
                Path(args.out) if args.out else None)
        elif args.command == "import":
            code, text = _cmd.import_json(Path(args.path), mode=args.mode)
        elif args.command == "doctor":
            code, text = _cmd.doctor()
        elif args.command == "status":
            code, text = _cmd.status()
        elif args.command == "migrate":
            from .migrate import migrate
            from .paths import MystPaths
            code, text = _run_migrate(MystPaths.discover())
        elif args.command == "hook":
            code, text = _cmd.hook(args.event)
        elif args.command == "agent-file":
            code, text = _cmd.agent_file(target=args.target)
        elif args.command == "server":
            if getattr(args, "server_kind", None) == "mcp":
                from .mcp_server import serve
                serve()
                return 0
            print("usage: myst server mcp", file=sys.stderr)
            return 1
        else:  # pragma: no cover
            parser.error("unknown command: %r" % args.command)
            return 1
    except MystError as exc:
        print("myst: %s" % exc, file=sys.stderr)
        return exc.exit_code
    except BrokenPipeError:  # `myst state | head` etc.
        return 0

    if text:
        print(text)
    return code


def _run_migrate(paths):
    from .migrate import migrate
    from .profile import ProjectProfile
    report = migrate(paths, ProjectProfile.load(paths.profile_file))
    if report.get("already_migrated"):
        return 0, "already migrated at %s" % report["at"]
    return 0, ("migrated from v1: %d semantic items, %d entries\n"
               "(v1 files kept untouched; marker: %s)"
               % (report["semantic_added"], report["entries_added"],
                  paths.layer / "migrated-from-v1.marker"))


if __name__ == "__main__":
    sys.exit(main())
