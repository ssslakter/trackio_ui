from importlib.resources import files
from datetime import datetime
import json, orjson, tempfile, click
from pathlib import Path
from fasthtml.common import *
from monsterui.all import *
from .utils import TrackioDatabase, prepare_metrics


def ProjectHeader(project_name, active_tab="dashboard"):
    """Navigation header to switch between views."""

    def Tab(name, href, active):
        cls = "border-b-2 px-4 py-2 text-sm font-medium transition-colors "
        cls += "border-primary text-primary" if active else "border-transparent text-muted-foreground hover:text-foreground"
        return A(name, href=href, cls=cls)

    return Div(
        H3(f"{project_name}", cls="text-lg font-bold px-4 py-2"),
        Div(
            Tab("Dashboard", f"/{project_name}", active=active_tab == "dashboard"),
            Tab("Runs Table", f"/{project_name}/table", active=active_tab == "runs"),
            cls="flex space-x-2 px-4 border-b bg-card",
        ),
        cls="flex flex-col w-full bg-card border-b",
    )


def RunsTable(runs, id='runs_table'):
    """Renders the MonsterUI table with dynamic columns."""
    if not runs:
        return Div("No runs found.", cls="p-10 text-center text-muted-foreground")

    for r in runs:
        r["Created"] = r.pop("_Created")
        r["Select"] = r["run_name"]
        del r["created_at"]

    all_keys = set().union(*(d.keys() for d in runs))
    fixed_cols = ["Select", "run_name", "Created"]
    ignore_cols = set([c for c in all_keys if c.split(".")[-1].startswith("_")] + fixed_cols)
    columns = fixed_cols + sorted([k for k in all_keys if k not in ignore_cols])

    def header_render(col):
        if col == "Select":
            return Th(CheckboxX(id="select-all-rows", onclick="toggleAll(this)"), shrink=True)
        return Th(col, cls="whitespace-nowrap")

    def cell_render(col, val):
        if col == "Select":
            return Td(CheckboxX(name="selected_runs", value=val, cls="row-checkbox"), shrink=True)
        return Td(str(val) if val is not None else "-", cls="whitespace-nowrap max-w-xs truncate")

    table = TableFromDicts(
        header_data=columns,
        body_data=runs,
        header_cell_render=header_render,
        body_cell_render=cell_render,
        cls=(TableT.sm, TableT.divider, TableT.hover),
    )
    table[0].attrs["class"] = "sticky top-0 bg-card"
    return Div(table, cls="overflow-auto flex-1 h-full w-full", id=id)


def LabeledToggle(label, id, name=None, checked=False, onchange=None, onclick=None, cls_colors="checkbox-primary"):
    """Generic component for a checkbox with a label."""
    return Div(
        CheckboxX(id=id, name=name or id, checked=checked, onchange=onchange, onclick=onclick, cls=f"checkbox checkbox-sm {cls_colors} mr-2"),
        Label(label, cls="font-semibold text-sm cursor-pointer", htmlFor=id),
        cls="flex items-center",
    )


def SidebarSection(*content, cls=""):
    """Container for logical groups in the sidebar."""
    return Div(*content, cls=f"p-4 border-b space-y-4 {cls}")


def RunEntry(run_name, is_checked):
    """Specific component for an individual run item in the list."""
    return Div(
        CheckboxX(
            name="runs",
            value=run_name,
            checked=is_checked,
            cls="checkbox checkbox-sm checkbox-primary mr-3",
        ),
        Span(run_name, cls="truncate text-sm"),
        cls="flex items-center hover:bg-muted/50 p-2 rounded-md cursor-pointer transition-colors",
    )


def RunsListComponent(runs, prefs):
    """The scrollable list of runs."""
    selected_runs = prefs.get("selected_runs", [])
    return Div(
        *[RunEntry(r, r in selected_runs) for r in (runs or [])],
        id="runs-list-container",
        cls="flex-1 overflow-y-auto p-4 space-y-1 min-h-0",
    )


# --- App Setup ---

