# Contributing

Thanks for your interest in contributing to multi-model-collab!

## Development Setup

```bash
git clone https://github.com/pure-maple/multi-model-collab.git
cd multi-model-collab/mcp/collab-hub

# Create virtual environment and install deps
uv sync

# Run lint
uv run ruff check src/
uv run ruff format --check src/

# Run unit tests
uv run python tests/test_detect.py

# Run e2e tests (requires codex/gemini/claude CLIs)
uv run python tests/test_e2e.py
```

## Adding a New Adapter

1. Create `src/collab_hub/adapters/your_adapter.py` extending `BaseAdapter`
2. Implement `_binary_name()`, `build_command()`, and `parse_output()`
3. Register it in `adapters/__init__.py`
4. Add tests

See existing adapters (`codex.py`, `gemini.py`, `claude.py`) as examples.

## Pull Requests

- Run `uv run ruff check src/ && uv run ruff format src/` before submitting
- Add tests for new functionality
- Keep PRs focused on a single change

## Reporting Issues

Open an issue at https://github.com/pure-maple/multi-model-collab/issues with:
- Your OS and Python version
- Which CLIs you have installed (codex, gemini, claude)
- Steps to reproduce the issue
