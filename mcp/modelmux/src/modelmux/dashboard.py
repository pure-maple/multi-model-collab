"""Web dashboard for modelmux.

Provides a REST API and minimal web UI for monitoring:
- Active dispatches (real-time status)
- History and statistics
- Provider availability
- Cost tracking

Uses Starlette (already a transitive dependency via mcp[cli]).

Usage:
    modelmux dashboard --port 41521
"""

from __future__ import annotations

import shutil
from dataclasses import asdict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route


async def api_status(request: Request) -> JSONResponse:
    """GET /api/status — list active dispatches."""
    from modelmux.status import list_active

    active = list_active()
    return JSONResponse(
        {"active": [asdict(s) for s in active], "count": len(active)}
    )


async def api_history(request: Request) -> JSONResponse:
    """GET /api/history — query dispatch history."""
    from modelmux.history import HistoryQuery, read_history

    limit = int(request.query_params.get("limit", "20"))
    provider = request.query_params.get("provider", "")
    hours = float(request.query_params.get("hours", "0"))
    status = request.query_params.get("status", "")

    entries = read_history(
        HistoryQuery(limit=limit, provider=provider, hours=hours, status=status)
    )
    return JSONResponse({"entries": entries, "count": len(entries)})


async def api_stats(request: Request) -> JSONResponse:
    """GET /api/stats — aggregated statistics."""
    from modelmux.history import get_history_stats

    hours = float(request.query_params.get("hours", "0"))
    stats = get_history_stats(hours=hours, include_costs=True)
    return JSONResponse(stats)


async def api_providers(request: Request) -> JSONResponse:
    """GET /api/providers — provider availability and info."""
    from modelmux.adapters import ADAPTERS, get_all_adapters

    all_adapters = get_all_adapters()
    providers = {}
    for name, adapter_or_cls in all_adapters.items():
        is_builtin = name in ADAPTERS
        is_custom = not is_builtin

        # Check binary availability for CLI-based adapters
        available = False
        binary = ""
        try:
            if hasattr(adapter_or_cls, "_binary_name"):
                if callable(adapter_or_cls._binary_name):
                    # It's a class, instantiate to call
                    inst = (
                        adapter_or_cls()
                        if isinstance(adapter_or_cls, type)
                        else adapter_or_cls
                    )
                    binary = inst._binary_name()
                    available = shutil.which(binary) is not None
                else:
                    binary = adapter_or_cls._binary_name
                    available = shutil.which(binary) is not None
            else:
                # A2A remote adapters are "available" if configured
                available = True
        except Exception:
            available = False

        providers[name] = {
            "available": available,
            "binary": binary,
            "builtin": is_builtin,
            "custom": is_custom,
        }

    return JSONResponse({"providers": providers})


async def api_costs(request: Request) -> JSONResponse:
    """GET /api/costs — cost breakdown."""
    from modelmux.costs import PRICING
    from modelmux.history import get_history_stats

    hours = float(request.query_params.get("hours", "0"))
    stats = get_history_stats(hours=hours, include_costs=True)
    costs = stats.get("costs", {})
    return JSONResponse({"costs": costs, "pricing": PRICING})


async def index(request: Request) -> HTMLResponse:
    """GET / — serve the dashboard HTML."""
    return HTMLResponse(_DASHBOARD_HTML)


