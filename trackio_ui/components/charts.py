from fasthtml.common import *
from monsterui.all import *

MAX_DEPTH = 2


def _slug(path):
    return path.replace("/", "-").replace(".", "-")


def ChartCard(path):
    return Div(
        P(path.split("/")[-1], title=path, cls="text-[10px] font-bold uppercase tracking-widest opacity-40 truncate mb-1"),
        Div(cls="chart-canvas w-full flex-1 min-h-0"),
        Button(
            UkIcon("maximize-2", height=13, width=13),
            onclick=f"Charts.openModal('{path}')",
            cls="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity btn btn-xs btn-ghost p-1",
        ),
        id=f"chart-{_slug(path)}",
        data_metric=path,
        cls="relative group flex flex-col border rounded-lg p-3 h-64",
        style="contain:strict",
    )


def ChartModal():
    """Single reusable modal for enlarged chart view. Render once in layout."""
    return Modal(
        Div(id="chart-modal-canvas", style="height:520px", cls="w-full"),
        header=ModalTitle("", id="chart-modal-title"),
        footer=ModalCloseButton("Close"),
        id="chart-modal",
        dialog_cls="uk-modal-dialog-large uk-margin-auto-vertical",
    )


def _render(node: dict[str, dict], prefix=""):
    cards = [ChartCard(f"{prefix}/{k}".lstrip("/")) for k, v in sorted(node.items()) if v is None]
    folders = [
        Details(
            Summary(k, cls="cursor-pointer text-xs font-bold uppercase tracking-widest opacity-50 py-2 select-none"),
            Div(*_render(v, f"{prefix}/{k}".lstrip("/")), cls="flex flex-col gap-6 pt-2"),
            open=True,
            id=f"folder-{_slug(prefix + k)}",
        )
        for k, v in sorted(node.items())
        if v is not None
    ]
    return ([Div(*cards, cls="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4")] if cards else []) + folders


def _tree(paths: list[str]) -> dict[str, dict | None]:
    t = {}
    for path in sorted(paths):
        parts = path.split("/")
        node = t
        for p in parts[: min(len(parts) - 1, MAX_DEPTH)]:
            node = node.setdefault(p, {})
        node["/".join(parts[min(len(parts) - 1, MAX_DEPTH) :])] = None
    return t


def ChartsContainer(metric_paths: list[str]):
    if not metric_paths:
        return Div(
            P("No metrics yet — select runs and refresh.", cls="text-sm opacity-40"),
            id="charts-container",
            cls="flex items-center justify-center h-48",
        )
    return Div(*_render(_tree(metric_paths)), id="charts-container", cls="flex flex-col gap-6")
