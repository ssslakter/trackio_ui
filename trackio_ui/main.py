from importlib.resources import files
import json, orjson, tempfile
import click
from fasthtml.common import *
from monsterui.all import *
from .utils import TrackioDatabase, prepare_metrics

# TODO refactor this into a proper web app, as well as JS
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
    """
    ),
    Style(
        """
        .sidebar-transition { transition: all 0.3s ease-in-out; }
        .sidebar-hidden #sidebar { 
            width: 0px !important; 
            min-width: 0px !important; 
            overflow: hidden; 
            border: none;
        }
        .sidebar-hidden .gutter { display: none; }
        #sidebar-toggle {
            position: absolute;
            bottom: 20px;
            left: 20px;
            z-index: 50;
        }
    """
    ),
]

databases = {}
app, rt = fast_app(hdrs=headers, 
                   static_path=files("trackio_ui"), 
                   secret_key="secret", 
                   key_fname=Path(tempfile.gettempdir()) / ".trackio_ui_sesskey")

default_project = ""


def get_db(project_name) -> TrackioDatabase:
    if project_name not in databases:
        databases[project_name] = TrackioDatabase(project_name)
    return databases[project_name]

@rt
def index():
    project_name = default_project or "default_project"
    return Redirect(f"/{project_name}")

@rt("/{project_name}")
def index(sess: dict, project_name: str):
    db = get_db(project_name)
    runs = db.get_runs()
    prefs = sess.get(f"prefs_{project_name}", {})

    sidebar = Div(
        Div(
            H3(project_name, cls="font-bold text-lg text-primary truncate"),
            P("Trainer Tools", cls="text-xs text-muted-foreground"),
            cls="p-4 border-b flex flex-col justify-center",
        ),
        Details(Summary("change theme"), ThemePicker()),
        Form(
            DivVStacked(
                LabelRange(
                    label="Smoothing",
                    name="smoothing",
                    min="0",
                    max="0.99",
                    step="0.01",
                    value=prefs.get("smoothing", "0.6"),
                    cls="w-full",
                ),
                LabelRange(
                    label="Downsample",
                    name="downsample",
                    min="1",
                    max="100",
                    step="1",
                    value=prefs.get("downsample", "1"),
                    cls="w-full",
                ),
                Div(
                    CheckboxX(
                        id="select-all",
                        cls="checkbox checkbox-sm checkbox-primary mr-2",
                        onclick="let c = this.checked; document.querySelectorAll('input[name=runs]').forEach(el => el.checked = c); htmx.trigger(this.closest('form'), 'change')",
                    ),
                    Label("Select All Runs", cls="font-semibold text-sm cursor-pointer", htmlFor="select-all"),
                    cls="flex items-center pt-2",
                ),
                Div(
                    CheckboxX(
                        name="refresh",
                        id="refresh-checkbox",
                        value="1",
                        checked=prefs.get("refresh", False),
                        cls="checkbox checkbox-sm checkbox-accent mr-2",
                    ),
                    Label("Refresh (no cache)", cls="font-semibold text-sm cursor-pointer", htmlFor="refresh-checkbox"),
                    cls="flex items-center pt-2",
                ),
                cls="p-6 border-b space-y-4",
            ),
            Div(
                *[
                    Div(
                        CheckboxX(
                            name="runs",
                            value=r,
                            checked=(r in prefs.get("selected_runs", [])),
                            cls="checkbox checkbox-sm checkbox-primary mr-3",
                        ),
                        Span(r, cls="truncate text-sm"),
                        cls="flex items-center hover:bg-muted/50 p-2 rounded-md cursor-pointer transition-colors",
                    )
                    for r in runs
                ],
                cls="flex-1 overflow-y-auto p-4 space-y-1",
            ),
            Div(
                Button(
                    "Submit",
                    type="submit",
                    cls="btn btn-primary w-full mt-2",
                    hx_get=f"/{project_name}/data",
                    hx_trigger="click",
                    hx_swap="none",
                    hx_on_htmx_after_request="updateDashboard(event)",
                ),
                cls="p-4 border-t"
            ),
            cls="flex flex-col h-[calc(100%-4rem)]",
            hx_get=f"/{project_name}/data",
            hx_trigger="change delay:500ms, load",
            hx_swap="none",
            hx_on_htmx_after_request="updateDashboard(event)",
        ),
        id="sidebar",
        cls="h-screen bg-card border-r flex flex-col sidebar-transition shrink-0",
    )

    charts = Div(
        Button(
            id="sidebar-toggle",
            cls="btn btn-circle btn-sm btn-secondary shadow-lg fixed bottom-6 left-6 z-[100]",
            onclick="toggleSidebar()",
        ),
        Div(
            Div(
                H3("Loading metrics...", cls="loading loading-dots loading-lg text-primary"),
                cls="m-auto loading-container",
            ),
            id="charts-container",
            cls="h-screen overflow-y-auto p-6 bg-muted/10 flex flex-col w-full",
        ),
        cls="relative flex-1 h-screen sidebar-transition min-w-0",
        id="main-content",
    )
    init_script = Script(
        """
        window.splitInstance = Split(['#sidebar', '#main-content'], {
            sizes: [20, 80],
            minSize: [250, 400],
            gutterSize: 8,
            cursor: 'col-resize',
            onDragEnd: function() {
                // Resize charts when user finishes dragging
                if(window.chartInstances) window.chartInstances.forEach(c => c.resize());
            }
        });
    """
    )

    return Title(f"{project_name}"), Div(
        sidebar,
        charts,
        init_script,
        cls="flex flex-row w-full h-screen overflow-hidden text-foreground",
        id="layout-wrapper",
    )


@rt("/{project_name}/data")
def get_data(sess, project_name: str, runs: list[str] = None, smoothing: float = 0.0, downsample: int = 1, refresh: bool = False):
    sess[f"prefs_{project_name}"] = {
        "selected_runs": runs or [],
        "smoothing": str(smoothing),
        "downsample": str(downsample),
        "refresh": bool(refresh),
    }
    if not runs:
        return json.dumps({"data": {}})

    db = get_db(project_name)
    raw_data = db.get_metrics(runs, refresh=bool(refresh))
    resp = orjson.dumps(
        {"data": prepare_metrics(raw_data)}, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS
    )
    return Response(content=resp, media_type="application/json")


@click.command()
@click.option("--host", default="127.0.0.1", help="Host/IP to bind the server")
@click.option("--port", default=8000, type=int, help="Port to run the server on")
@click.option("--project", default=None, help="Default project to use")
def main(host, port, project):
    global default_project
    default_project = project
    serve(host=host, port=port, reload=False, appname="trackio_ui.main")


if __name__ == "__main__":
    main()
