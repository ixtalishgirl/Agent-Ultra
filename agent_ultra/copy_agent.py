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
"""

import time
from pathlib import Path

from .browser_profile import BrowserProfile
from .report_protocol import Report, append_report


class CopyAgent:
    def __init__(self, copy_id, base_dir, machine):
        self.copy_id = copy_id
        self.base_dir = Path(base_dir)
        self.workdir = self.base_dir / "workspace"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserProfile(copy_id, self.base_dir)
        self.machine = machine  # dict describing the copy's machine

    def work(self, task_id, log_path):
        """Do the verifiable part of a task and report facts to head."""
        from . import dispatcher_bridge as bridge

        try:
            count = bridge.tool_count()
            evidence = [f"dispatcher tool_count={count}"]
            status, summary = "ok", "dispatcher bridge live"
        except Exception as exc:  # noqa: BLE001 - reported, not hidden
            evidence = [f"dispatcher bridge error: {exc}"]
            status, summary = "error", "dispatcher bridge failed"
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
        }
