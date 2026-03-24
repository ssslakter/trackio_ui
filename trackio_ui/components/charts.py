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
        style="contain: content; content-visibility: auto; contain-intrinsic-size: auto 256px;",
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
        style="contain: content;",
    )


def _render(node: dict[str, dict[str, Any] | None], prefix: str = "") -> list:
    cards = []
    folders = []

    for k, v in sorted(node.items()):
        if k == _SELF:
            continue
        path = f"{prefix}/{k}".lstrip("/")
        if v is None:
            cards.append(ChartCard(path))
        else:
            if _SELF in v:
                cards.append(ChartCard(path))
            inner = {ik: iv for ik, iv in v.items() if ik != _SELF}
            if inner:
                folders.append(
                    GroupPanel(
                        *_render(inner, path),
                        label=k,
                        id=f"folder-{_slug(path)}",
                        card=False,
                    )
                )
    if cards:
        cards_grid = Div(*cards, cls="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4")
        charts_block = [GroupPanel(cards_grid, label="metrics", id="folder-metrics", card=True)] if prefix == "" else [cards_grid]
    else:
        charts_block = []

    return charts_block + folders


_SELF = "_self"


def _tree(paths: list[str]) -> dict[str, dict[str, Any] | None]:
    t: dict[str, dict[str, Any] | None] = {}

    for path in sorted(paths):
        parts = path.split("/")
        node = t

        for p in parts[: min(len(parts) - 1, MAX_DEPTH)]:
            existing = node.get(p)
            if existing is None and p not in node:  # type: ignore
                node[p] = {}
            elif existing is None and p in node:  # type: ignore
                node[p] = {_SELF: None}
            node = node[p]

        leaf_key = "/".join(parts[min(len(parts) - 1, MAX_DEPTH) :])

        if node and leaf_key in node and isinstance(node[leaf_key], dict):
            node[leaf_key][_SELF] = None
        else:
            node[leaf_key] = None
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
