import json
from fasthtml.common import *
from monsterui.all import *


def LabeledCheckbox(label, id, name=None, checked=False, onchange=None, onclick=None, cls_colors="checkbox-primary"):
    """Generic component for a checkbox with a label."""
    return Div(
        CheckboxX(
            id=id,
            name=name or id,
            checked=checked,
            onchange=onchange,
            onclick=onclick,
            cls=f"checkbox checkbox-sm {cls_colors} mr-2",
        ),
        Label(label, cls="font-semibold text-sm cursor-pointer", htmlFor=id),
        cls="flex items-center",
    )


def SidebarSection(*content, cls=""):
    """Container for logical groups in the sidebar."""
    return Div(*content, cls=f"p-4 border-b space-y-4 {cls}")


def RunEntry(run_name):
    """Specific component for an individual run item in the list."""
    return Div(
        CheckboxX(
            name="runs",
            value=run_name,
            x_model="selected",
            cls="checkbox checkbox-sm checkbox-primary mr-3",
        ),
        Span(run_name, cls="text-sm"),
        cls="flex items-center hover:bg-muted/50 p-2 rounded-md cursor-pointer transition-colors",
    )


def RunsListComponent(runs_names: list[str]):
    runs_names = runs_names or []
    ids_json = json.dumps([r for r in runs_names])
    alpine_data = f'{{ selected: $persist([]), allIds: {ids_json} }}'
    return Div(
        LabeledCheckbox(
            "Select All Runs",
            "select-all",
            onclick="let c = this.checked; document.querySelectorAll('input[name=runs]').forEach(el => el.checked = c); htmx.trigger(this.closest('form'), 'change')",
        ),
        Div(
            *[RunEntry(r) for r in runs_names],
            id="runs-list-container",
            cls="flex-1 min-h-0 overflow-y-auto overflow-x-auto mt-2 border border-gray w-full",
        ),
        x_data=alpine_data,
        x_init="selected = selected.filter(id => allIds.includes(id))",
        cls="flex flex-col flex-1 min-h-0",  # <-- grows to fill remaining form space
    )
