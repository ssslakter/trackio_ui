from importlib.resources import files
from datetime import datetime
import asyncio
from asyncio import Queue
import json, orjson, tempfile, click
from pathlib import Path
from fasthtml.common import *
from monsterui.all import *
from .data import TrackioDatabase, prepare_metrics
from .components import *
from .utils import *


# --- App Setup ---

headers = [
    Script("""
  (function() {
    const w = localStorage.getItem('sidebarWidth');
    if (w) document.documentElement.style.setProperty('--sidebar-width', w);
  })();
    """),
    ResizeScript(),
    Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js"),
    Script(src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"),
    Script(src="/static/sse.js"),
    Script(src="/static/charts.js"),
    Script(src="https://cdn.jsdelivr.net/npm/@alpinejs/persist@3.x.x/dist/cdn.min.js", defer=True),
    Script(src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js", defer=True),
    Style("""
    [x-cloak] { display: none !important; }
    """),
    Style("""
  #sidebar { width: var(--sidebar-width, 280px); }
  #layout-wrapper { --sidebar-width: 280px; }
    """),
    Theme.blue.headers(),
    Style("""
    /* number input spinners follow the page color-scheme (light/dark) */
    html:not(.dark) { color-scheme: light; }
    html.dark        { color-scheme: dark;  }
    """),
]


databases = {}
sse_run_queues: dict[str, Queue] = {}
app, rt = fast_app(
    hdrs=headers,
    static_path=files("trackio_ui"),
    secret_key="secret",
    key_fname=Path(tempfile.gettempdir()) / ".trackio_ui_sesskey",
    bodykw={"hx-boost": "true"},
)

default_project = os.getenv("TRACKIO_DEFAULT_PROJECT", "")


def get_db(project_name) -> TrackioDatabase:
    if project_name not in databases:
        databases[project_name] = TrackioDatabase(project_name)
    return databases[project_name]


# --- Routes ---


@rt("/")
def index():
    print("Default project:", default_project)
    return Redirect(f"/{default_project or 'default_project'}")


@rt("/{project_name}/runs")
def get_runs(sess, project_name: str):
    runs = get_db(project_name).get_runs()
    return RunsListComponent(runs)


@rt("/{project_name}/table")
def runs_table_view(project_name: str):
    db = get_db(project_name)
    runs = db.get_runs(names_only=False)

    script = Script(
        """
        function toggleAll(source) {
            checkboxes = document.getElementsByClassName('row-checkbox');
            for(var i=0, n=checkboxes.length;i<n;i++) {
                checkboxes[i].checked = source.checked;
            }
        }
    """
    )

    return Title(f"{project_name} - Runs"), Div(
        ProjectHeader(project_name, "runs"),
        RunsTable(project_name, runs),
        script,
        cls="h-screen w-full flex flex-col",
    )


@rt("/{project_name}/delete_runs")
def delete_runs_endpoint(project_name: str, selected_runs: list[str]):
    if selected_runs:
        db = get_db(project_name)
        db.delete_runs(selected_runs)
    runs = db.get_runs()
    return RunsTable(project_name, db.get_runs(names_only=False))


@rt("/{project_name}")
def project_dashboard(project_name: str):
    db = get_db(project_name)
    runs = db.get_runs()

    # Sidebar Construction
    sidebar_header = SidebarSection(
        None,
        H3(project_name, cls="font-bold text-lg text-primary truncate"),
        Details(Summary("change theme"), ThemePicker()),
        cls="justify-center shrink-0",
    )
    main_id = "#main-content"

    controls_form = Form(
        P("Controls", cls="text-xs font-bold uppercase tracking-widest opacity-50"),
        SliderInput(
            name="smoothing",
            label="Smoothing",
            min="0",
            max="0.99",
            step="0.01",
            default="0.5",
        ),
        LabelInput(
            label="Max Points",
            name="max_points",
            type="number",
            x_data="{val: $persist('100000').as('max_points')}",
            x_model="val",
            **{"@keydown.enter.prevent": "$el.querySelector('input')?.blur() ?? $el.blur()"},
        ),
        Div(
            LabeledCheckbox("log-x Axis", "log-x-axis", cls_colors="checkbox-secondary", x_model="logX"),
            LabeledCheckbox("log-y Axis", "log-y-axis", cls_colors="checkbox-secondary", x_model="logY"),
            cls="flex flex-row flex-wrap gap-4",
            x_data="{ logX: false, logY: false }",
            **{"@change": "Charts.setLogAxes(logX, logY)"},
        ),
        id="controls-form",
        hx_post=get_charts.to(project_name=project_name),
        hx_trigger="change",
        hx_swap="none",
        hx_include="#runs-form",
        cls="flex flex-col gap-3 shrink-0",
    )

    runs_list = RunsListComponent(runs)
    runs_form = Form(
        runs_list,
        id="runs-form",
        hx_post=get_charts.to(project_name=project_name),
        hx_trigger="change delay:500ms, load",
        hx_target=main_id,
        hx_swap="innerHTML",
        hx_include=f"#{controls_form.id}",
        cls="flex flex-col flex-1 min-h-0",
    )

    controls_section = SidebarSection(
        controls_form,
        runs_form,
        cls="flex flex-col min-h-0 overflow-hidden",
    )

    sidebar_footer = Div(
        Button(
            "Refresh runs",
            cls=(ButtonT.primary, "w-full", "mt-2"),
            hx_get=get_runs.to(project_name=project_name),
            hx_target=f"#{runs_list.id}",
            hx_swap="outerHTML",
        ),
        cls="p-4 border-t bg-card",
    )

    sidebar = Aside(
        sidebar_header,
        controls_section,
        sidebar_footer,
        id="sidebar",
        cls="h-full bg-card border-r grid shrink-0",
        style="width: var(--sidebar-width); grid-template-rows: auto 1fr auto;",
    )

    main_content = Main(
        Div("Loading", id="charts-container"),
        id=main_id[1:],
        cls="relative flex-1 min-w-0 overflow-y-auto p-6 pr-8 bg-muted/10",
    )

    layout = Div(
        sidebar,
        ResizeHandle(),
        main_content,
        Script("{}", type="application/json", id="chart-data-payload"),
        ChartModal(),
        SSEListener(project_name) if False else None,
        cls="flex flex-1 min-h-0",
        id="layout-wrapper",
        style="--sidebar-width: 300px;",
    )

    return (
        Title(f"trackio-ui {project_name}"),
        Div(
            ProjectHeader(project_name, "dashboard"),
            layout,
            cls="flex flex-col h-screen overflow-hidden",
        ),
    )


@rt("/{project_name}/layout")
def get_charts(
    project_name: str,
    runs: list[str] | None = None,
    smoothing: float = 0.0,
    max_points: int = 0,
    current_schema: list[str] | None = None,
):
    db = get_db(project_name)
    runs = runs or []
    filtered_runs = [r for r in db.get_runs() if r in runs]
    if project_name in sse_run_queues:
        sse_run_queues[project_name].put_nowait(filtered_runs)
    metrics, new_schema = db.get_metrics_and_schema(filtered_runs)
    data = prepare_metrics(metrics, smoothing=smoothing, max_points=max_points)
    schema_changed = set(current_schema or []) != set(new_schema)
    data_json = orjson.dumps(
        {"data": data, "runs": filtered_runs, "schema_changed": schema_changed}, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS
    ).decode()
    data_island = Script(data_json, type="application/json", id="chart-data-payload", hx_swap_oob="true")

    if not schema_changed:
        return data_island, HtmxResponseHeaders(reswap="none")
    return ChartsContainer(new_schema), data_island


shutdown_event = signal_shutdown()


async def live_generator(project_name: str):
    db = get_db(project_name)
    q: Queue = Queue()
    sse_run_queues[project_name] = q
    current_runs: list[str] = []
    try:
        while not shutdown_event.is_set():
            while not q.empty():
                current_runs = q.get_nowait()
            if current_runs:
                data = db.get_metrics(current_runs, refresh=True)
                yield sse_json({"data": prepare_metrics(data, 0.5, 10_000)}, event="data_update")
            await asyncio.sleep(3)
    finally:
        sse_run_queues.pop(project_name, None)


@rt("/{project_name}/live")
async def live_stream(project_name: str):
    return EventStream(live_generator(project_name))


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--project", default=None)
def main(host, port, project):
    if project:
        os.environ["TRACKIO_DEFAULT_PROJECT"] = project
    serve(host=host, port=port, reload=True, appname="trackio_ui.main")


if __name__ == "__main__":
    main()
