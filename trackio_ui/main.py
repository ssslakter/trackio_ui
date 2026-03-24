from importlib.resources import files
from datetime import datetime
import asyncio
from asyncio import Queue
import json, orjson, tempfile, click
from pathlib import Path
from fasthtml.common import *
from monsterui.all import *
from .data import TrackioDatabase, prepare_step_metrics, prepare_system_metrics
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
    Theme.blue.headers(),
    Style("""
    .dot-wave { display: flex; gap: 4px; align-items: center; justify-content: center; }
    .dot-wave div { width: 8px; height: 8px; border-radius: 50%; background: currentColor; animation: dot-wave 1.4s infinite ease-in-out both; }
    .dot-wave div:nth-child(1) { animation-delay: -0.32s; }
    .dot-wave div:nth-child(2) { animation-delay: -0.16s; }
    @keyframes dot-wave {
        0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
        40% { transform: scale(1); opacity: 1; }
    }
    """),
    Style("""
    [x-cloak] {
        display: none !important;
    }

    #sidebar {
        width: var(--sidebar-width, 280px);
    }

    #layout-wrapper {
        --sidebar-width: 280px;
    }

    /* number input spinners follow the page color-scheme (light/dark) */
    html:not(.dark) {
        color-scheme: light;
    }

    html.dark {
        color-scheme: dark;
    }

    button.htmx-request .spin-indicator {
        animation: htmx-spin 1s linear infinite;
        transform-origin: center;
    }
    @keyframes htmx-spin {
        from { transform: rotate(0deg); }
        to { transform: rotate(360deg); }
    }
    
    body.is-resizing * {
        pointer-events: none !important;
        user-select: none !important;
    }
    """),
]


databases = {}
project_state = {}

app, rt = fast_app(
    hdrs=headers,
    static_path=files("trackio_ui"),
    secret_key="secret",
    key_fname=Path(tempfile.gettempdir()) / ".trackio_ui_sesskey",
    bodykw={"hx-boost": "true"},
)

trackio_root = os.getenv("TRACKIO_ROOT", None)


def get_db(project_name) -> TrackioDatabase:
    if project_name not in databases:
        databases[project_name] = TrackioDatabase(project_name, trackio_root=trackio_root)
    return databases[project_name]


# --- Routes ---


@rt("/")
def index():
    default_project = os.getenv("TRACKIO_DEFAULT_PROJECT")
    return Redirect(f"/{default_project or 'default_project'}")


@rt("/{project_name}/runs")
def get_runs(project_name: str):
    runs = get_db(project_name).get_runs()
    return RunsListItems(runs)


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


@rt("/{project_name}/sse_toggle")
def sse_toggle(project_name: str, req: Request):
    query = dict(req.query_params)
    if query.get("live-update-toggle") == "on":
        return SSEListener(project_name)
    return ""


