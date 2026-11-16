"""MCP (Model Context Protocol) stdio server — JSON-RPC 2.0, zero deps.

Speaks the minimal MCP surface needed for coding-agent integration:

    initialize → {protocolVersion, capabilities:{tools:{}}, serverInfo}
    tools/list → tool descriptors with JSON schemas
    tools/call → executes one of: log, state, show, verify, consolidate,
                 doctor, status
    ping       → {}

Notifications (no id) are ignored; unknown methods return JSON-RPC
errors (-32601). Every tools/call result is MCP content
({content: [{type: "text", text}]}), isError=true on command failure.
The server runs entirely offline and exits when stdin closes.
"""

from __future__ import annotations

import json
import sys

from . import __version__, commands as _cmd
from .model import Kind, Status

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "myst_log",
        "description": "Append an episodic entry to the project's cognitive "
                       "ledger (decision / rejection / insight / risk / event). "
                       "Always record why alternatives were rejected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "short title of the episode"},
                "kind": {"type": "string",
                         "enum": list(Kind.ALL),
                         "default": "decision"},
                "context": {"type": "string"},
                "decision": {"type": "string"},
                "rejection": {"type": "string"},
                "consequences": {"type": "string"},
                "options": {"type": "array",
                             "description": "options considered: "
                                            "[{name, chosen, reason}]",
                             "items": {"type": "object",
                                       "properties": {
                                           "name": {"type": "string"},
                                           "chosen": {"type": "boolean"},
                                           "reason": {"type": "string"}}}},
                "tags": {"type": "array", "items": {"type": "string"}},
                "supersedes": {"type": "integer",
                               "description": "id of the entry this replaces"},
                "pinned": {"type": "boolean", "default": False},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["text"],
        },
    },
    {
        "name": "myst_state",
        "description": "Generate the injectable cognitive state (invariants + "
                       "relevance-ranked trajectory) within a token budget. "
                       "Use at task start to load project context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "budget": {"type": "integer", "minimum": 120,
                           "description": "token budget for the state"},
                "focus": {"type": "string",
                          "description": "topic focus for retrieval boosting"},
                "format": {"type": "string",
                           "enum": ["markdown", "compact", "json"],
                           "default": "markdown"},
                "include_closed": {"type": "boolean", "default": False},
                "max_entries": {"type": "integer", "default": 25},
                "save": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "myst_show",
        "description": "Inspect the ledger and semantic memory (filters "
                       "optional). Use to review project reasoning history.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(Kind.ALL)},
                "status": {"type": "string", "enum": list(Status.ALL)},
                "query": {"type": "string"},
                "include_closed": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "myst_verify",
        "description": "Verify the hash-chain integrity of the episodic "
                       "ledger. Detects tampering, deletion, reordering.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "myst_consolidate",
        "description": "Distill recurring episodic patterns into semantic "
                       "memory proposals (apply=false by default).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "apply": {"type": "boolean", "default": False},
                "threshold": {"type": "integer", "minimum": 2, "default": 3},
            },
        },
    },
    {
        "name": "myst_doctor",
        "description": "Health check of the cognitive layer.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "myst_status",
        "description": "One-line ledger summary.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_TOOL_NAMES = {t["name"] for t in TOOLS}


class JSONRPCError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def _result(req_id, result):
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
    sys.stdout.flush()


def _error(req_id, code, message):
    sys.stdout.write(json.dumps({
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": code, "message": message}}) + "\n")
    sys.stdout.flush()


def _tool_content(text, is_error=False):
    return {"content": [{"type": "text", "text": text}],
            "isError": bool(is_error)}


def handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "myst-persistence", "version": __version__},
        })

    if method == "notifications/initialized":
        return None  # notification: no response

    if method == "ping":
        return _result(req_id, {})

    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name not in _TOOL_NAMES:
                raise JSONRPCError(-32602, "unknown tool: %r" % name)
            if name == "myst_log":
                code, text = _cmd.log(
                    args["text"], kind=args.get("kind", "decision"),
                    context=args.get("context", ""),
                    decision=args.get("decision", ""),
                    rejection=args.get("rejection", ""),
                    consequences=args.get("consequences", ""),
                    options=args.get("options"),
                    tags=args.get("tags", []),
                    status=args.get("status", "active"),
                    supersedes=args.get("supersedes"),
                    pinned=bool(args.get("pinned", False)),
                    confidence=float(args.get("confidence", 0.0)),
                )
            elif name == "myst_state":
                code, text = _cmd.state(
                    budget=args.get("budget"),
                    focus=args.get("focus", ""),
                    fmt=args.get("format", "markdown"),
                    include_closed=bool(args.get("include_closed", False)),
                    max_entries=int(args.get("max_entries", 25)),
                    save=bool(args.get("save", True)),
                )
            elif name == "myst_show":
                code, text = _cmd.show(
                    kind=args.get("kind"), status=args.get("status"),
                    query=args.get("query", ""),
                    include_closed=bool(args.get("include_closed", True)),
                )
            elif name == "myst_verify":
                code, text = _cmd.verify()
            elif name == "myst_consolidate":
                code, text = _cmd.consolidate(
                    apply=bool(args.get("apply", False)),
                    threshold=int(args.get("threshold", 3)),
                    prune_after=0.0,  # MCP never prunes implicitly
                )
            elif name == "myst_doctor":
                code, text = _cmd.doctor()
            elif name == "myst_status":
                code, text = _cmd.status()
            else:  # pragma: no cover — guarded by _TOOL_NAMES above
                raise JSONRPCError(-32602, "unknown tool: %r" % name)
        except JSONRPCError:
            raise
        except KeyError as exc:
            raise JSONRPCError(-32602,
                               "missing argument: %s" % exc.args[0])
        except Exception as exc:  # tool-level failure → isError content
            return _result(req_id, _tool_content(
                "myst %s failed: %s" % (name, exc), is_error=True))
        return _result(req_id, _tool_content(
            text if code == 0 else "FAILED: " + text, is_error=code != 0))

    if req_id is not None:
        raise JSONRPCError(-32601, "method not found: %r" % method)
    return None  # unknown notification


def serve(stdin=None, stdout=None):
    """Run the stdio loop until EOF. Blocks."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _error(None, -32700, "parse error: %s" % exc)
            continue
        try:
            handle_request(req)
        except JSONRPCError as exc:
            _error(req.get("id"), exc.code, exc.message)
        except Exception as exc:  # never crash the server loop
            _error(req.get("id"), -32603, "internal error: %s" % exc)


if __name__ == "__main__":
    serve()
