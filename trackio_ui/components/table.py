import json
from datetime import datetime
from fasthtml.common import *
from monsterui.all import *


def _normalize_run(run: dict) -> dict:
    run["Created"] = run.pop("_Created")
    run["Select"] = run["run_name"]
    del run["created_at"]
    return run


def _build_columns(runs: list[dict]) -> list[str]:
    fixed = ["Select", "run_name", "Created"]
    all_keys = set().union(*(r.keys() for r in runs))
    ignore = set(k for k in all_keys if k.split(".")[-1].startswith("_")) | set(fixed)
    return fixed + sorted(k for k in all_keys if k not in ignore)


def _header_cell(col: str) -> FT:
    if col != "Select":
        return Th(col, cls="whitespace-nowrap")
    return Th(
        CheckboxX(
            id="select-all-rows",
            **{
                "@click": "selected = (selected.length === allIds.length) ? [] : [...allIds]",
                ":checked": "allIds.length > 0 && selected.length === allIds.length",
                "x-effect": "$el.indeterminate = selected.length > 0 && selected.length < allIds.length",
            },
        ),
        shrink=True,
    )


def _body_cell(col: str, val) -> FT:
    if col == "Select":
        return Td(
        CheckboxX(name="selected_runs", value=val, **{"x-model": "selected"}, cls="row-checkbox"),
        shrink=True,
    )
    elif col == "Created":
        dt_obj = datetime.fromisoformat(val)
        formatted = dt_obj.strftime("%B %d, %Y at %I:%M %p")
        return Td(formatted, cls="whitespace-nowrap")
    return Td(str(val) if val is not None else "-", cls="whitespace-nowrap max-w-xs truncate")
    


def RunsTable(project_name: str, runs: list[dict], id: str = "runs_table"):

    from trackio_ui.main import delete_runs_endpoint

    if not runs:
        return Div("No runs found.", cls="p-10 text-center text-muted-foreground")

    alpine_data = json.dumps({"selected": [], "allIds": [r["run_name"] for r in runs]})
    runs = [_normalize_run(r) for r in runs]
    columns = _build_columns(runs)

    table = TableFromDicts(
        header_data=columns,
        body_data=runs,
        header_cell_render=_header_cell,
        body_cell_render=_body_cell,
        cls=(TableT.sm, TableT.divider, TableT.hover),
    )
    table[0].attrs["class"] = "sticky top-0 bg-card"

    return Form(
        Div(
            Button(
                Div(UkIcon(icon="trash-2", cls="mr-2"), "Delete Selected", cls="flex items-center"),
                cls=ButtonT.destructive,
                **{":disabled": "selected.length === 0", ":class": "selected.length === 0 ? 'opacity-40 cursor-not-allowed' : ''"},
                hx_post=delete_runs_endpoint.to(project_name=project_name),
                hx_confirm="Are you sure you want to delete the selected runs?",
                hx_target="#table-container",
            ),
            cls="p-4 border-b bg-muted/20 flex gap-2",
        ),
        Div(
            Div(table, cls="overflow-auto flex-1 h-full w-full", id=id),
            cls="flex-1 min-h-0 overflow-hidden relative",
        ),
        id="table-container",
        x_data=alpine_data,
        cls="flex-1 flex flex-col min-h-0",
    )
