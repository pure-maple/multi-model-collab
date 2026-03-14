"""Web dashboard for vyane.

Provides a REST API and minimal web UI for monitoring:
- Active dispatches (real-time status)
- History and statistics
- Provider availability
- Cost tracking

Uses Starlette (already a transitive dependency via mcp[cli]).

Usage:
    vyane dashboard --port 41521
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route


def _clamp_int(raw: str, default: int, lo: int = 1, hi: int = 10000) -> int:
    """Parse and clamp an integer query param to [lo, hi]."""
    try:
        return max(lo, min(hi, int(raw)))
    except (ValueError, TypeError):
        return default


def _clamp_float(
    raw: str, default: float, lo: float = 0.0, hi: float = 8760.0
) -> float:
    """Parse and clamp a float query param to [lo, hi]."""
    try:
        return max(lo, min(hi, float(raw)))
    except (ValueError, TypeError):
        return default


async def api_status(request: Request) -> JSONResponse:
    """GET /api/status — list active dispatches."""
    from vyane.status import list_active

    active = list_active()
    return JSONResponse({"active": [asdict(s) for s in active], "count": len(active)})


async def api_history(request: Request) -> JSONResponse:
    """GET /api/history — query dispatch history."""
    from vyane.history import HistoryQuery, read_history

    limit = _clamp_int(request.query_params.get("limit", "20"), 20)
    provider = request.query_params.get("provider", "")
    hours = _clamp_float(request.query_params.get("hours", "0"), 0.0)
    status = request.query_params.get("status", "")

    entries = read_history(
        HistoryQuery(limit=limit, provider=provider, hours=hours, status=status)
    )
    return JSONResponse({"entries": entries, "count": len(entries)})


async def api_stats(request: Request) -> JSONResponse:
    """GET /api/stats — aggregated statistics."""
    from vyane.history import get_history_stats

    hours = _clamp_float(request.query_params.get("hours", "0"), 0.0)
    stats = get_history_stats(hours=hours, include_costs=True)
    return JSONResponse(stats)


async def api_providers(request: Request) -> JSONResponse:
    """GET /api/providers — provider availability and info."""
    from vyane.adapters import ADAPTERS, get_all_adapters
    from vyane.adapters.base import BaseAdapter

    all_adapters = get_all_adapters()
    providers = {}
    for name, adapter_or_cls in all_adapters.items():
        is_builtin = name in ADAPTERS
        is_custom = not is_builtin

        available = False
        binary = ""
        try:
            inst = (
                adapter_or_cls
                if isinstance(adapter_or_cls, BaseAdapter)
                else adapter_or_cls()
            )
            binary = inst._binary_name()
            available = inst.check_available()
        except Exception:
            available = False

        providers[name] = {
            "available": available,
            "binary": binary,
            "builtin": is_builtin,
            "custom": is_custom,
        }

    return JSONResponse({"providers": providers})


async def api_trends(request: Request) -> JSONResponse:
    """GET /api/trends — time-series data for charts."""
    from vyane.history import get_trends

    hours = _clamp_float(request.query_params.get("hours", "24"), 24.0, lo=0.1)
    bucket_minutes = _clamp_int(
        request.query_params.get("bucket", "60"), 60, lo=1, hi=1440
    )
    trends = get_trends(hours=hours, bucket_minutes=bucket_minutes)
    return JSONResponse(trends)


async def api_collaborations(request: Request) -> JSONResponse:
    """GET /api/collaborations — collaboration history with turn details."""
    from vyane.history import HistoryQuery, read_history

    limit = _clamp_int(request.query_params.get("limit", "10"), 10)
    hours = _clamp_float(request.query_params.get("hours", "0"), 0.0)

    entries = read_history(HistoryQuery(limit=limit, source="collaborate", hours=hours))
    # Each entry should have turns array from mux_collaborate
    collabs = []
    for e in entries:
        collabs.append(
            {
                "task_id": e.get("task_id", ""),
                "pattern": e.get("pattern", ""),
                "state": e.get("state", ""),
                "rounds": e.get("rounds", 0),
                "duration_seconds": e.get("duration_seconds", 0),
                "providers_used": e.get("providers_used", []),
                "turns": e.get("turns", []),
                "task": e.get("task", "")[:200],
                "ts": e.get("ts", 0),
            }
        )
    return JSONResponse({"collaborations": collabs, "count": len(collabs)})


async def api_feedback(request: Request) -> JSONResponse:
    """GET /api/feedback — feedback scores and recent entries."""
    from vyane.feedback import feedback_scores, read_feedback

    hours = _clamp_float(request.query_params.get("hours", "168"), 168.0, lo=1.0)
    entries = read_feedback(hours=hours)

    # Compute per-provider scores
    providers_seen = list({e.get("provider", "") for e in entries if e.get("provider")})
    scores = feedback_scores(providers_seen, hours=hours) if providers_seen else {}

    # Per-provider summary
    provider_summary: dict[str, dict] = {}
    for e in entries:
        prov = e.get("provider", "")
        if not prov:
            continue
        if prov not in provider_summary:
            provider_summary[prov] = {"count": 0, "total_rating": 0, "ratings": []}
        provider_summary[prov]["count"] += 1
        provider_summary[prov]["total_rating"] += e.get("rating", 0)
        provider_summary[prov]["ratings"].append(e.get("rating", 0))

    for prov, summary in provider_summary.items():
        summary["avg_rating"] = (
            round(summary["total_rating"] / summary["count"], 2)
            if summary["count"]
            else 0
        )
        summary["score"] = round(scores.get(prov, 0.5), 3)
        del summary["ratings"]  # don't send raw list

    return JSONResponse(
        {
            "total_entries": len(entries),
            "recent": entries[-20:],  # last 20 entries
            "by_provider": provider_summary,
            "hours": hours,
        }
    )


async def api_costs(request: Request) -> JSONResponse:
    """GET /api/costs — cost breakdown."""
    from vyane.costs import PRICING
    from vyane.history import get_history_stats

    hours = _clamp_float(request.query_params.get("hours", "0"), 0.0)
    stats = get_history_stats(hours=hours, include_costs=True)
    costs = stats.get("costs", {})
    return JSONResponse({"costs": costs, "pricing": PRICING})


def _collect_dashboard_data() -> dict:
    """Gather all dashboard data in one call (for SSE push)."""
    from vyane.history import HistoryQuery, get_history_stats, read_history
    from vyane.status import list_active

    active = list_active()
    stats = get_history_stats(hours=0, include_costs=True)
    entries = read_history(HistoryQuery(limit=15))

    return {
        "active": [asdict(s) for s in active],
        "stats": stats,
        "history": entries,
    }


async def api_events(request: Request) -> StreamingResponse:
    """GET /api/events — SSE stream pushing dashboard updates every 2s."""

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = _collect_dashboard_data()
                payload = json.dumps(data, ensure_ascii=False, default=str)
                yield f"data: {payload}\n\n"
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def index(request: Request) -> HTMLResponse:
    """GET / — serve the dashboard HTML."""
    return HTMLResponse(_DASHBOARD_HTML)


_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vyane Dashboard</title>
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
.collab-item { border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem; margin-bottom: 0.75rem; }
.collab-header { display: flex; justify-content: space-between; margin-bottom: 0.5rem; }
.collab-pattern { color: var(--accent); font-weight: 600; }
.collab-state { font-size: 0.8rem; }
.timeline { display: flex; gap: 2px; align-items: stretch; margin-top: 0.5rem; min-height: 32px; }
.turn-bar { flex: 1; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-size: 0.65rem; color: #fff; min-width: 40px; cursor: default; }
.turn-bar.success { background: #238636; }
.turn-bar.error { background: #da3633; }
.turn-bar.timeout { background: #9e6a03; }
</style>
</head>
<body>
<div style="display:flex;align-items:baseline;justify-content:space-between;">
  <div><h1>Vyane Dashboard</h1><p class="subtitle">Multi-model Collaboration Monitor</p></div>
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

  <div class="card">
    <h2>User Feedback</h2>
    <div id="feedback"><p class="loading">Loading...</p></div>
  </div>
</div>

<div class="grid" style="margin-top:1rem;">
  <div class="card">
    <h2>Dispatch Volume</h2>
    <canvas id="chart-volume" height="180"></canvas>
  </div>
  <div class="card">
    <h2>Success Rate & Latency</h2>
    <canvas id="chart-perf" height="180"></canvas>
  </div>
</div>

<div class="card" style="margin-top:1rem;">
  <h2>A2A Collaborations</h2>
  <div id="collabs"><p class="loading">Loading...</p></div>
</div>

<div class="card" style="margin-top:1rem;">
  <h2>Recent History</h2>
  <div id="history"><p class="loading">Loading...</p></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const $ = id => document.getElementById(id);
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

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
    h += `<tr><td>${esc(s.provider)}</td><td>${elapsed}s</td><td>${esc((s.task_summary||'').slice(0,60))}</td></tr>`;
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
    h += `<div class="stat"><span class="stat-label">${esc(name)}${tag}</span><span>${b}</span></div>`;
  }
  $('providers').innerHTML = h || '<p style="color:var(--text-dim)">No providers</p>';
}

async function refreshStats() {
  const d = await fetchJSON('/api/stats');
  if (!d || !d.total) { $('stats').innerHTML = '<p style="color:var(--text-dim)">No data</p>'; return; }
  let h = `<div class="stat"><span class="stat-label">Total dispatches</span><span class="stat-value">${d.total}</span></div>`;
  for (const [prov, ps] of Object.entries(d.by_provider || {})) {
    h += `<div class="stat"><span class="stat-label">${esc(prov)}</span>`;
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
    h += `<div class="stat"><span class="stat-label">${esc(prov)}</span><span>${pd.calls} calls, $${pd.total_cost.toFixed(4)}</span></div>`;
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
    h += `<tr><td>${t}</td><td>${esc(e.provider||'?')}</td>`;
    h += `<td style="${cls}">${icon}</td><td>${(e.duration_seconds||0).toFixed(1)}s</td>`;
    h += `<td>${esc((e.task||'').slice(0,60))}</td></tr>`;
  });
  h += '</table>';
  $('history').innerHTML = h;
}

async function refreshFeedback() {
  const d = await fetchJSON('/api/feedback?hours=168');
  if (!d || d.total_entries === 0) { $('feedback').innerHTML = '<p style="color:var(--text-dim)">No feedback yet. Use mux_feedback to rate results.</p>'; return; }
  let h = '';
  for (const [prov, info] of Object.entries(d.by_provider || {})) {
    const stars = '&#9733;'.repeat(Math.round(info.avg_rating)) + '&#9734;'.repeat(5 - Math.round(info.avg_rating));
    const scoreColor = info.score >= 0.7 ? 'var(--green)' : info.score >= 0.4 ? 'var(--yellow)' : 'var(--red)';
    h += `<div class="stat"><span class="stat-label">${esc(prov)} <span style="color:var(--yellow)">${stars}</span></span>`;
    h += `<span>${info.avg_rating}/5 (${info.count} ratings) <span style="color:${scoreColor};font-weight:600">score: ${info.score}</span></span></div>`;
  }
  h += `<div style="margin-top:0.5rem;font-size:0.75rem;color:var(--text-dim)">Last 7 days &middot; ${d.total_entries} total ratings</div>`;
  $('feedback').innerHTML = h;
}

let volumeChart = null, perfChart = null;

async function refreshTrends() {
  const d = await fetchJSON('/api/trends?hours=24&bucket=60');
  if (!d || !d.buckets || d.buckets.length === 0) return;

  const labels = d.buckets.map(b => new Date(b.ts * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));
  const counts = d.buckets.map(b => b.count);
  const successes = d.buckets.map(b => b.success);
  const errors = d.buckets.map(b => b.error);
  const rates = d.buckets.map(b => b.success_rate);
  const durations = d.buckets.map(b => b.avg_duration);

  const chartOpts = {responsive:true, animation:false, plugins:{legend:{labels:{color:'#8b949e',font:{size:11}}}}, scales:{x:{ticks:{color:'#8b949e',maxTicksLimit:12},grid:{color:'#30363d'}},y:{ticks:{color:'#8b949e'},grid:{color:'#30363d'}}}};

  if (volumeChart) { volumeChart.data.labels = labels; volumeChart.data.datasets[0].data = successes; volumeChart.data.datasets[1].data = errors; volumeChart.update(); }
  else { volumeChart = new Chart($('chart-volume'), {type:'bar', data:{labels, datasets:[{label:'Success',data:successes,backgroundColor:'#3fb950',stack:'s'},{label:'Error',data:errors,backgroundColor:'#f85149',stack:'s'}]}, options:{...chartOpts, scales:{...chartOpts.scales, y:{...chartOpts.scales.y, stacked:true}, x:{...chartOpts.scales.x, stacked:true}}}}); }

  if (perfChart) { perfChart.data.labels = labels; perfChart.data.datasets[0].data = rates; perfChart.data.datasets[1].data = durations; perfChart.update(); }
  else { perfChart = new Chart($('chart-perf'), {type:'line', data:{labels, datasets:[{label:'Success %',data:rates,borderColor:'#58a6ff',yAxisID:'y'},{label:'Avg Duration (s)',data:durations,borderColor:'#d29922',yAxisID:'y1'}]}, options:{...chartOpts, scales:{...chartOpts.scales, y:{...chartOpts.scales.y, position:'left',min:0,max:100}, y1:{ticks:{color:'#8b949e'},grid:{drawOnChartArea:false},position:'right',min:0}}}}); }
}

async function refreshCollabs() {
  const d = await fetchJSON('/api/collaborations?limit=5');
  if (!d || d.count === 0) { $('collabs').innerHTML = '<p style="color:var(--text-dim)">No collaborations yet</p>'; return; }
  let h = '';
  d.collaborations.forEach(c => {
    const t = c.ts ? new Date(c.ts*1000).toLocaleString() : '?';
    const stCls = c.state === 'completed' ? 'color:var(--green)' : c.state === 'failed' ? 'color:var(--red)' : 'color:var(--yellow)';
    h += `<div class="collab-item">`;
    h += `<div class="collab-header"><span><span class="collab-pattern">${esc(c.pattern)}</span> — ${esc(c.task.slice(0,80))}</span>`;
    h += `<span class="collab-state" style="${stCls}">${esc(c.state)} (${c.rounds} rounds, ${c.duration_seconds}s)</span></div>`;
    h += `<div style="font-size:0.75rem;color:var(--text-dim)">Providers: ${esc((c.providers_used||[]).join(', '))} | ${t}</div>`;
    if (c.turns && c.turns.length) {
      h += '<div class="timeline">';
      c.turns.forEach(turn => {
        const cls = turn.status === 'success' ? 'success' : turn.status === 'timeout' ? 'timeout' : 'error';
        h += `<div class="turn-bar ${cls}" title="${esc(turn.role)} (${esc(turn.provider)}) ${turn.duration}s\n${esc((turn.output_summary||'').slice(0,80))}">${esc(turn.role)}</div>`;
      });
      h += '</div>';
    }
    h += '</div>';
  });
  $('collabs').innerHTML = h;
}

async function refresh() {
  await Promise.all([refreshActive(), refreshProviders(), refreshStats(), refreshCosts(), refreshFeedback(), refreshHistory(), refreshTrends(), refreshCollabs()]);
}

// SSE real-time updates with polling fallback
let sseConnected = false;
function connectSSE() {
  const es = new EventSource('/api/events');
  es.onopen = () => {
    sseConnected = true;
    $('refresh-info').textContent = 'live (SSE)';
  };
  es.onmessage = (ev) => {
    try {
      const d = JSON.parse(ev.data);
      // Update active dispatches from SSE data
      if (d.active !== undefined) {
        const count = d.active.length;
        if (count === 0) { $('active').innerHTML = '<p style="color:var(--text-dim)">No active dispatches</p>'; }
        else {
          const now = Date.now()/1000;
          let h = '<table><tr><th>Provider</th><th>Elapsed</th><th>Task</th></tr>';
          d.active.forEach(s => {
            h += `<tr><td>${esc(s.provider)}</td><td>${(now - s.started_at).toFixed(1)}s</td><td>${esc((s.task_summary||'').slice(0,60))}</td></tr>`;
          });
          h += '</table>';
          $('active').innerHTML = h;
        }
      }
      // Update stats
      if (d.stats && d.stats.total) {
        let h = `<div class="stat"><span class="stat-label">Total dispatches</span><span class="stat-value">${d.stats.total}</span></div>`;
        for (const [prov, ps] of Object.entries(d.stats.by_provider || {})) {
          h += `<div class="stat"><span class="stat-label">${esc(prov)}</span><span>${ps.calls} calls, ${ps.success_rate}% ok, avg ${ps.avg_duration}s</span></div>`;
        }
        $('stats').innerHTML = h;
      }
      // Update history
      if (d.history && d.history.length) {
        let h = '<table><tr><th>Time</th><th>Provider</th><th>Status</th><th>Duration</th><th>Task</th></tr>';
        d.history.forEach(e => {
          const t = e.ts ? new Date(e.ts*1000).toLocaleTimeString() : '?';
          const icon = e.status === 'success' ? '&#x2713;' : '&#x2717;';
          const cls = e.status === 'success' ? 'color:var(--green)' : 'color:var(--red)';
          h += `<tr><td>${t}</td><td>${esc(e.provider||'?')}</td><td style="${cls}">${icon}</td><td>${(e.duration_seconds||0).toFixed(1)}s</td><td>${esc((e.task||'').slice(0,60))}</td></tr>`;
        });
        h += '</table>';
        $('history').innerHTML = h;
      }
    } catch {}
    // Refresh less-frequent panels at lower rate via SSE counter
    if (!window._sseCount) window._sseCount = 0;
    window._sseCount++;
    if (window._sseCount % 5 === 0) {
      refreshProviders(); refreshCosts(); refreshFeedback(); refreshTrends(); refreshCollabs();
    }
  };
  es.onerror = () => {
    sseConnected = false;
    es.close();
    $('refresh-info').textContent = 'auto-refresh: 5s (polling)';
    // Fall back to polling
    setInterval(refresh, 5000);
  };
}

// Initial full load, then try SSE
refresh();
if (typeof EventSource !== 'undefined') {
  connectSSE();
} else {
  setInterval(refresh, 5000);
}
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
            Route("/api/feedback", api_feedback),
            Route("/api/trends", api_trends),
            Route("/api/collaborations", api_collaborations),
            Route("/api/events", api_events),
        ],
    )


def run_dashboard(host: str = "127.0.0.1", port: int = 41521) -> None:
    """Start the dashboard server."""
    import uvicorn

    from vyane import __version__

    print(f"Vyane Dashboard v{__version__}")
    print(f"  http://{host}:{port}")
    print()

    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
