# Example: MCP client configuration snippets

## Claude Desktop / Claude Code

`claude_desktop_config.json` (or `.claude.json` → `mcpServers`):

```json
{
  "mcpServers": {
    "myst": {
      "command": "myst",
      "args": ["server", "mcp"]
    }
  }
}
```

## Cursor / any MCP client with command-based servers

```json
{
  "mcpServers": {
    "myst": {
      "command": "python",
      "args": ["-m", "myst_persistence", "server", "mcp"]
    }
  }
}
```

## Standalone variant (no install)

```json
{
  "mcpServers": {
    "myst": {
      "command": "python3",
      "args": ["/absolute/path/to/myst_standalone.py", "server", "mcp"]
    }
  }
}
```

## Available tools

| Tool | Purpose |
|---|---|
| `myst_log` | append a decision / rejection / insight / risk / event |
| `myst_state` | injectable cognitive state within a token budget |
| `myst_show` | inspect ledger + semantic memory with filters |
| `myst_verify` | hash-chain integrity check |
| `myst_consolidate` | propose semantic items from recurring patterns |
| `myst_doctor` | layer health check |
| `myst_status` | one-line summary |

## Session protocol (what the agent does)

1. Task start → `myst_state {"budget": 1500, "focus": "<current topic>"}`.
2. When deciding or rejecting anything architectural → `myst_log` with
   `kind`, `tags`, `decision`/`rejection` and reasons for each option.
3. When reversing course → `myst_log` with `supersedes: <old id>`.
4. Task end → refresh state; weekly → `myst_consolidate` (review proposals,
   re-run with `apply: true` to write them).
