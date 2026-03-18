from importlib.resources import files
from datetime import datetime
import asyncio
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
]


databases = {}
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
def delete_runs_endpoint(project_name: str, selected_runs: list[str] | None = None):
    if selected_runs:
        db = get_db(project_name)
        db.delete_runs(selected_runs)

    return RunsTable(project_name, db.get_runs(names_only=False))


@rt("/{project_name}")
def project_dashboard(project_name: str, selected_runs: str | None = None):
    db = get_db(project_name)
    runs = db.get_runs()
    selected_runs = selected_runs.split(",") if selected_runs else []
    db.set_selected_runs(selected_runs)

    # Sidebar Construction
    sidebar_header = SidebarSection(
        None,
        H3(project_name, cls="font-bold text-lg text-primary truncate"),
        P("Trainer Tools", cls="text-xs text-muted-foreground"),
        Details(Summary("change theme"), ThemePicker()),
        cls="justify-center shrink-0",
    )

    controls = SidebarSection(
        H3("Controls"),
        LabelRange(
            label="Smoothing",
            name="smoothing",
            min="0",
            max="0.99",
            step="0.01",
            x_data=f"{{val: parseFloat(localStorage.getItem('smoothing') ?? '0.5')}}",
            x_init="$el.setAttribute('value', val)",
            **{"@uk-input-range:input.window": "localStorage.setItem('smoothing', $event.detail.value)"},
            cls="space-y-2",
        ),
        LabelInput(
            label="Max Points",
            name="max_points",
            type="number",
            x_data="{val: $persist('100000').as('max_points')}",
            x_model="val",
        ),
        Div(
            LabeledCheckbox("log-x Axis", "log-x-axis", cls_colors="checkbox-secondary"),
            LabeledCheckbox("log-y Axis", "log-y-axis", cls_colors="checkbox-secondary"),
            cls="flex flex-row flex-wrap gap-4 py-2",
            **{"@change": "Charts.setLogAxes($el.querySelector('#log-x-axis').checked, $el.querySelector('#log-y-axis').checked)"},
        ),
        (runs_list := RunsListComponent(runs)),
        cls="flex flex-col flex-1 min-h-0",
    )
    sidebar_footer = Div(
        Button(
            "Refresh",
            cls=(ButtonT.primary, "w-full", "mt-2"),
            hx_get=get_runs.to(project_name=project_name),
            hx_target=f"#{runs_list.id}",
            hx_swap="outerHTML",
        ),
        cls="shrink-0 p-4 border-t",
    )

    sidebar = Aside(
        sidebar_header,
        Form(
            controls,
            cls="flex flex-col flex-1 min-h-0 overflow-y-auto",
            hx_get=get_layout.to(project_name=project_name),
            hx_trigger="change delay:500ms, load",
            hx_target="#main-content",
            hx_swap="innerHTML",
        ),
        sidebar_footer,
        id="sidebar",
        cls="h-full bg-card border-r flex flex-col shrink-0",
        style="width: var(--sidebar-width)",
    )

    main_content = Main(
        ChartsContainer(db.get_metrics_schema(runs)),
        id="main-content",
        cls="relative flex-1 min-w-0 overflow-y-auto p-6 pr-8 bg-muted/10",
    )

    layout = Div(
        sidebar,
        ResizeHandle(),
        main_content,
        SSEListener(project_name, active=True),
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
def get_layout(project_name: str, runs: list[str] | None = None):
    db = get_db(project_name)
    runs = runs or []
    filtered_runs = [r for r in db.get_runs() if r in runs]
    db.set_selected_runs(filtered_runs)
    ck = cookie("selected_runs", filtered_runs, path=f"/{project_name}")
    return ChartsContainer(db.get_metrics_schema()), ck


@rt("/{project_name}/data")
def get_data(
    project_name: str,
    runs: list[str] | None = None,
    smoothing: float = 0.0,
    max_points: int = 0,
    refresh: bool = False,
):
    if not runs:
        return json.dumps({"data": {}})

    db = get_db(project_name)
    raw_data = db.get_metrics(runs, refresh=bool(refresh))
    resp = orjson.dumps(
        {"data": prepare_metrics(raw_data, smoothing, max_points)},
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
    )
    return Response(content=resp, media_type="application/json")


shutdown_event = signal_shutdown()


async def live_generator(project_name: str):
    db = get_db(project_name)
    while not shutdown_event.is_set():
        # TODO figure out what is going on
        # new_paths = db.get_metrics_schema(runs)
        # if new_paths:
        #     html = to_xml(ChartsContainer(new_paths))
        #     yield sse_message(html, event="layout_add")

        data = db.get_metrics()
        yield sse_json({"data": prepare_metrics(data, 0.5, 10_000)}, event="data_update")

        await asyncio.sleep(3)


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
