"""
`acc ui` — a lightweight Textual dashboard over the pipeline.

Shows each stage's artifact freshness (✓ fresh / ⚠ stale / ✗ missing), runs any
stage with a single keypress (output streamed live), rebuilds the whole demo,
and serves the site locally. It is a thin front-end: every action calls the same
acc.cli command functions the `acc` CLI uses, so there is no logic duplication.
"""
import contextlib
import functools
import http.server
import io
import socketserver
import threading

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

try:  # widget was renamed across Textual versions
    from textual.widgets import RichLog as LogWidget
except ImportError:  # pragma: no cover
    from textual.widgets import TextLog as LogWidget

from . import cli, config
from .status import pipeline_status

_GLYPH = {"fresh": ("✓", "green"), "stale": ("⚠", "yellow"), "missing": ("✗", "red")}


class _LogWriter(io.TextIOBase):
    """Line-buffered stdout/stderr forwarder into the RichLog (thread-safe)."""

    def __init__(self, app, log):
        self.app, self.log, self._buf = app, log, ""

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.app.call_from_thread(self.log.write, escape(line))
        return len(s)

    def flush(self):
        if self._buf:
            self.app.call_from_thread(self.log.write, escape(self._buf))
            self._buf = ""


class DriftInspectorApp(App):
    TITLE = "Drift Inspector — pipeline"
    CSS = """
    #stages { height: auto; margin: 1 1 0 1; }
    #hint { color: $text-muted; margin: 0 1; }
    #log { height: 1fr; border: round $panel; margin: 1; }
    """
    BINDINGS = [
        ("e", "run('embed')", "Embed"),
        ("p", "run('project')", "Project"),
        ("b", "run('build-inspector')", "Build data"),
        ("k", "run('bake')", "Bake"),
        ("a", "run('all')", "Rebuild demo"),
        ("f", "run('figures')", "Figures"),
        ("s", "serve", "Serve"),
        ("r", "refresh_table", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    _httpd = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="stages", cursor_type="row", zebra_stripes=True)
        yield Static("e embed · p project · b build data · k bake · "
                     "a rebuild demo · f figures · s serve · r refresh · q quit",
                     id="hint")
        yield Vertical(LogWidget(id="log", highlight=True, markup=True))
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#stages", DataTable)
        table.add_columns(" ", "Stage", "State", "Size", "Produced by")
        self.refresh_table()
        self.query_one("#log", LogWidget).write("[dim]ready — pick a stage[/dim]")

    def refresh_table(self) -> None:
        table = self.query_one("#stages", DataTable)
        table.clear()
        for r in pipeline_status():
            mark, color = _GLYPH[r["state"]]
            size = f"{r['size']/1e6:.1f} MB" if r["size"] else "—"
            table.add_row(Text(mark, style=color), r["label"],
                          Text(r["state"], style=color), size, r["how"])

    def action_refresh_table(self) -> None:
        self.refresh_table()

    def action_run(self, cmd: str) -> None:
        log = self.query_one("#log", LogWidget)
        log.write(f"[b]› {cmd}[/b]")
        fn = {
            "embed": cli.cmd_embed, "project": cli.cmd_project,
            "build-inspector": cli.cmd_build_inspector, "bake": cli.cmd_bake,
            "all": cli.cmd_all, "figures": cli.cmd_figures,
        }[cmd]

        def task():
            writer = _LogWriter(self, log)
            try:
                with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                    fn(None)
                writer.flush()
                self.call_from_thread(log.write, f"[green]✓ {cmd} done[/green]")
            except Exception as exc:  # surface failures in the log, don't crash the UI
                writer.flush()
                self.call_from_thread(log.write, f"[red]✗ {cmd} failed: {exc}[/red]")
            self.call_from_thread(self.refresh_table)

        self.run_worker(task, thread=True, group="stage")

    def action_serve(self) -> None:
        log = self.query_one("#log", LogWidget)
        if self._httpd is not None:
            log.write("[yellow]already serving on :8000[/yellow]")
            return
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(config.INSPECTOR))
        self._httpd = socketserver.TCPServer(("", 8000), handler)
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()
        log.write("[green]serving → http://localhost:8000/[/green]")

    def on_unmount(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None


def run() -> None:
    DriftInspectorApp().run()
