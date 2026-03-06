# modelmux

Model multiplexer — unified MCP server for cross-platform multi-model AI collaboration.

## Quick Reference

- **Package**: `mcp/modelmux/` (pyproject.toml, src/modelmux/)
- **Install**: `uvx modelmux` or `claude mcp add modelmux -s user -- uvx modelmux`
- **Python**: Use `uv`, not system python. Requires 3.10+
- **Tests**: `cd mcp/modelmux && uv run --with pytest python -m pytest tests/ --ignore=tests/test_e2e.py`
- **Lint**: `uv run ruff check src/ && uv run ruff format src/`
- **Build**: `uv build`
- **CI**: GitHub Actions (matrix 3.10-3.12 x ubuntu/macos), auto-publish on tag

## Architecture

```
MCP Client → modelmux (FastMCP server, stdio)
  ├── mux_dispatch   → single provider dispatch (auto-route, failover)
  ├── mux_broadcast  → parallel multi-provider dispatch
  ├── mux_history    → query result history & analytics
  └── mux_check      → availability & config status
      │
      ├── CodexAdapter  → codex exec --json
      ├── GeminiAdapter → gemini -p -o stream-json
      ├── ClaudeAdapter → claude -p
      └── OllamaAdapter → ollama run <model>
```

## Key Files

| File | Purpose |
|------|---------|
| `server.py` | MCP tools (dispatch, broadcast, history, check) |
| `adapters/base.py` | Threaded subprocess runner, canonical result schema |
| `adapters/{codex,gemini,claude,ollama}.py` | Provider-specific adapters |
| `config.py` | Profile loading, routing rules |
| `detect.py` | Caller platform detection |
| `audit.py` | JSONL audit log (policy rate-limiting) |
| `history.py` | Full result storage (history.jsonl) |
| `policy.py` | Policy engine (rate limits, blocks) |
| `status.py` | Real-time dispatch status tracking |
| `tui.py` | Textual TUI config panel |
| `init_wizard.py` | Interactive setup wizard |
| `cli.py` | CLI entry point with subcommands |

## Dev Workflow

1. Edit `src/modelmux/` files
2. `uv sync` (if deps changed)
3. Run tests + lint
4. Commit → push → tag `vX.Y.Z` → auto-publish to PyPI

## Conventions

- Adapters inherit `BaseAdapter`, implement `build_command()` and `parse_output()`
- All dispatch results use `AdapterResult` canonical schema
- Config files: `~/.config/modelmux/` (user) or `.modelmux/` (project)
- Status files: `~/.config/modelmux/status/{run_id}.json`
- Chinese for internal docs, bilingual for public docs

See `docs/ROADMAP.md` for feature planning, `docs/CHANGELOG.md` for version history.
