# Bonus Powers — verified status

Bonus capabilities beyond a plain chat assistant, built locally in
this repo. Nothing here is pushed or deployed yet. No blanket
"all working" claim is made: each power below states exactly what
was proven by a real test run and what still needs a live model,
a live browser, or a configured integration.

## 1. Autonomous mode — WORKING (proven, no model needed)

- Code: `agent_ultra/task_queue.py` (queue + worker + handlers).
- How: tasks are records in a file-backed JSONL queue. The worker
  claims the oldest pending task (or resumes an interrupted running
  one), runs the handler, and checkpoints every evidence step to
  the queue file. No task runs without a queue entry. A task with
  zero evidence steps is marked `error` ("no evidence"), never
  `done`. On restart the handler receives prior steps + the last
  checkpoint and skips finished work.
- Default handler: real dispatcher bridge check (tool count).
  A model-driven handler (`model_chat_handler`) is provided for
  use when a model is configured.
- Proven by: `tests/test_bonus_powers.py` section (a) — pick order,
  checkpointing, resume, no-evidence refusal, real dispatcher step.
- UNTESTED: a model-driven autonomous task run (needs a live
  model); multi-worker use (single-worker by design, no locking
  claimed).

## 2. Self-made tools, live in the loop — WORKING (proven, mocked model)

- Code: `agent_ultra/model_loop.py` (tool_create + custom dispatch)
  on top of the existing `agent_ultra/tool_pipeline.py` (5 stages).
- How: the model gets a `tool_create` tool (name + parameter
  schema only, no prose). A call runs the real pipeline: intake,
  validated_call (name/collision/source checks), execute (write,
  import, run declared tests), evidence (sha256 + per-test file),
  report. A tool whose tests fail is NOT registered — its file is
  removed and the failure is fed back. On success the new tool is
  offered in later rounds of the same turn and dispatches through
  `dispatch_custom` (validated at call time). Custom tools are
  pure computation only (no imports, no eval/exec/open, no dunders).
- Proven by: `tests/test_bonus_powers.py` section (b) — create a
  tool, use it in a later round (10 + 32 = 42 fed back), and a
  failing tool refused with no file left behind.
- UNTESTED: a REAL model deciding to create and use a tool (needs
  a live model that emits `tool_calls`); the pipeline is NOT a
  sandbox — a registered tool runs with the agent's own privileges
  inside its own container.

## 3. Persistent memory in the loop — WIRING REAL, live use UNTESTED

- Code: `agent_ultra/memory_loop.py` on `agent_ultra/supabase_client.py`.
- How: before a model call, `recall_before` recalls memories
  (query = the last user message); recalled rows — the owner's own
  stored rows, verbatim — ride along as extra messages. After the
  call, `save_after` saves the agent reply as a conversation row.
  When Supabase is NOT configured, both are clean no-ops: empty
  recall, unsaved outcome, reported as such, never fake rows.
- Proven by: `tests/test_bonus_powers.py` section (c) — no-op
  with no env vars, and recall-before/save-after ordering with a
  fake memory client (no network).
- UNTESTED: a real Supabase recall/save (needs SUPABASE_URL +
  SUPABASE_KEY configured on the running host); the memories table
  itself must exist in the project.

## 4. Arena of copies — WORKING, head-managed (proven, mocked + real paths)

- Code: `agent_ultra/arena.py` on `spawner.py` + `head.py` +
  `report_protocol.py` + `copy_agent.py` (approach pool + executor).
- The managed flow, in order (documented in `arena.py` so the
  model clearly knows it):
  1. ORDER BROADCAST — the head gives the order to EVERY copy:
     one order record per copy in `orders.jsonl`, each carrying
     the task and that copy's assigned approach.
  2. DISTINCT PER-COPY APPROACH — for ONE task, every copy tries
     a DIFFERENT path (alag alag rastay): dispatcher count, extra
     calculator, custom-tools list, browser registry, shell echo,
     Supabase status, Drive status, text understanding. The arena
     REFUSES to run when copies exceed distinct approaches
     (ValueError) rather than duplicating a path.
  3. INDEPENDENT WORK — copies work in waves of at most
     `max_concurrent` (default 10) — sequential batches on this
     host, because containers are UNTESTED here.
  4. RESULT REPORTS — each copy reports through the report
     protocol (`reports.jsonl`): status + evidence, with its
     approach named in the evidence.
  5. HEAD COMPARISON — only after the waves finish, the head
     examines EVERY returned report and ranks them on evidence.
  6. JUDGED WINNER — the bracket yields exactly one winner (or
     None when no copy reported); copies that never reported are
     listed as missing, not silently dropped.
- Proven by: `tests/test_arena_management.py` (13 checks) —
  distinct broadcast approaches, every report naming its own
  approach, comparison covering every report, one judged winner,
  pool-exhaustion + duplicate refusal, waves; plus
  `tests/test_bonus_powers.py` section (d) still passing.
- NOT promised: 1000 simultaneous copies. With waves, 1000 copies
  means ceil(1000 / max_concurrent) sequential waves; true
  simultaneity needs a fleet. Quality judging by a model is
  UNTESTED and is not claimed — the head judges mechanically on
  report evidence.

## Standing rules kept in all four powers

- No prompt content: no system prompt, no example messages, no
  descriptive prose sent to the model. Tool/queue schemas carry
  names + parameter names/types only.
- No secrets, tokens, keys, or passwords in any file.
- No fake claims: anything needing a live model, a live browser,
  or a configured integration is labeled UNTESTED above.
- Not pushed to GitHub, not deployed to Render, training
  notebooks untouched.

## Tests

- `python3 tests/test_bonus_powers.py` — 28 checks, ALL PASS.
- `python3 tests/test_arena_management.py` — 13 checks, ALL PASS.
- `python3 tests/test_model_browser_loop.py` — 16/16 PASS.
- `python3 tests/smoke_test.py` — 72/72 PASS.