_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>modelmux Dashboard</title>
<style>
:root {
  --bg: #0d1117; --surface: #161b22; --border: #30363d;
  --text: #e6edf3; --text-dim: #8b949e; --accent: #58a6ff;
  --green: #3fb950; --red: #f85149; --yellow: #d29922;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); padding: 1.5rem; line-height: 1.5;
}
h1 { font-size: 1.5rem; margin-bottom: 0.25rem; }
.subtitle { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 1rem;
}
.card h2 { font-size: 1rem; color: var(--accent); margin-bottom: 0.75rem; }
.stat { display: flex; justify-content: space-between; padding: 0.3rem 0; border-bottom: 1px solid var(--border); }
.stat:last-child { border-bottom: none; }
.stat-label { color: var(--text-dim); }
.stat-value { font-weight: 600; }
.badge {
  display: inline-block; padding: 0.1rem 0.5rem; border-radius: 12px;
  font-size: 0.75rem; font-weight: 600;
}
.badge-ok { background: #23312a; color: var(--green); }
.badge-err { background: #311d1d; color: var(--red); }
.badge-na { background: #2a2418; color: var(--yellow); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: left; color: var(--text-dim); padding: 0.4rem 0.5rem; border-bottom: 2px solid var(--border); }
td { padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--border); }
.loading { color: var(--text-dim); font-style: italic; }
#refresh-info { color: var(--text-dim); font-size: 0.75rem; float: right; }
</style>
</head>
<body>
<div style="display:flex;align-items:baseline;justify-content:space-between;">
  <div><h1>modelmux Dashboard</h1><p class="subtitle">Model Multiplexer Monitor</p></div>
  <span id="refresh-info">auto-refresh: 5s</span>
</div>

<div class="grid">
  <div class="card">
    <h2>Active Dispatches</h2>
    <div id="active"><p class="loading">Loading...</p></div>
  </div>

  <div class="card">
    <h2>Provider Status</h2>
    <div id="providers"><p class="loading">Loading...</p></div>
  </div>

  <div class="card">
    <h2>Statistics</h2>
    <div id="stats"><p class="loading">Loading...</p></div>
  </div>

  <div class="card">
    <h2>Cost Summary</h2>
    <div id="costs"><p class="loading">Loading...</p></div>
  </div>
</div>

<div class="card" style="margin-top:1rem;">
  <h2>Recent History</h2>
  <div id="history"><p class="loading">Loading...</p></div>
</div>

<script>
const $ = id => document.getElementById(id);

async function fetchJSON(url) {
  try { const r = await fetch(url); return await r.json(); }
  catch { return null; }
}

function badge(ok) {
  if (ok === true) return '<span class="badge badge-ok">OK</span>';
  if (ok === false) return '<span class="badge badge-err">N/A</span>';
  return '<span class="badge badge-na">?</span>';
}

async function refreshActive() {
  const d = await fetchJSON('/api/status');
  if (!d) { $('active').innerHTML = '<p class="loading">Error</p>'; return; }
  if (d.count === 0) { $('active').innerHTML = '<p style="color:var(--text-dim)">No active dispatches</p>'; return; }
  let h = '<table><tr><th>Provider</th><th>Elapsed</th><th>Task</th></tr>';
  const now = Date.now()/1000;
  d.active.forEach(s => {
    const elapsed = (now - s.started_at).toFixed(1);
    h += `<tr><td>${s.provider}</td><td>${elapsed}s</td><td>${(s.task_summary||'').slice(0,60)}</td></tr>`;
  });
  h += '</table>';
  $('active').innerHTML = h;
}

async function refreshProviders() {
  const d = await fetchJSON('/api/providers');
  if (!d) return;
  let h = '';
  for (const [name, info] of Object.entries(d.providers)) {
    const b = badge(info.available);
    const tag = info.custom ? ' <span style="color:var(--text-dim);font-size:0.75rem">(custom)</span>' : '';
    h += `<div class="stat"><span class="stat-label">${name}${tag}</span><span>${b}</span></div>`;
  }
  $('providers').innerHTML = h || '<p style="color:var(--text-dim)">No providers</p>';
}

async function refreshStats() {
  const d = await fetchJSON('/api/stats');
  if (!d || !d.total) { $('stats').innerHTML = '<p style="color:var(--text-dim)">No data</p>'; return; }
  let h = `<div class="stat"><span class="stat-label">Total dispatches</span><span class="stat-value">${d.total}</span></div>`;
  for (const [prov, ps] of Object.entries(d.by_provider || {})) {
    h += `<div class="stat"><span class="stat-label">${prov}</span>`;
    h += `<span>${ps.calls} calls, ${ps.success_rate}% ok, avg ${ps.avg_duration}s</span></div>`;
  }
  $('stats').innerHTML = h;
}

async function refreshCosts() {
  const d = await fetchJSON('/api/costs');
  if (!d || !d.costs || !d.costs.entries_with_usage) {
    $('costs').innerHTML = '<p style="color:var(--text-dim)">No cost data</p>'; return;
  }
  const c = d.costs;
  let h = `<div class="stat"><span class="stat-label">Total cost</span><span class="stat-value">$${c.total_cost_usd.toFixed(4)}</span></div>`;
  h += `<div class="stat"><span class="stat-label">Tokens</span><span>${c.total_input_tokens.toLocaleString()} in / ${c.total_output_tokens.toLocaleString()} out</span></div>`;
  for (const [prov, pd] of Object.entries(c.by_provider || {})) {
    h += `<div class="stat"><span class="stat-label">${prov}</span><span>${pd.calls} calls, $${pd.total_cost.toFixed(4)}</span></div>`;
  }
  $('costs').innerHTML = h;
}

async function refreshHistory() {
  const d = await fetchJSON('/api/history?limit=15');
  if (!d || d.count === 0) { $('history').innerHTML = '<p style="color:var(--text-dim)">No history</p>'; return; }
  let h = '<table><tr><th>Time</th><th>Provider</th><th>Status</th><th>Duration</th><th>Task</th></tr>';
  d.entries.forEach(e => {
    const t = e.ts ? new Date(e.ts*1000).toLocaleTimeString() : '?';
    const icon = e.status === 'success' ? '&#x2713;' : '&#x2717;';
    const cls = e.status === 'success' ? 'color:var(--green)' : 'color:var(--red)';
    h += `<tr><td>${t}</td><td>${e.provider||'?'}</td>`;
    h += `<td style="${cls}">${icon}</td><td>${(e.duration_seconds||0).toFixed(1)}s</td>`;
    h += `<td>${(e.task||'').slice(0,60)}</td></tr>`;
  });
  h += '</table>';
  $('history').innerHTML = h;
}

async function refresh() {
  await Promise.all([refreshActive(), refreshProviders(), refreshStats(), refreshCosts(), refreshHistory()]);
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def create_app() -> Starlette:
    """Create the dashboard Starlette application."""
    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/status", api_status),
            Route("/api/history", api_history),
            Route("/api/stats", api_stats),
            Route("/api/providers", api_providers),
            Route("/api/costs", api_costs),
        ],
    )


def run_dashboard(host: str = "127.0.0.1", port: int = 41521) -> None:
    """Start the dashboard server."""
    import uvicorn

    from modelmux import __version__

    print(f"modelmux Dashboard v{__version__}")
    print(f"  http://{host}:{port}")
    print()

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
