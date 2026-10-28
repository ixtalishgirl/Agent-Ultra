"""Demo entrypoint: head + copies + reports, all runnable locally.

Usage from ~/workspace/agent-ultra:
    python3 -m agent_ultra [--copies N] [--task TASK_ID]

What it really does: spawns N copy dirs (workspace + browser profile),
each copy checks the real Agent OS dispatcher bridge and reports facts
to the head, and the head runs a mechanical Arena-style bracket.
No model call, no container, no live browser: those are UNTESTED and
are reported as such, never faked.
"""

import argparse
import tempfile
from pathlib import Path

from .head import HeadAgent
from .spawner import Spawner


def run_demo(copies=3, task_id="demo-001", base_dir=None):
    base = Path(base_dir) if base_dir else Path(tempfile.mkdtemp(prefix="agent-ultra-demo-"))
    copies_dir = base / "copies"
    log_path = base / "reports.jsonl"
    spawner = Spawner(copies_dir)
    made = spawner.spawn(copies)
    reports = [c.work(task_id, log_path) for c in made]
    head = HeadAgent(log_path)
    rounds, winner = head.run_bracket(head.collect())
    return {
        "base_dir": str(base),
        "log_path": str(log_path),
        "copies": [c.describe() for c in made],
        "reports": len(reports),
        "bracket_rounds": rounds,
        "winner": winner["copy_id"] if winner else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--copies", type=int, default=3)
    parser.add_argument("--task", default="demo-001")
    parser.add_argument("--base-dir", default=None)
    args = parser.parse_args()
    import json

    print(json.dumps(run_demo(args.copies, args.task, args.base_dir), indent=2))


if __name__ == "__main__":
    main()
