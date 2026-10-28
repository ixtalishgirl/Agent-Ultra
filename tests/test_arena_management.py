"""Tests for arena copy management. Run from ~/workspace/agent-ultra:

    python3 tests/test_arena_management.py

Proves WITHOUT a live model or a live browser:
  - the head broadcasts one order per copy, each with a DIFFERENT
    approach, recorded in orders.jsonl;
  - every copy's report names its own assigned approach;
  - after ALL copies return, the head compares every report on
    evidence and judges exactly one winner;
  - copies beyond the distinct-approach pool are refused, never
    silently given a duplicate path;
  - waves still batch copies without promising simultaneity.

Prints PASS lines; exits non-zero on any failure.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_ultra import arena as arena_mod  # noqa: E402
from agent_ultra.copy_agent import APPROACH_NAMES  # noqa: E402
from agent_ultra.report_protocol import Report, append_report, read_reports  # noqa: E402


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
    if not cond:
        raise SystemExit(1)


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agent-ultra-arena-mgmt-"))

    # ---- distinct approaches + judged winner (recording work_fn) --
    def recording_work(specs):
        def work_fn(copy, task_id, log_path):
            status, n = specs[copy.copy_id]
            evidence = [f"approach={copy.approach}"]
            evidence += [f"e{i}" for i in range(n)]
            append_report(log_path, Report(
                copy_id=copy.copy_id, task_id=task_id, status=status,
                summary=f"mock {copy.copy_id} via {copy.approach}",
                evidence=evidence))
        return work_fn

    specs = {"arena-0001": ("ok", 3), "arena-0002": ("ok", 1),
             "arena-0003": ("error", 0)}
    res = arena_mod.run_arena(
        "t1", tmp / "arena1", copies=3, max_concurrent=10,
        work_fn=recording_work(specs),
        task={"goal": "prove distinct paths"})
    got_approaches = [a["approach"] for a in res["assignments"]]
    check("orders assign a distinct approach per copy",
          len(got_approaches) == 3 and len(set(got_approaches)) == 3)
    orders = read_reports(res["orders_file"])
    check("orders file holds one broadcast order per copy",
          len(orders) == 3
          and len({o["approach"] for o in orders}) == 3
          and all(o["order"] == {"goal": "prove distinct paths"}
                  for o in orders))
    reports = read_reports(res["reports_file"])
    by_copy = {r["copy_id"]: r for r in reports}
    check("every report names its own assigned approach",
          all(f"approach={a['approach']}" in by_copy[a["copy_id"]]["evidence"]
              for a in res["assignments"]))
    check("all copies returned before judging",
          res["reports"] == 3 and res["missing"] == [])
    check("head comparison covers every returned report",
          len(res["comparison"]) == 3
          and {c["copy_id"] for c in res["comparison"]}
          == {"arena-0001", "arena-0002", "arena-0003"})
    check("exactly one judged winner, from evidence",
          res["winner"] is not None
          and res["winner"]["copy_id"] == "arena-0001"
          and res["winner"]["status"] == "ok"
          and res["comparison"][0]["copy_id"] == "arena-0001")

    # ---- default path: real approach executors, distinct paths -----
    res2 = arena_mod.run_arena("t2", tmp / "arena2", copies=3)
    reports2 = read_reports(res2["reports_file"])
    rep_approaches = []
    for r in reports2:
        hits = [e for e in r["evidence"] if e.startswith("approach=")]
        rep_approaches.append(hits[0] if hits else None)
    check("default path reports distinct approaches",
          len(reports2) == 3 and len(set(rep_approaches)) == 3
          and all(rep_approaches))
    check("default path still yields one winner",
          res2["winner"] is not None and res2["missing"] == [])
    check("default assignments match the approach pool order",
          [a["approach"] for a in res2["assignments"]]
          == list(APPROACH_NAMES[:3]))

    # ---- pool exhaustion + duplicate approaches are refused --------
    try:
        arena_mod.run_arena("t3", tmp / "arena3",
                            copies=len(APPROACH_NAMES) + 1)
        refused = False
    except ValueError as exc:
        refused = "distinct approaches" in str(exc)
    check("copies beyond the pool are refused, never duplicated",
          refused)
    try:
        arena_mod.run_arena("t4", tmp / "arena4", copies=2,
                            approaches=["same-path", "same-path"])
        dup_refused = False
    except ValueError as exc:
        dup_refused = "distinct" in str(exc)
    check("duplicate custom approaches are refused", dup_refused)

    # ---- waves still batch, without promising simultaneity ---------
    res5 = arena_mod.run_arena(
        "t5", tmp / "arena5", copies=5, max_concurrent=2,
        work_fn=lambda c, t, p: append_report(p, Report(
            copy_id=c.copy_id, task_id=t, status="ok",
            summary="mock", evidence=[f"approach={c.approach}", "e"])))
    check("5 copies with max 2 run in 3 waves, all distinct paths",
          res5["waves"] == 3
          and len({a["approach"] for a in res5["assignments"]}) == 5
          and res5["winner"] is not None)
    check("arena status still does not promise simultaneity",
          "NOT" in res5["status"] and "fleet" in res5["status"])

    print(f"ALL PASS (workdir: {tmp})")


if __name__ == "__main__":
    main()
