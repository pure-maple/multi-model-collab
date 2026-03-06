# Reef Local Tasks

## Active

- [x] Routing history cache: TTL cache for history/benchmark/feedback data (60s)
- [ ] Config validation: `load_config()` silently accepts invalid keys — add schema validation with warnings for unknown fields
- [x] mux_check provider latency: last_used_ago + avg_latency + success_rate per provider

## Backlog

- [ ] Test coverage: find untested code paths in recently changed files (feedback.py, routing.py v4 paths)
- [ ] Adapter cache thread safety: asyncio.Lock for adapter_cache in server.py (low priority — GIL makes it safe)
