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
