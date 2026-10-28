"""Arena of copies — COPY MANAGEMENT (head-managed flow).

The head manages all copies and gives the order to every copy. The
flow, in order, documented so the model clearly knows it:

  1. ORDER BROADCAST — the head gives the order to EVERY copy: one
     order record per copy in orders.jsonl, each carrying the task
     and that copy's assigned approach.
  2. DISTINCT PER-COPY APPROACH — for ONE task, every copy tries a
     DIFFERENT path (alag alag rastay). Approaches come from
     copy_agent.APPROACH_NAMES; the arena REFUSES to run when
     copies exceed distinct approaches (ValueError) rather than
     silently giving two copies the same path. A caller may pass
     its own distinct approach list instead.
  3. INDEPENDENT WORK — copies work in waves of at most
     max_concurrent (sequential batches on this host; containers
     are UNTESTED here, so no parallel-container claim is made).
  4. RESULT REPORTS — each copy reports through the report
     protocol (reports.jsonl): status + evidence, with its
     approach named in the evidence.
  5. HEAD COMPARISON — only after the waves finish, the head
     examines EVERY returned report and ranks them on evidence.
  6. JUDGED WINNER — the bracket yields exactly one winner (or
     None when no copy reported). Copies that never reported are
     listed as missing, not silently dropped.

Structure notes: this module is the structure (broadcast, waves,
judgement). The pipeline is the report protocol plus the 5-stage
tool pipeline for any tool a copy creates; the tunnel is the model
endpoint route (model_client) — neither is re-implemented here,
both are reused. One run_arena call owns its base dir's
orders.jsonl + reports.jsonl; both are reset at the start so stale
reports from an older run can never count as this run's answers.

1000 SIMULTANEOUS copies are NOT promised: with waves, 1000 copies
means ceil(1000 / max_concurrent) sequential waves, and true
simultaneity needs a fleet (see ARCHITECTURE.md scaling math).
Quality judging by a model is UNTESTED and is not claimed — the
head judges mechanically on report evidence.
"""

import json
import math
import time
from pathlib import Path

from .copy_agent import APPROACH_NAMES
from .head import HeadAgent
from .report_protocol import read_reports
from .spawner import DEFAULT_CONCURRENT, Spawner


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")


def _append_jsonl(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


def run_arena(task_id, base_dir, copies=3, max_concurrent=DEFAULT_CONCURRENT,
              work_fn=None, prefix="arena", approaches=None, task=None):
    """Run one task across N copies under head management and pick
    one judged winner.

    work_fn(copy, task_id, log_path) overrides the copy's work
    (tests inject mocked copies this way). The copy's assigned
    approach is always set on copy.approach before work_fn runs, so
    an overriding function can record it too. Default work: the
    copy runs its assigned approach path (copy_agent._run_approach)
    and reports it.
    """
    if not isinstance(copies, int) or copies < 1:
        raise ValueError("copies must be an integer >= 1")
    if not isinstance(max_concurrent, int) or max_concurrent < 1:
        raise ValueError("max_concurrent must be an integer >= 1")
    pool = list(approaches) if approaches is not None else list(APPROACH_NAMES)
    if len(set(pool)) != len(pool):
        raise ValueError("approaches must be distinct — duplicates refused")
    if copies > len(pool):
        raise ValueError(
            f"only {len(pool)} distinct approaches available, "
            f"but copies={copies} requested — add approaches to run "
            f"more copies; paths are never duplicated")
    assigned = pool[:copies]

    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    orders_path = base / "orders.jsonl"
    log_path = base / "reports.jsonl"
    _write_jsonl(orders_path, [])
    _write_jsonl(log_path, [])

    spawner = Spawner(base / "copies")
    all_copies = spawner.spawn(copies, prefix=prefix)

    # 1. ORDER BROADCAST — the head gives the order to every copy,
    #    each with its own distinct approach, recorded on disk.
    assignments = []
    for copy, approach in zip(all_copies, assigned):
        copy.approach = approach
        order = {
            "task_id": task_id,
            "copy_id": copy.copy_id,
            "approach": approach,
            "order": task if task is not None else {"task_id": task_id},
            "ts": time.time(),
        }
        _append_jsonl(orders_path, order)
        assignments.append({"copy_id": copy.copy_id, "approach": approach})

    # 2+3. DISTINCT APPROACHES, INDEPENDENT WORK in waves.
    waves = math.ceil(copies / max_concurrent)
    for wave_start in range(0, copies, max_concurrent):
        for copy in all_copies[wave_start:wave_start + max_concurrent]:
            if work_fn is not None:
                work_fn(copy, task_id, log_path)
            else:
                copy.work(task_id, log_path, approach=copy.approach)

    # 4+5+6. REPORTS, HEAD COMPARISON, JUDGED WINNER — only after
    # all copies have had their turn.
    reports = read_reports(log_path)
    reported = {r["copy_id"] for r in reports}
    missing = [c.copy_id for c in all_copies if c.copy_id not in reported]
    head = HeadAgent(log_path)
    judgement = head.judge(reports)
    return {
        "task_id": task_id,
        "copies": copies,
        "max_concurrent": max_concurrent,
        "waves": waves,
        "wave_mode": "sequential batches on this host",
        "assignments": assignments,
        "orders_file": str(orders_path),
        "reports_file": str(log_path),
        "reports": len(reports),
        "missing": missing,
        "rounds": judgement["rounds"],
        "comparison": judgement["comparison"],
        "winner": judgement["winner"],
        "status": (
            f"{copies} copies ran in {waves} wave(s) of at most "
            f"{max_concurrent}, each on a distinct approach; "
            f"{len(reports)} reported, {len(missing)} missing; "
            f"1000 simultaneous copies are NOT promised — true "
            f"simultaneity needs a fleet."
        ),
    }