headers = [
    Script(src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"),
    Script(src="/static/dashboard.js"),
    Script(src="https://unpkg.com/split.js/dist/split.min.js"),
    Theme.blue.headers(),
    Style(
        """
        .gutter { background-color: hsl(var(--border)); }
        .gutter.gutter-horizontal { cursor: col-resize; }
        .gutter.gutter-horizontal:hover { background-color: hsl(var(--primary)); }
        .sidebar-transition { transition: all 0.3s ease-in-out; }
        .sidebar-hidden #sidebar { width: 0px !important; min-width: 0px !important; overflow: hidden; border: none; }
        .sidebar-hidden .gutter { display: none; }
        #sidebar-toggle { position: absolute; bottom: 20px; left: 20px; z-index: 50; }

        .chart-modal-backdrop {
            position: fixed;
            top: 0; left: 0;
            width: 100vw; height: 100vh;
            background-color: rgba(0, 0, 0, 0.5);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.2s ease-in-out, visibility 0.2s ease-in-out;
        }
        .chart-modal-backdrop.is-visible {
            opacity: 1;
            visibility: visible;
        }
        .chart-modal-content {
            background-color: hsl(var(--card));
            color: hsl(var(--card-foreground));
            width: 90vw;
            height: 85vh;
            border-radius: 0.5rem;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1);
            display: flex;
            flex-direction: column;
            padding: 1rem;
        }
        .modal-chart-container {
            flex-grow: 1;
            min-height: 0; /* Important for flexbox sizing */
        }
    """
    ),
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
    db, prefs = get_db(project_name), sess.get(f"prefs_{project_name}", {})
    return RunsListComponent(db.get_runs(), prefs)


@rt("/{project_name}/table")
def runs_table_view(project_name: str):
    db = get_db(project_name)
    runs = db.get_runs(names_only=False)

    actions_bar = Div(
        Button(
            Div(UkIcon(icon="trash-2", cls="mr-2"), "Delete Selected", cls='flex items-center'),
            cls=ButtonT.destructive,
            hx_post=f"/{project_name}/delete_runs",
            hx_confirm="Are you sure you want to delete the selected runs?",
            hx_target="#table-container",
        ),
        cls="p-4 border-b bg-muted/20 flex gap-2",
    )

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
        Form(
            actions_bar,
            Div(RunsTable(runs), id="table-container", cls="flex-1 min-h-0 overflow-hidden relative"),
            cls="flex-1 flex flex-col min-h-0",
        ),
        script,
        cls="h-screen w-full flex flex-col",
    )


@rt("/{project_name}/delete_runs")
def delete_runs_endpoint(project_name: str, selected_runs: list[str] = None):
    if selected_runs:
        db = get_db(project_name)
        db.delete_runs(selected_runs)

    return RunsTable(db.get_runs(names_only=False))


@rt("/{project_name}")
def project_dashboard(sess: dict, project_name: str):
    db = get_db(project_name)
    runs = db.get_runs()
    prefs = sess.get(f"prefs_{project_name}", {})

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
        LabelRange(label="Smoothing", name="smoothing", min="0", max="0.99", step="0.01", value=prefs.get("smoothing", "0.6"), cls="space-y-2"),
        LabelInput(
            label="Max Points",
            name="max_points",
            type="number",
            value=prefs.get("max_points", "100000"),
        ),
        LabeledToggle("no cache", "refresh-checkbox", name="refresh", checked=prefs.get("refresh", False), cls_colors="checkbox-accent"),
        Div(
            LabeledToggle("log-x axis", "log-x-axis", onchange="updateChartsAxisType()", cls_colors="checkbox-secondary"),
            LabeledToggle("log-y axis", "log-y-axis", onchange="updateChartsAxisType()", cls_colors="checkbox-secondary"),
            cls="flex flex-row flex-wrap gap-4 py-2",
        ),
        LabeledToggle(
            "Select All Runs",
            "select-all",
            onclick="let c = this.checked; document.querySelectorAll('input[name=runs]').forEach(el => el.checked = c); htmx.trigger(this.closest('form'), 'change')",
        ),
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

    sidebar = Div(
        sidebar_header,
        Form(
            Div(Div(controls, cls="shrink-0"), RunsListComponent(runs, prefs), sidebar_footer, cls="flex flex-col flex-1 min-h-0"),
            cls="flex flex-col flex-1 min-h-0",
            hx_get=get_data.to(project_name=project_name),
            hx_trigger="change delay:500ms, load, submit",
            hx_swap="none",
            hx_on_htmx_after_request="updateDashboard(event)",
        ),
        id="sidebar",
        cls="h-full bg-card border-r flex flex-col sidebar-transition shrink-0 overflow-hidden",
    )

    main_content = Div(
        Button(id="sidebar-toggle", cls="btn btn-circle btn-sm btn-secondary shadow-lg fixed bottom-6 left-6 z-[100]", onclick="toggleSidebar()"),
        Div(
            Div(
            Div(H3("Loading metrics...", cls="loading loading-dots loading-lg text-primary"), cls="m-auto loading-container"),
            id="charts-container",
            cls="p-6 pr-8 bg-muted/10 flex flex-col w-full",
        ),
        cls="flex-1 h-full w-full overflow-y-auto transform-gpu"),
        id="main-content",
        cls="relative flex-1 sidebar-transition min-w-0",
    )

    split_init = Script(
        "window.splitInstance = Split(['#sidebar', '#main-content'], {sizes: [20, 80], minSize: [250, 400], gutterSize: 8, cursor: 'col-resize', onDragEnd: function() { if(window.chartInstances) window.chartInstances.forEach(c => c.resize()); }});"
    )

    layout = Div(
        sidebar,
        main_content,
        split_init,
        cls="flex flex-1 flex-row w-full overflow-hidden text-foreground",
        id="layout-wrapper",
    )

    return Title(f"{project_name}"), Div(ProjectHeader(project_name, "dashboard"), layout, cls="flex flex-col h-screen w-full")


@rt("/{project_name}/data")
def get_data(sess, project_name: str, runs: list[str] = None, smoothing: float = 0.0, max_points: int = 0, refresh: bool = False):
    sess[f"prefs_{project_name}"] = {"selected_runs": runs or [], "smoothing": str(smoothing), "max_points": str(max_points), "refresh": bool(refresh)}
    if not runs:
        return json.dumps({"data": {}})

    db = get_db(project_name)
    raw_data = db.get_metrics(runs, refresh=bool(refresh))
    resp = orjson.dumps({"data": prepare_metrics(raw_data, smoothing, max_points)}, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)
    return Response(content=resp, media_type="application/json")


@click.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8000, type=int)
@click.option("--project", default=None)
def main(host, port, project):
    global default_project
    default_project = project
    serve(host=host, port=port, reload=False, appname="trackio_ui.main")


if __name__ == "__main__":
    main()
