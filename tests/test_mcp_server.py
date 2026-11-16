"""MCP server: JSON-RPC protocol compliance and tool semantics."""

import io
import json

import pytest

from myst_persistence import mcp_server


def _serve_lines(requests, cwd=None):
    """Run serve() over a list of request dicts; return response dicts.

    `cwd` is chdir'd into for the duration (tools resolve the layer from
    the current working directory)."""
    import os
    stdin = io.StringIO("".join(json.dumps(r) + "\n" for r in requests))
    out = io.StringIO()
    real = sys_stdout()
    prev = os.getcwd()
    if cwd is not None:
        os.chdir(cwd)
    set_stdout(out)
    try:
        mcp_server.serve(stdin=stdin)
    finally:
        set_stdout(real)
        if cwd is not None:
            os.chdir(prev)
    return [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]


def sys_stdout():
    import sys
    return sys.stdout


def set_stdout(stream):
    import sys
    sys.stdout = stream


def test_initialize_handshake(project):
    lines = _serve_lines([
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
    ])
    r = lines[0]["result"]
    assert r["protocolVersion"] == "2024-11-05"
    assert "tools" in r["capabilities"]
    assert r["serverInfo"]["name"] == "myst-persistence"


def test_tools_list(project):
    lines = _serve_lines([
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ])
    tools = lines[0]["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"myst_log", "myst_state", "myst_show", "myst_verify",
            "myst_consolidate", "myst_doctor", "myst_status"} <= names
    # every tool has a JSON schema
    for t in tools:
        assert t["inputSchema"]["type"] == "object"


def test_ping(project):
    lines = _serve_lines([{"jsonrpc": "2.0", "id": 3, "method": "ping"}])
    assert lines[0]["result"] == {}


def test_notification_silent(project):
    lines = _serve_lines([
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    ])
    assert lines == []


def test_unknown_method_error(project):
    lines = _serve_lines([
        {"jsonrpc": "2.0", "id": 4, "method": "no/such"},
    ])
    assert lines[0]["error"]["code"] == -32601


def test_unknown_tool_error(project):
    lines = _serve_lines([
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "nope", "arguments": {}}},
    ])
    assert lines[0]["error"]["code"] == -32602


def test_parse_error():
    stdin = io.StringIO("this is not json\n")
    out = io.StringIO()
    real = sys_stdout()
    set_stdout(out)
    try:
        mcp_server.serve(stdin=stdin)
    finally:
        set_stdout(real)
    lines = [json.loads(l) for l in out.getvalue().splitlines() if l.strip()]
    assert lines[0]["error"]["code"] == -32700


def test_myst_log_tool(project):
    before = _serve_lines([
        {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
         "params": {"name": "myst_log",
                    "arguments": {"text": "via mcp", "kind": "insight",
                                  "tags": ["mcp"]}}},
    ], cwd=project)[0]["result"]
    assert before["isError"] is False
    assert "logged #" in before["content"][0]["text"]

    after = _serve_lines([
        {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
         "params": {"name": "myst_show", "arguments": {"query": "via mcp"}}},
    ], cwd=project)[0]["result"]
    assert "via mcp" in after["content"][0]["text"]


def test_myst_state_tool_budget(project):
    r = _serve_lines([
        {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
         "params": {"name": "myst_state",
                    "arguments": {"budget": 300, "format": "compact"}}},
    ], cwd=project)[0]["result"]
    text = r["content"][0]["text"]
    assert not r["isError"]
    assert text.strip()  # non-empty even under tight budget


def test_myst_verify_tool_ok(project):
    r = _serve_lines([
        {"jsonrpc": "2.0", "id": 13, "method": "tools/call",
         "params": {"name": "myst_verify", "arguments": {}}},
    ], cwd=project)[0]["result"]
    assert "OK" in r["content"][0]["text"]


def test_myst_status_tool(project):
    r = _serve_lines([
        {"jsonrpc": "2.0", "id": 14, "method": "tools/call",
         "params": {"name": "myst_status", "arguments": {}}},
    ], cwd=project)[0]["result"]
    assert "myst:" in r["content"][0]["text"]
