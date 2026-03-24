import json
from fasthtml.common import *
from monsterui.all import *


def LabeledCheckbox(label, id, name=None, checked=False, onchange=None, onclick=None, cls_colors="checkbox-primary", **kwargs):
    """Checkbox + label pair used throughout the sidebar."""
    return Div(
        CheckboxX(
            id=id,
            name=name or id,
            checked=checked,
            onchange=onchange,
            onclick=onclick,
            cls=f"checkbox checkbox-sm {cls_colors} mr-2",
            **kwargs,
        ),
        FormLabel(label, fr=id),
        cls="flex items-center",
    )


def SidebarSection(*content, cls=""):
    """Container for logical groups in the sidebar."""
    return Div(*content, cls=f"p-4 border-b space-y-3 {cls}")


def RunEntry(run_name):
    """Single run row in the runs list."""
    return Div(
        CheckboxX(
            name="runs",
            value=run_name,
            x_model="selected",
            cls="checkbox checkbox-sm checkbox-primary mr-3",
        ),
        Span(run_name, cls="text-sm"),
        cls="flex items-center hover:bg-base-content/5 px-2 py-1.5 cursor-pointer transition-colors",
    )


def RunsListItems(runs_names: list[str], id="runs-list-inner"):
    """Inner scrollable list of runs. Swapped by HTMX independently."""
    runs_names = runs_names or []
    ids_json = json.dumps(list(runs_names))
    return Div(
        *[RunEntry(r) for r in runs_names],
        id=id,
        x_init=f"allIds = {ids_json}; selected = selected.filter(id => allIds.includes(id))",
        cls="flex-1 min-h-0 overflow-y-auto overflow-x-auto w-full uk-card shadow-none",
    )


def RunsListComponent(project_name: str, runs_names: list[str], id="runs-list-container"):
    """Outer container holding the header, buttons, and Alpine.js state."""
    from trackio_ui.main import get_runs
    alpine_data = "{ selected: $persist([]), allIds: [] }"

    header = Div(
        LabeledCheckbox(
            "Select All Runs",
            "select-all",
            **{
                "@click": "selected = selected.length === allIds.length ? [] : [...allIds]",
                ":checked": "allIds.length > 0 && selected.length === allIds.length",
                "x-effect": "$el.indeterminate = selected.length > 0 && selected.length < allIds.length",
            },
        ),
        Button(
            UkIcon("refresh-cw", height=14, width=14, cls="spin-indicator"),
            title="Refresh Runs List",
            hx_get=get_runs.to(project_name=project_name),
            hx_target="#runs-list-inner",
            hx_swap="outerHTML",
            hx_include="this",
            hx_indicator="this",
            cls="btn btn-xs btn-ghost p-1 opacity-50 hover:opacity-100 transition-opacity flex items-center justify-center",
        ),
        cls="flex items-center justify-between mb-2",
    )
    return Div(
        header,
        RunsListItems(runs_names),
        x_data=alpine_data,
        cls="flex flex-col flex-1 min-h-0 mt-2",
        id=id,
    )


def ResizeHandle():
    return Div(
        cls="w-1.5 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 transition-colors shrink-0 relative group",
        x_data="sidebarResize()",
        **{"@pointerdown": "startDrag($event)"},
    )


def ResizeScript():
    return Script("""
document.addEventListener('alpine:init', () => {
Alpine.data('sidebarResize', () => ({
    init() {
        const saved = localStorage.getItem('sidebarWidth');
        if (saved) {
            document.getElementById('layout-wrapper')
                ?.style.setProperty('--sidebar-width', saved);
        }
    },
    startDrag(e) {
      e.preventDefault();
      const sidebar = document.getElementById('sidebar');
      const wrapper = document.getElementById('layout-wrapper');
      const startX = e.clientX;
      const startW = sidebar.offsetWidth;
      const onMove = (ev) => {
        const maxW = Math.floor(window.innerWidth * 0.5);
        const minW = Math.floor(window.innerWidth * 0.1);
        const newW = Math.min(maxW, Math.max(minW, startW + ev.clientX - startX));
        wrapper.style.setProperty('--sidebar-width', newW + 'px');
      };
      const onUp = () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        localStorage.setItem('sidebarWidth', wrapper.style.getPropertyValue('--sidebar-width'));
        if (typeof Charts !== 'undefined') Charts.resize();
      };
      document.addEventListener('pointermove', onMove, { passive: true });
      document.addEventListener('pointerup', onUp);
    }
  }));
});
""")
