import json
from fasthtml.common import *
from monsterui.all import *


def LabeledCheckbox(label, id, name=None, checked=False, onchange=None, onclick=None, cls_colors="checkbox-primary", **kwargs):
    """Generic component for a checkbox with a label."""
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


def RunsListComponent(runs_names: list[str], id="runs-list-container"):
    runs_names = runs_names or []
    ids_json = json.dumps([r for r in runs_names])
    alpine_data = f"{{ selected: $persist([]), allIds: {ids_json} }}"
    return Div(
        LabeledCheckbox(
            "Select All Runs",
            "select-all",
            **{
                "@click": "selected = selected.length === allIds.length ? [] : [...allIds]",
                ":checked": "allIds.length > 0 && selected.length === allIds.length",
                "x-effect": "$el.indeterminate = selected.length > 0 && selected.length < allIds.length",
            },
        ),
        Div(
            *[RunEntry(r) for r in runs_names],
            cls="flex-1 min-h-0 overflow-y-auto overflow-x-auto mt-2 border border-gray w-full",
        ),
        x_data=alpine_data,
        x_init="selected = selected.filter(id => allIds.includes(id))",
        cls="flex flex-col flex-1 min-h-0",
        id=id,
    )


def ResizeHandle():
    return Div(
        cls="w-1.5 cursor-col-resize hover:bg-primary/40 active:bg-primary/60 transition-colors shrink-0 relative group",
        x_data="sidebarResize()",
        **{"@pointerdown": "startDrag($event)"},
    )


def ResizeScript():
    return Script(
        """
document.addEventListener('alpine:init', () => {
Alpine.data('sidebarResize', () => ({
    startDrag(e) {
      e.preventDefault();
      const sidebar = document.getElementById('sidebar');
      const wrapper = document.getElementById('layout-wrapper');
      const startX = e.clientX;
      const startW = sidebar.offsetWidth;

      // Write directly to CSS var
      const onMove = (ev) => {
        const maxW = Math.floor(window.innerWidth * 0.5);
        const minW = Math.floor(window.innerWidth * 0.1);
        const newW = Math.min(maxW, Math.max(minW, startW + ev.clientX - startX));
        wrapper.style.setProperty('--sidebar-width', newW + 'px');
      };

      const onUp = () => {
        document.removeEventListener('pointermove', onMove);
        document.removeEventListener('pointerup', onUp);
        // Persist
        localStorage.setItem('sidebarWidth', wrapper.style.getPropertyValue('--sidebar-width'));
      };

      document.addEventListener('pointermove', onMove, { passive: true });
      document.addEventListener('pointerup', onUp);
    }
  }));
});
"""
    )