@rt("/{project_name}")
def project_dashboard(project_name: str):
    if project_name in project_state:
        project_state[project_name].pop("schema", None)
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
            LabeledCheckbox("Wall-Clock", "use-time-axis", cls_colors="checkbox-secondary", x_model="useTime"),
            cls="flex flex-row flex-wrap gap-4",
            x_data="{ logX: false, logY: false, useTime: false }",
            **{"@change": "Charts.setAxes(logX, logY, useTime)"},
        ),
        id="controls-form",
        hx_post=get_charts.to(project_name=project_name),
        hx_trigger="change",
        hx_swap="none",
        hx_include="#runs-form",
        hx_indicator="#main-refresh-btn",
        hx_sync="this:replace",
        cls="flex flex-col gap-3 shrink-0",
    )

    runs_list = RunsListComponent(project_name, runs)
    runs_form = Form(
        runs_list,
        id="runs-form",
        hx_post=get_charts.to(project_name=project_name),
        hx_trigger="change delay:500ms, load",
        hx_target=main_id,
        hx_swap="innerHTML",
        hx_include=f"#{controls_form.id}",
        hx_indicator="#main-refresh-btn",
        hx_sync="this:replace",
        hx_on__before_request="Charts.clearQueue()",
        cls="flex flex-col flex-1 min-h-0",
    )

    live_update_toggle = Div(
        LabeledCheckbox(
            "Live Updates",
            "live-update-toggle",
            cls_colors="checkbox-accent",
            hx_get=sse_toggle.to(project_name=project_name),
            hx_target="#sse-wrapper",
            hx_swap="innerHTML",
        ),
        x_data="{ live: $persist(false).as('trackio_live_updates') }",
        cls="pb-2 pt-1",
    )

    controls_section = SidebarSection(
        controls_form,
        live_update_toggle,
        runs_form,
        cls="flex flex-col min-h-0 overflow-hidden",
    )

    sidebar_footer = Div(
        Button(
            UkIcon("refresh-cw", cls="mr-2 spin-indicator", width=16, height=16),
            "Refresh Data",
            id="main-refresh-btn",
            cls=(ButtonT.primary, "w-full", "flex", "items-center", "justify-center"),
            hx_post=get_charts.to(project_name=project_name),
            hx_include="#runs-form, #controls-form",
            hx_target=main_id,
            hx_swap="innerHTML",
            hx_sync="this:replace",
        ),
        cls="p-4 border-t bg-card shrink-0",
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
        LoadingIndicator(),
        id=main_id[1:],
        cls="relative flex-1 min-w-0 overflow-y-auto p-6 pr-8 bg-muted/10",
    )

    layout = Div(
        sidebar,
        ResizeHandle(),
        main_content,
        Script("{}", type="application/json", id="chart-data-payload"),
        ChartModal(),
        Div(id="sse-wrapper"),
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


def _merge_data_payloads(step_data: dict, system_data: dict) -> dict:
    """Merge step-metric and system-metric payloads into one {run: {path: series}} dict."""
    merged: dict = {}
    for run, series in step_data.items():
        merged.setdefault(run, {}).update(series)
    for run, series in system_data.items():
        merged.setdefault(run, {}).update(series)
    return merged


def _collect_time_axis_paths(system_data: dict) -> list[str]:
    """Return the union of all system/* paths across all runs."""
    paths: set[str] = set()
    for series in system_data.values():
        paths.update(series.keys())
    return sorted(paths)


def _collect_timestamp_paths(step_data: dict) -> list[str]:
    """Return paths from step metrics whose series include a 'ts' field."""
    paths: set[str] = set()
    for series_map in step_data.values():
        for path, series in series_map.items():
            if "ts" in series:
                paths.add(path)
    return sorted(paths)


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

    state = project_state.get(project_name, {})
    prev_schema = state.get("schema", [])

    project_state[project_name] = {"runs": filtered_runs, "smoothing": smoothing, "max_points": max_points}
    metrics_result, new_schema = db.get_metrics_and_schema(filtered_runs)

    run_starts = db.get_run_starts(filtered_runs)
    step_data = prepare_step_metrics(metrics_result.step_metrics, run_starts, smoothing=smoothing, max_points=max_points)
    system_data = prepare_system_metrics(metrics_result.system_metrics, run_starts, max_points=max_points)

    data = _merge_data_payloads(step_data, system_data)

    time_axis_paths = _collect_time_axis_paths(system_data)
    ts_optional_paths = _collect_timestamp_paths(step_data)

    schema_changed = set(prev_schema) != set(new_schema)
    project_state[project_name]["schema"] = new_schema

    data_json = orjson.dumps(
        {
            "data": data,
            "runs": filtered_runs,
            "schema_changed": schema_changed,
            "time_axis_paths": time_axis_paths,
            "ts_optional_paths": ts_optional_paths,
        },
        option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS,
    ).decode()
    data_island = Script(data_json, type="application/json", id="chart-data-payload", hx_swap_oob="true")
    if not schema_changed and runs:
        return data_island, HtmxResponseHeaders(reswap="none")
    return ChartsContainer(new_schema), data_island


shutdown_event = signal_shutdown()


async def live_generator(project_name: str):
    db = get_db(project_name)
    # step metrics state: run_name -> last known step
    run_step_states: dict[str, int] = {}
    # system metrics state: run_name -> last known timestamp
    run_sys_states: dict[str, float] = {}
    run_active_ticks: dict[str, int] = {}
    tick_count = 0

    try:
        while not shutdown_event.is_set():
            state = project_state.get(project_name, {})
            current_runs = state.get("runs", [])
            smoothing = state.get("smoothing", 0.0)
            max_points = state.get("max_points", 0)

            run_step_states = {r: run_step_states.get(r, -1) for r in current_runs}
            run_sys_states = {r: run_sys_states.get(r, -1.0) for r in current_runs}
            run_active_ticks = {r: run_active_ticks.get(r, 0) for r in current_runs}

            runs_to_check = []
            for r in current_runs:
                ticks_idle = run_active_ticks.get(r, 0)
                if ticks_idle < 5 or tick_count % 15 == 0:
                    runs_to_check.append(r)

            if runs_to_check:
                max_steps = await asyncio.to_thread(db.get_max_steps, runs_to_check)
                max_sys_ts = await asyncio.to_thread(db.get_max_system_timestamps, runs_to_check)
                run_starts = await asyncio.to_thread(db.get_run_starts, runs_to_check)

                runs_to_fetch_steps: dict[str, int] = {}
                runs_to_fetch_sys: dict[str, float] = {}
                any_new = False

                for r in runs_to_check:
                    m_step = max_steps.get(r, -1)
                    if m_step > run_step_states.get(r, -1):
                        runs_to_fetch_steps[r] = run_step_states.get(r, -1)
                        any_new = True

                    m_ts = max_sys_ts.get(r, -1.0)
                    if m_ts > run_sys_states.get(r, -1.0):
                        runs_to_fetch_sys[r] = run_sys_states.get(r, -1.0)
                        any_new = True

                    if not any_new:
                        run_active_ticks[r] = run_active_ticks.get(r, 0) + 1

                updated_step_dfs = {}
                updated_sys_dfs = {}

                if runs_to_fetch_steps:
                    updated_step_dfs = await asyncio.to_thread(db.fetch_new_metrics, runs_to_fetch_steps)
                    for r in updated_step_dfs:
                        run_step_states[r] = max_steps.get(r, run_step_states.get(r, -1))
                        run_active_ticks[r] = 0

                if runs_to_fetch_sys:
                    updated_sys_dfs = await asyncio.to_thread(db.fetch_new_system_metrics, runs_to_fetch_sys)
                    for r in updated_sys_dfs:
                        run_sys_states[r] = max_sys_ts.get(r, run_sys_states.get(r, -1.0))
                        run_active_ticks[r] = 0

                if updated_step_dfs or updated_sys_dfs:
                    step_data = await asyncio.to_thread(prepare_step_metrics, updated_step_dfs, run_starts, smoothing, max_points)
                    sys_data = await asyncio.to_thread(prepare_system_metrics, updated_sys_dfs, run_starts, max_points)
                    merged = _merge_data_payloads(step_data, sys_data)
                    time_axis_paths = _collect_time_axis_paths(sys_data)
                    ts_optional_paths = _collect_timestamp_paths(step_data)
                    yield sse_json(
                        {
                            "data": merged,
                            "time_axis_paths": time_axis_paths,
                            "ts_optional_paths": ts_optional_paths,
                        },
                        event="data_update",
                    )

            tick_count += 1
            await asyncio.sleep(1)
    finally:
        pass


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
