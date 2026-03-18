from fasthtml.common import *
from monsterui.all import *


def ProjectHeader(project_name, active_tab="dashboard"):
    """Navigation header to switch between views."""

    def Tab(name, href, active):
        cls = "border-b-2 px-4 py-2 text-sm font-medium transition-colors "
        cls += "border-primary text-primary" if active else "border-transparent text-muted-foreground hover:text-foreground"
        return A(name, href=href, cls=cls)

    return Header(
        H3(f"{project_name}", cls="text-lg font-bold px-4 py-2"),
        Nav(
            Tab("Dashboard", f"/{project_name}", active=active_tab == "dashboard"),
            Tab("Runs Table", f"/{project_name}/table", active=active_tab == "runs"),
            cls="flex space-x-2 px-4 border-b bg-card",
        ),
        cls="flex flex-col bg-card border-b shrink-0",
    )


def SectionLabel(text):
    return P(text, cls="text-xs font-bold uppercase tracking-widest opacity-50")


def SliderInput(name, label, min="0", max="1", step="0.01", default="0.5", **kwargs):
    return Div(
        FormLabel(label, fr=name),
        Input(
            type="range",
            name=name,
            id=name,
            min=min,
            max=max,
            step=step,
            x_init="$el.value = val",
            cls="uk-range w-full mt-1",
            **{"@input": f"val = $el.value; localStorage.setItem('{name}', val)"},
        ),
        Span(x_text="parseFloat(val).toFixed(2)", cls="text-sm text-muted-foreground tabular-nums"),
        x_data=f"{{val: parseFloat(localStorage.getItem('{name}') ?? '{default}')}}",
        cls="flex flex-col gap-1",
        **kwargs,
    )


def SSEListener(project_name: str):
    from trackio_ui.main import live_stream

    return Div(
        id="sse-root",
        hx_ext="sse",
        sse_connect=live_stream.to(project_name=project_name),
        sse_swap="layout_add,layout_remove",
    )
