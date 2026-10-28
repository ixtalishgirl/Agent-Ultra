"""Copy -> head report protocol.

A report is a plain JSON object, one per line in reports.jsonl.
No prompt content lives here: reports carry facts (status, evidence)
only. The head ranks on those facts mechanically; quality judging by
a model is UNTESTED and needs owner-approved criteria first.
"""

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

VALID_STATUSES = ("ok", "error", "pending")


@dataclass
class Report:
    copy_id: str
    task_id: str
    status: str  # ok | error | pending
    summary: str
    evidence: list = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def validate(self):
        if self.status not in VALID_STATUSES:
            raise ValueError(f"bad status: {self.status!r}")
        if not self.copy_id or not self.task_id:
            raise ValueError("copy_id and task_id are required")
        return True

    def to_json(self):
        self.validate()
        return json.dumps(asdict(self), sort_keys=True)


def append_report(log_path, report):
    """Append one report to a JSONL log. Returns the line written."""
    line = report.to_json()
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def read_reports(log_path):
    """Read all reports from a JSONL log. Returns a list of dicts."""
    path = Path(log_path)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
