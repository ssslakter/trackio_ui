from fasthtml.common import *
from monsterui.all import *

MAX_DEPTH = 3


def _slug(path: str) -> str:
    return path.replace("/", "-").replace(".", "-")


def ChartCard(path: str):
    """Render a single chart card."""
    return Div(
        P(
            path.split("/", maxsplit=MAX_DEPTH)[-1],
            title=path,
            cls="text-[10px] font-bold uppercase tracking-widest opacity-40 truncate mb-1",
        ),
        Div(cls="chart-canvas w-full flex-1 min-h-0"),
        Button(
            UkIcon("maximize-2", height=13, width=13),
            onclick=f"Charts.openModal('{path}')",
            cls="absolute top-1.5 right-1.5 opacity-0 group-hover:opacity-60 "
            "hover:!opacity-100 transition-opacity btn btn-xs btn-ghost p-1",
        ),
        id=f"chart-{_slug(path)}",
        data_metric=path,
        cls="relative group flex flex-col p-2 h-64 uk-card shadow-none",
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


def GroupPanel(*content, label: str, id: str, open: bool = True, card: bool = False):
    """Render a collapsible group panel."""
    panel_cls = "p-4 bg-card uk-card" if card else "p-4 bg-card"
    return Details(
        Summary(
            label,
            cls="!font-bold text-xs uppercase tracking-widest opacity-50 select-none",
        ),
        Div(*content, cls="flex flex-col gap-6 pt-2"),
        open=open,
        id=id,
        cls=panel_cls,
    )


def _render(node: dict[str, dict[str, Any] | None], prefix: str = "") -> list:
    cards = [ChartCard(f"{prefix}/{k}".lstrip("/")) for k, v in sorted(node.items()) if v is None]
    folders = [
        GroupPanel(
            *_render(v, f"{prefix}/{k}".lstrip("/")),
            label=k,
            id=f"folder-{_slug(f'{prefix}/{k}'.lstrip('/'))}",
            card=False,
        )
        for k, v in sorted(node.items())
        if v is not None
    ]
    if cards:
        cards_grid = Div(*cards, cls="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4")
        charts_block = [GroupPanel(cards_grid, label="metrics", id="folder-metrics", card=True)] if prefix == "" else [cards_grid]
    else:
        charts_block = []
    return charts_block + folders


def _tree(paths: list[str]) -> dict[str, dict[str, Any] | None]:
    t: dict[str, dict[str, Any] | None] = {}
    for path in sorted(paths):
        parts = path.split("/")
        node: dict[str, dict[str, Any] | None] = t
        for p in parts[: min(len(parts) - 1, MAX_DEPTH)]:
            existing = node.setdefault(p, {})
            node = existing if isinstance(existing, dict) else node
        node["/".join(parts[min(len(parts) - 1, MAX_DEPTH) :])] = None
    return t


def ChartsContainer(metric_paths: list[str]):
    """Render charts container with grouped metrics."""
    if not metric_paths:
        return Div(
            P("No metrics yet — select runs and refresh.", cls="text-sm opacity-40"),
            id="charts-container",
            cls="flex items-center justify-center h-48",
        )

    return Div(*_render(_tree(metric_paths)), id="charts-container", cls="flex flex-col gap-6")
