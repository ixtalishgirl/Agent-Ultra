"""One agent copy.

A copy owns: its own workspace dir, its own browser-profile dir, and
its own machine record. The machine record is honest about this host:
no Docker here, so the machine is a local directory and the container
path is UNTESTED (see spawner.py). A copy never claims a live browser
or a container it does not have.

work() is the real, runnable core: the copy checks the dispatcher
bridge (a real call: 761 tools load), then reports facts to the head.
Model inference is NOT done here: the model endpoint is an empty
config placeholder (config.yaml) and live serving is UNTESTED.

APPROACHES (arena copy management): one task is never worked the
same way by every copy. Each copy is assigned ONE approach from
APPROACH_NAMES — a different real path (dispatcher check, extra
tool, custom-tool list, browser registry, shell, integration
status, text understanding). work(..., approach=name) runs only
that path and names it in its report evidence, so the head can see
exactly which copy took which path. Unknown approach names are
recorded as error evidence, never faked.
"""

import time
from pathlib import Path

from .browser_profile import BrowserProfile
from .report_protocol import Report, append_report

# Distinct real paths a copy can take for one task. The arena
# assigns each copy a different one and refuses to run when copies
# exceed this pool rather than duplicating a path.
APPROACH_NAMES = (
    "dispatcher-count",
    "extra-calculator",
    "custom-tools-list",
    "browser-registry",
    "shell-echo",
    "supabase-status",
    "drive-status",
    "extra-understand",
)


def _run_approach(name):
    """Run one approach path. Returns (status, evidence list).
    Every branch is a real call; failures become error evidence."""
    from . import dispatcher_bridge as bridge

    if name == "dispatcher-count":
        count = bridge.tool_count()
        return "ok", [f"dispatcher tool_count={count}"]
    if name == "extra-calculator":
        result = bridge.dispatch_extra("calculator", {"expression": "2+3*4"})
        if result.get("result") == 14:
            return "ok", ["calculator 2+3*4=14"]
        return "error", [f"calculator unexpected: {result}"]
    if name == "custom-tools-list":
        tools = bridge.list_custom_tools()
        return "ok", [f"custom tools count={len(tools)}"]
    if name == "browser-registry":
        tools = bridge.list_browser_tools()
        return "ok", [f"browser tools count={len(tools)}"]
    if name == "shell-echo":
        from . import shell_tool

        result = shell_tool.run("echo arena-probe")
        if result.get("ok") and result.get("stdout", "").strip() == "arena-probe":
            return "ok", ["shell echo arena-probe rc=0"]
        return "error", [f"shell echo unexpected: {result}"]
    if name == "supabase-status":
        status = bridge.supabase_status()
        return "ok", [f"supabase configured={status.get('configured')}"]
    if name == "drive-status":
        status = bridge.drive_status()
        return "ok", [f"drive configured={status.get('configured')}"]
    if name == "extra-understand":
        result = bridge.dispatch_extra(
            "understand_text",
            {"text": "The arena probe checks distinct paths. "
                     "Each copy walks alone. "
                     "The head judges on evidence."})
        if result.get("status") == "ok":
            return "ok", ["understand_text ok"]
        return "error", [f"understand_text unexpected: {result}"]
    return "error", [f"unknown approach: {name!r}; not executed"]


class CopyAgent:
    def __init__(self, copy_id, base_dir, machine):
        self.copy_id = copy_id
        self.base_dir = Path(base_dir)
        self.workdir = self.base_dir / "workspace"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserProfile(copy_id, self.base_dir)
        self.machine = machine  # dict describing the copy's machine
        self.approach = None  # approach assigned by the head (arena)

    def work(self, task_id, log_path, approach=None):
        """Do the verifiable part of a task and report facts to head.
        With approach=None (legacy path) the copy checks the
        dispatcher bridge. With approach=name the copy runs ONLY
        that distinct path and names it in its evidence, so the
        head can see exactly which copy took which path."""
        from . import dispatcher_bridge as bridge

        self.approach = approach
        if approach is None:
            try:
                count = bridge.tool_count()
                evidence = [f"dispatcher tool_count={count}"]
                status, summary = "ok", "dispatcher bridge live"
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                evidence = [f"dispatcher bridge error: {exc}"]
                status, summary = "error", "dispatcher bridge failed"
        else:
            try:
                status, path_evidence = _run_approach(approach)
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                status = "error"
                path_evidence = [f"approach {approach} raised: {exc}"]
            evidence = [f"approach={approach}"] + path_evidence
            summary = f"approach {approach} {status}"
        report = Report(
            copy_id=self.copy_id,
            task_id=task_id,
            status=status,
            summary=summary,
            evidence=evidence,
        )
        append_report(log_path, report)
        return report

    def describe(self):
        return {
            "copy_id": self.copy_id,
            "workdir": str(self.workdir),
            "browser_profile": str(self.browser.path),
            "browser_live": "UNTESTED",
            "machine": self.machine,
            "approach": self.approach,
        }
