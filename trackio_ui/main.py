from importlib.resources import files
from datetime import datetime
import json, orjson, tempfile, click
from pathlib import Path
from fasthtml.common import *
from monsterui.all import *
from .utils import TrackioDatabase, prepare_metrics
from .components import *


# --- App Setup ---

headers = [
    Script(src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"),
    Script(src="/static/dashboard.js"),
    Script(src="https://unpkg.com/split.js/dist/split.min.js"),
    Script(src="https://cdn.jsdelivr.net/npm/@alpinejs/persist@3.x.x/dist/cdn.min.js", defer=True),
    Script(src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js", defer=True),
    Style("""
    [x-cloak] { display: none !important; }
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

default_project = ""


def get_db(project_name) -> TrackioDatabase:
    if project_name not in databases:
        databases[project_name] = TrackioDatabase(project_name)
    return databases[project_name]


# --- Routes ---


@rt("/")
def index():
    return Redirect(f"/{default_project or 'default_project'}")


@rt("/{project_name}/runs")
def get_runs_component(sess, project_name: str):
    db = get_db(project_name)
    return RunsListComponent(db.get_runs())


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
def project_dashboard(sess: dict, project_name: str):
    db = get_db(project_name)
    runs = db.get_runs()
    # prefs = sess.get(f"prefs_{project_name}", {})

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
            LabeledCheckbox("log-x axis", "log-x-axis", onchange="updateChartsAxisType()", cls_colors="checkbox-secondary"),
            LabeledCheckbox("log-y axis", "log-y-axis", onchange="updateChartsAxisType()", cls_colors="checkbox-secondary"),
            cls="flex flex-row flex-wrap gap-4 py-2",
        ),
        RunsListComponent(runs),
        cls="flex flex-col flex-1 min-h-0",
    )

    sidebar_footer = Div(
        Button(
            "Refresh",
            cls=(ButtonT.primary, "w-full", "mt-2"),
            hx_get=get_runs_component.to(project_name=project_name),
            hx_target="#runs-list-container",
            hx_swap="outerHTML",
        ),
        cls="shrink-0 p-4 border-t",
    )

    sidebar = Aside(
        sidebar_header,
        Form(
            controls,
            cls="flex flex-col flex-1 min-h-0 overflow-y-auto",
            hx_get=get_data.to(project_name=project_name),
            hx_trigger="change delay:500ms, load, submit",
            hx_swap="none",
            hx_on_htmx_after_request="updateDashboard(event)",
        ),
        sidebar_footer,
        id="sidebar",
        cls="h-full bg-card border-r flex flex-col shrink-0",
    )

    main_content = Main(
        Div(
            H3("Loading metrics...", cls="loading loading-dots loading-lg text-primary"),
            cls="m-auto loading-container",
        ),
        id="main-content",
        cls="relative flex-1 min-w-0 overflow-y-auto p-6 pr-8 bg-muted/10",
    )

    split_init = Script(
        "window.splitInstance = Split(['#sidebar', '#main-content'], {sizes: [20, 80], minSize: [250, 400], gutterSize: 8, cursor: 'col-resize', onDragEnd: function() { if(window.chartInstances) window.chartInstances.forEach(c => c.resize()); }});"
    )

    layout = Div(
        sidebar,
        main_content,
        split_init,
        cls="flex flex-1 min-h-0",
        id="layout-wrapper",
    )

    return (
        Title(f"trackio-ui {project_name}"),
        Div(
            ProjectHeader(project_name, "dashboard"),
            layout,
            cls="flex flex-col h-screen overflow-hidden",
        ),
    )


@rt("/{project_name}/data")
def get_data(
    sess,
    project_name: str,
    runs: list[str] | None = None,
    smoothing: float = 0.0,
    max_points: int = 0,
    refresh: bool = False,
):
    sess[f"prefs_{project_name}"] = {
        "selected_runs": runs or [],
        "smoothing": str(smoothing),
        "max_points": str(max_points),
        "refresh": bool(refresh),
    }
    if not runs:
        return json.dumps({"data": {}})

    db = get_db(project_name)
    raw_data = db.get_metrics(runs, refresh=bool(refresh))
    resp = orjson.dumps(
        {"data": prepare_metrics(raw_data, smoothing, max_points)},
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
    )
    return Response(content=resp, media_type="application/json")


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--project", default=None)
def main(host, port, project):
    global default_project
    default_project = project
    serve(host=host, port=port, reload=True, appname="trackio_ui.main")


if __name__ == "__main__":
    main()
