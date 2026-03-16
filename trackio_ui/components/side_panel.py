from fasthtml.common import *
from monsterui.all import *


def LabeledToggle(label, id, name=None, checked=False, onchange=None, onclick=None, cls_colors="checkbox-primary"):
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
