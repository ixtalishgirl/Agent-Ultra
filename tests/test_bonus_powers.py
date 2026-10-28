"""Tests for the bonus powers package. Run from ~/workspace/agent-ultra:

    python3 tests/test_bonus_powers.py

Proves WITHOUT a live model or a live browser:
  (a) the autonomous queue worker picks a task, checkpoints each
      step, resumes an interrupted task from its checkpoint, and
      never marks a task done without evidence;
  (b) a model tool call creates a self-made tool through the real
      pipeline, the model then USES it in a later round, and a
      failing tool is refused (never registered);
  (c) memory recall/save is a clean no-op when Supabase is
      unconfigured, and wires recall-before + save-after when a
      memory client is configured (fake client, no network);
  (d) the arena with mocked copies returns exactly one winner from
      report evidence, in waves, without promising simultaneity.

Prints PASS lines; exits non-zero on any failure. Any custom tool
file created by (b) is removed afterwards so the repo stays clean.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_ultra import arena as arena_mod  # noqa: E402
from agent_ultra import memory_loop  # noqa: E402
from agent_ultra import model_loop  # noqa: E402
from agent_ultra import task_queue  # noqa: E402
from agent_ultra.chat_store import ChatStore  # noqa: E402
from agent_ultra.report_protocol import Report, append_report  # noqa: E402

CUSTOM_DIR = Path(__file__).resolve().parent.parent / "agent_ultra" / "custom_tools"


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
    if not cond:
        raise SystemExit(1)


def cleanup_tools(*names):
    for name in names:
        for suffix in (".py", ".test_evidence.json"):
            (CUSTOM_DIR / f"{name}{suffix}").unlink(missing_ok=True)


class FakeModel:
    """Scripted stand-in for a live model: returns canned replies /
    tool calls in order, records every call."""

    def __init__(self, script):
        self.configured = True
        self.script = script
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": list(messages), "tools": tools})
        step = self.script[min(len(self.calls) - 1, len(self.script) - 1)]
        return step


def tool_call(call_id, name, args):
    return {"id": call_id, "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps(args)}}


class FakeMemory:
    """Stands in for a configured Supabase client (no network)."""

    def __init__(self):
        self.configured = True
        self.order = []
        self.saved = []

    def recall_memories(self, query=None, kind=None, limit=20):
        self.order.append("recall")
        return {"ok": True, "data": [{"content": "past row one"}]}

    def save_memory(self, content, kind="note", meta=None):
        self.order.append("save")
        self.saved.append((content, kind, meta))
        return {"ok": True}


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agent-ultra-powers-"))
    saved_env = {k: os.environ.pop(k) for k in ("SUPABASE_URL", "SUPABASE_KEY")
                 if k in os.environ}
    cleanup_tools("bonus_add_two", "bonus_bad_tool")
    try:
        # ------------------------------------------------ (a) queue
        queue = task_queue.TaskQueue(tmp / "queue.jsonl")
        t1 = queue.enqueue({"text": "probe one"})
        queue.enqueue({"text": "probe two"})

        def two_step_handler(task, prior_steps, checkpoint):
            for i in (1, 2):
                yield {"evidence": f"step {i} for {task['text']}",
                       "checkpoint": {"step": i}}

        res = task_queue.run_worker_once(queue, two_step_handler)
        check("(a) worker picks the oldest pending task first",
              res["task_id"] == t1["id"] and res["status"] == "done")
        rec = queue.get(t1["id"])
        check("(a) steps checkpointed with evidence",
              len(rec["steps"]) == 2
              and rec["steps"][1]["checkpoint"] == {"step": 2}
              and rec["status"] == "done")
        check("(a) second task still pending, untouched",
              queue.get(queue.list("pending")[0]["id"])["status"] == "pending")

        # Resume: its own queue — claim a task, record one step,
        # then "restart" with a fresh queue object on the same file.
        queue_r = task_queue.TaskQueue(tmp / "queue_resume.jsonl")
        t3 = queue_r.enqueue({"text": "resume me"})
        claimed = queue_r.claim_next()
        check("(a) claim takes the pending task",
              claimed["id"] == t3["id"] and claimed["status"] == "running")
        queue_r.record_step(claimed["id"], "resume step 1",
                            {"step": 1})
        queue_r2 = task_queue.TaskQueue(tmp / "queue_resume.jsonl")

        def resume_aware_handler(task, prior_steps, checkpoint):
            if prior_steps:
                return  # work already done: skip, prior evidence stands
            yield {"evidence": "fresh step", "checkpoint": {}}

        res = task_queue.run_worker_once(queue_r2, resume_aware_handler)
        check("(a) interrupted task resumes from its checkpoint",
              res["task_id"] == t3["id"] and res["status"] == "done"
              and len(queue_r2.get(t3["id"])["steps"]) == 1)

        # No evidence -> never marked done.
        queue_e = task_queue.TaskQueue(tmp / "queue_empty.jsonl")
        te = queue_e.enqueue({"text": "empty work"})

        def empty_handler(task, prior_steps, checkpoint):
            if prior_steps:
                return
            return
            yield  # a generator that yields nothing

        res = task_queue.run_worker_once(queue_e, empty_handler)
        check("(a) task with no evidence is error, never done",
              res["status"] == "error" and "no evidence" in res["error"])
        terec = queue_e.get(te["id"])
        check("(a) no-evidence task record is error, not done",
              terec["status"] == "error" and "no evidence" in terec["error"])

        # Default handler does real dispatcher work (no model).
        queue_d = task_queue.TaskQueue(tmp / "queue_dispatch.jsonl")
        queue_d.enqueue({"text": "dispatcher check"})
        res = task_queue.run_worker_once(queue_d,
                                         task_queue.dispatcher_check_handler)
        check("(a) default handler yields real dispatcher evidence",
              res["status"] == "done"
              and "dispatcher tool_count=" in
              queue_d.get(res["task_id"])["steps"][0]["evidence"])

        # ------------------------------------------- (b) self-made
        store = ChatStore(tmp / "power-chats")
        chat = store.create(title="tool chat")
        cid = chat["chat_id"]
        store.append_message(cid, "user", "make and use a tool")
        fake = FakeModel([
            {"ok": True, "reply": "", "tool_calls": [tool_call(
                "c1", "tool_create", {
                    "name": "bonus_add_two",
                    "description": "adds two numbers",
                    "source": "def bonus_add_two(a, b):\n    return a + b",
                    "arg_names": ["a", "b"],
                    "tests": [{"args": {"a": 2, "b": 3},
                               "expected": 5}]})]},
            {"ok": True, "reply": "", "tool_calls": [tool_call(
                "c2", "bonus_add_two", {"a": 10, "b": 32})]},
            {"ok": True, "reply": "used my new tool, got 42",
             "tool_calls": []},
        ])
        result = model_loop.run_model_reply(store, cid, client=fake)
        check("(b) model turn completes after create + use + reply",
              result.get("ok") is True)
        tool_names = [t["function"]["name"]
                      for t in (fake.calls[1]["tools"] or [])]
        check("(b) created tool is offered in a later round",
              "bonus_add_two" in tool_names)
        fed = fake.calls[2]["messages"]
        check("(b) custom tool result (42) fed back to model",
              any(m.get("role") == "tool" and "42" in m.get("content", "")
                  for m in fed))
        check("(b) tool file + evidence exist after creation",
              (CUSTOM_DIR / "bonus_add_two.py").exists()
              and (CUSTOM_DIR / "bonus_add_two.test_evidence.json").exists())
        msgs = store.get(cid)["messages"]
        check("(b) follow-up text stored as agent message",
              msgs[-1]["role"] == "agent"
              and msgs[-1]["text"] == "used my new tool, got 42")
        check("(b) tool schema sent to model carries no prose",
              set(model_loop.MODEL_TOOL_CREATE["function"].keys())
              == {"name", "parameters"}
              and "description" not in json.dumps(model_loop.MODEL_BROWSER_TOOL))

        # Failing tool is refused, never registered.
        chat2 = store.create(title="bad tool chat")
        cid2 = chat2["chat_id"]
        store.append_message(cid2, "user", "make a bad tool")
        bad = FakeModel([
            {"ok": True, "reply": "", "tool_calls": [tool_call(
                "c1", "tool_create", {
                    "name": "bonus_bad_tool",
                    "description": "adds, but tested wrong",
                    "source": "def bonus_bad_tool(a, b):\n    return a + b",
                    "arg_names": ["a", "b"],
                    "tests": [{"args": {"a": 2, "b": 3},
                               "expected": 999}]})]},
            {"ok": True, "reply": "noted, that tool failed its tests",
             "tool_calls": []},
        ])
        model_loop.run_model_reply(store, cid2, client=bad)
        check("(b) failing tool file is NOT registered",
              not (CUSTOM_DIR / "bonus_bad_tool.py").exists()
              and not (CUSTOM_DIR / "bonus_bad_tool.test_evidence.json").exists())
        fed_bad = bad.calls[1]["messages"]
        check("(b) failure report fed back, not a success",
              any(m.get("role") == "tool" and "NOT registered" in m.get("content", "")
                  for m in fed_bad))

        # ------------------------------------------------ (c) memory
        from agent_ultra.supabase_client import SupabaseClient
        bare = SupabaseClient()
        check("(c) Supabase client is unconfigured without env",
              bare.configured is False)
        rec = memory_loop.recall_before(bare, "hello")
        check("(c) recall is a clean no-op when unconfigured",
              rec == {"configured": False, "memories": []})
        sav = memory_loop.save_after(bare, "outcome")
        check("(c) save is a clean no-op when unconfigured",
              sav == {"configured": False, "saved": False})
        chat3 = store.create(title="memory chat")
        cid3 = chat3["chat_id"]
        store.append_message(cid3, "user", "hello with memory")
        plain = FakeModel([{"ok": True, "reply": "memory reply",
                            "tool_calls": []}])
        out = memory_loop.run_reply_with_memory(store, cid3, client=plain,
                                                memory_client=bare)
        check("(c) reply still works with memory unconfigured",
              out["reply"].get("ok") is True
              and out["memory"]["configured"] is False
              and out["saved"]["saved"] is False)
        fake_mem = FakeMemory()
        chat4 = store.create(title="memory chat 2")
        cid4 = chat4["chat_id"]
        store.append_message(cid4, "user", "hello again")
        plain2 = FakeModel([{"ok": True, "reply": "second reply",
                             "tool_calls": []}])
        out2 = memory_loop.run_reply_with_memory(store, cid4, client=plain2,
                                                 memory_client=fake_mem)
        check("(c) recall runs before the model call, save after",
              fake_mem.order == ["recall", "save"])
        check("(c) recalled row reaches the model call verbatim",
              any(m.get("content") == "past row one"
                  for m in plain2.calls[0]["messages"]))
        check("(c) outcome saved as a conversation row",
              fake_mem.saved and fake_mem.saved[0][0] == "second reply"
              and fake_mem.saved[0][1] == "conversation")

        # ------------------------------------------------ (d) arena
        def mock_work_factory(specs):
            def work_fn(copy, task_id, log_path):
                status, n = specs[copy.copy_id]
                append_report(log_path, Report(
                    copy_id=copy.copy_id, task_id=task_id, status=status,
                    summary=f"mock {copy.copy_id}",
                    evidence=[f"e{i}" for i in range(n)]))
            return work_fn

        specs = {"arena-0001": ("ok", 3), "arena-0002": ("ok", 1),
                 "arena-0003": ("error", 0)}
        res = arena_mod.run_arena("t1", tmp / "arena1", copies=3,
                                  max_concurrent=10,
                                  work_fn=mock_work_factory(specs))
        check("(d) arena returns exactly one winner from evidence",
              res["winner"] is not None
              and res["winner"]["copy_id"] == "arena-0001"
              and res["reports"] == 3)
        check("(d) winner is the highest mechanical score, not a claim",
              res["winner"]["status"] == "ok"
              and len(res["winner"]["evidence"]) == 3)
        res5 = arena_mod.run_arena(
            "t2", tmp / "arena2", copies=5, max_concurrent=2,
            work_fn=lambda c, t, p: append_report(p, Report(
                copy_id=c.copy_id, task_id=t, status="ok",
                summary="mock", evidence=["e"])))
        check("(d) 5 copies with max 2 run in 3 waves",
              res5["waves"] == 3 and res5["copies"] == 5
              and res5["winner"] is not None)
        check("(d) arena status does not promise simultaneity",
              "NOT" in res5["status"] and "fleet" in res5["status"])
        res1 = arena_mod.run_arena(
            "t3", tmp / "arena3", copies=1,
            work_fn=lambda c, t, p: append_report(p, Report(
                copy_id=c.copy_id, task_id=t, status="ok",
                summary="solo", evidence=["e"])))
        check("(d) single copy wins by default",
              res1["winner"] is not None and res1["waves"] == 1)
    finally:
        cleanup_tools("bonus_add_two", "bonus_bad_tool")
        for k, v in saved_env.items():
            os.environ[k] = v

    print(f"ALL PASS (workdir: {tmp})")


if __name__ == "__main__":
    main()
