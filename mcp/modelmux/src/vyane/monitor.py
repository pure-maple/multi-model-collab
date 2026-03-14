"""Vyane Monitor — real-time TUI for active dispatch tasks.

Launch with: vyane monitor  (legacy alias: modelmux monitor)
Requires: pip install vyane[tui]  (textual dependency)
"""

from __future__ import annotations

import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import DataTable, Footer, Header, Static

from vyane.status import list_active, read_status

# Status → display emoji
_STATUS_ICON = {
    "pending": "[dim]⏳[/]",
    "running": "[green]▶[/]",
    "success": "[green]✓[/]",
    "error": "[red]✗[/]",
    "timeout": "[yellow]⏱[/]",
    "cancelled": "[dim]⊘[/]",
    "paused": "[yellow]⏸[/]",
}


def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m{s:02d}s"


class TaskDetail(Static):
    """Bottom panel showing selected task detail."""

    selected_run_id: reactive[str] = reactive("")

    def watch_selected_run_id(self, run_id: str) -> None:
        if not run_id:
            self.update("[dim]Select a task to view details[/]")
            return
        status = read_status(run_id)
        if not status:
            self.update(f"[dim]Task {run_id} not found[/]")
            return
        lines = [
            f"[bold]Run ID:[/] {status.run_id}",
            f"[bold]Provider:[/] {status.provider}",
            f"[bold]Status:[/] {status.status}",
            f"[bold]Elapsed:[/] {_fmt_elapsed(status.elapsed_seconds)}",
        ]
        if status.paused:
            lines.append("[yellow][bold]⏸ PAUSED[/][/]")
        if status.failover_from:
            lines.append(f"[bold]Failover from:[/] {status.failover_from}")
        if status.error:
            lines.append(f"[bold red]Error:[/] {status.error[:300]}")
        if status.task_summary:
            lines.append(f"\n[bold]Task:[/]\n{status.task_summary}")
        if status.output_preview:
            preview = status.output_preview[:2000]
            lines.append(f"\n[bold]Output preview:[/]\n{preview}")
        self.update("\n".join(lines))


class VyaneMonitor(App):
    """Vyane real-time task monitor."""

    TITLE = "Vyane Monitor"
    CSS = """
    #task-table {
        height: 1fr;
        min-height: 8;
    }
    #detail-panel {
        height: 2fr;
        border-top: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
    ]

    _refresh_timer: Timer | None = None
    _selected_run_id: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="task-table")
        yield TaskDetail(id="detail-panel")
        yield Static("", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.add_columns("", "Run ID", "Provider", "Task", "Status", "Elapsed")
        table.cursor_type = "row"
        self._refresh_tasks()
        self._refresh_timer = self.set_interval(2.0, self._refresh_tasks)

    def _refresh_tasks(self) -> None:
        table = self.query_one("#task-table", DataTable)
        statuses = list_active()
        now = time.time()

        # Remember selection
        old_cursor = table.cursor_row

        table.clear()
        for s in statuses:
            elapsed = s.elapsed_seconds or (now - s.started_at if s.started_at else 0)
            icon = _STATUS_ICON.get(s.status, "?")
            if s.paused:
                icon = _STATUS_ICON["paused"]
            summary = (s.task_summary or "")[:50]
            table.add_row(
                icon,
                s.run_id,
                s.provider,
                summary,
                s.status,
                _fmt_elapsed(elapsed),
                key=s.run_id,
            )

        # Restore cursor position
        if statuses and old_cursor is not None:
            try:
                table.move_cursor(row=min(old_cursor, len(statuses) - 1))
            except Exception:
                pass

        # Update status bar
        running = sum(1 for s in statuses if s.status == "running")
        paused = sum(1 for s in statuses if s.paused)
        total = len(statuses)
        bar = f" {total} tasks"
        if running:
            bar += f" | [green]{running} running[/]"
        if paused:
            bar += f" | [yellow]{paused} paused[/]"
        bar += " | [dim]auto-refresh 2s[/]"
        self.query_one("#status-bar", Static).update(bar)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            self._selected_run_id = str(event.row_key.value)
            self.query_one(
                "#detail-panel", TaskDetail
            ).selected_run_id = self._selected_run_id

    def action_refresh(self) -> None:
        self._refresh_tasks()

    def action_cursor_down(self) -> None:
        self.query_one("#task-table", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#task-table", DataTable).action_cursor_up()


def run_monitor() -> None:
    """Entry point for ``vyane monitor`` / legacy ``modelmux monitor``."""
    app = VyaneMonitor()
    app.run()
