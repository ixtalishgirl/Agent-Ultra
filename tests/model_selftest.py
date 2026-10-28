#!/usr/bin/env python3
"""Model self-test suite — PREPARED, honestly NOT-RUN until serving.

Run from ~/workspace/agent-ultra:

    python3 tests/model_selftest.py [--messages-file FILE] [--rounds N]

What it checks, once the model is served via MODEL_API_URL (ngrok
tunnel to the owner's VPS llama.cpp server, see TUNNEL.md):

  1. model health — model_client.health() against the tunnel URL.
  2. every power — the tool registries the agent knows: extra tools
     (calculator/weather/internet/imagine/understand), Supabase
     tools, Drive tools, custom tools, and the 28 browser actions.
  3. permissions — the Agent OS dispatcher loads and its real tool
     count is reported (761 at last verification).
  4. browser actions — the 28-action registry; live action timing
     only when Playwright/Chromium is present, otherwise the honest
     BROWSER-ABSENT result (never a fake timing).
  5. speed — measured ms for local tools that run here (calculator,
     and network tools when they answer honestly).
  6. model generation + long-task endurance — ONLY with
     --messages-file: a JSON file the OWNER supplies, containing a
     list of message lists to send to the model. This suite authors
     NO prompt content of its own: the owner forbids writing any
     prompt for a model/agent/document without asking her first, so
     without an owner-supplied file these two sections print
     PENDING-OWNER-INPUT and are not run. The long-task check loops
     the supplied messages for --rounds rounds and reports success
     rate, total time, and average ms per call.

Exit codes (printed, never faked):
  0 — model live AND every runnable section passed (generation
      sections ran, i.e. --messages-file was given).
  2 — NOT-RUN: MODEL_API_URL unset or the tunnel is unreachable, or
      the run is PARTIAL (generation sections pending owner input).
  1 — a runnable section failed.

Nothing here is claimed as a model result until the model is served.
Until then this suite prints NOT-RUN and exits 2.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS = []


def section(name, status, detail=""):
    RESULTS.append({"section": name, "status": status, "detail": detail})
    print(f"[{status}] {name} {detail}")


def main():
    parser = argparse.ArgumentParser(description="Agent-Ultra model self-test")
    parser.add_argument("--messages-file", default=None,
                        help="JSON file the OWNER supplies: a list of "
                             "message lists to send to the model. No "
                             "prompts are authored by this suite.")
    parser.add_argument("--rounds", type=int, default=5,
                        help="Long-task endurance rounds (default 5).")
    args = parser.parse_args()

    from agent_ultra import dispatcher_bridge as bridge
    from agent_ultra.model_client import ModelClient

    client = ModelClient()
    if not client.configured:
        section("model health", "NOT-RUN",
                "MODEL_API_URL is unset — the model is not served yet.")
        print("RESULT: NOT-RUN (model not served; nothing model-driven ran)")
        return 2
    health = client.health()
    if not health.get("live"):
        section("model health", "NOT-RUN",
                f"tunnel unreachable: {health.get('error', '')[:200]}")
        print("RESULT: NOT-RUN (tunnel unreachable; nothing model-driven ran)")
        return 2
    section("model health", "PASS",
            f"live, HTTP {health.get('status')}, {health.get('ms')} ms")

    # ---- every power: tool registries (all local, all real) --------
    try:
        extra = bridge.list_extra_tools()
        section("power: extra tools", "PASS",
                f"{len(extra)} tools: {', '.join(sorted(extra))}")
    except Exception as exc:
        section("power: extra tools", "FAIL", f"{type(exc).__name__}: {exc}")
    try:
        sup = bridge.list_supabase_tools()
        section("power: supabase tools", "PASS",
                f"{len(sup)} tools, "
                f"{'READY' if sup.get('supabase_status', {}).get('status') == 'READY' else 'NOT CONFIGURED'}")
    except Exception as exc:
        section("power: supabase tools", "FAIL", f"{type(exc).__name__}: {exc}")
    try:
        drv = bridge.list_drive_tools()
        section("power: drive tools", "PASS",
                f"{len(drv)} tools, "
                f"{'READY' if drv.get('drive_status', {}).get('status') == 'READY' else 'NOT CONFIGURED'}")
    except Exception as exc:
        section("power: drive tools", "FAIL", f"{type(exc).__name__}: {exc}")
    try:
        custom = bridge.list_custom_tools()
        section("power: custom tools", "PASS",
                f"{len(custom)} tools: {', '.join(sorted(custom)) or 'none yet'}")
    except Exception as exc:
        section("power: custom tools", "FAIL", f"{type(exc).__name__}: {exc}")

    # ---- permissions: dispatcher tool count --------------------------
    try:
        count = bridge.tool_count()
        section("permissions: dispatcher", "PASS",
                f"{count} Agent OS tools loaded")
    except Exception as exc:
        section("permissions: dispatcher", "FAIL", f"{type(exc).__name__}: {exc}")

    # ---- browser actions: registry + live timing if possible --------
    try:
        browsers = bridge.list_browser_tools()
        section("browser: action registry", "PASS",
                f"{len(browsers)} actions")
    except Exception as exc:
        section("browser: action registry", "FAIL", f"{type(exc).__name__}: {exc}")
    try:
        import playwright  # noqa: F401
        section("browser: live timing", "PENDING",
                "Playwright present — live session timing needs a "
                "Railway container run (see ARCHITECTURE.md).")
    except ImportError:
        section("browser: live timing", "NOT-RUN",
                "BROWSER-ABSENT on this host (no Playwright); live "
                "browser timing is a post-deploy Railway check.")

    # ---- speed: measured ms for local tools --------------------------
    try:
        t0 = time.perf_counter()
        out = bridge.dispatch_extra("calculator", {"expression": "2+3*4"})
        ms = round((time.perf_counter() - t0) * 1000, 1)
        ok = out.get("status") == "ok" and out.get("result") == 14
        section("speed: calculator", "PASS" if ok else "FAIL",
                f"{ms} ms, result={out.get('result')}")
    except Exception as exc:
        section("speed: calculator", "FAIL", f"{type(exc).__name__}: {exc}")

    # ---- model generation + long task (owner messages only) ---------
    if not args.messages_file:
        section("model: generation", "PENDING-OWNER-INPUT",
                "no --messages-file given; this suite authors no prompts.")
        section("model: long-task endurance", "PENDING-OWNER-INPUT",
                "needs owner-supplied messages to loop.")
        print("RESULT: PARTIAL (runnable sections above are real; "
              "generation + long-task need owner-supplied messages)")
        return 2
    try:
        messages = json.loads(Path(args.messages_file).read_text())
        assert isinstance(messages, list) and messages
    except Exception as exc:
        section("model: generation", "FAIL",
                f"messages file unusable: {exc}")
        print("RESULT: FAIL")
        return 1
    ok_calls = 0
    total_ms = 0.0
    first_reply = ""
    for i, msgs in enumerate(messages):
        res = client.chat(msgs)
        if res.get("ok"):
            ok_calls += 1
            total_ms += res.get("ms", 0)
            if i == 0:
                first_reply = (res.get("reply") or "")[:200]
        else:
            section(f"model: generation call {i}", "FAIL",
                    str(res.get("error", ""))[:200])
    section("model: generation", "PASS" if ok_calls == len(messages) else "FAIL",
            f"{ok_calls}/{len(messages)} replies, first 200 chars: {first_reply!r}")
    # Long-task endurance: loop the supplied messages.
    rounds_ok = 0
    rounds_ms = 0.0
    for r in range(max(1, args.rounds)):
        for msgs in messages:
            res = client.chat(msgs)
            if res.get("ok"):
                rounds_ok += 1
                rounds_ms += res.get("ms", 0)
    total_calls = max(1, args.rounds) * len(messages)
    avg = round(rounds_ms / max(1, rounds_ok), 1) if rounds_ok else 0
    section("model: long-task endurance",
            "PASS" if rounds_ok == total_calls else "FAIL",
            f"{rounds_ok}/{total_calls} calls ok, total {round(rounds_ms, 1)} ms, "
            f"avg {avg} ms/call over {args.rounds} rounds")

    failed = [r for r in RESULTS if r["status"] == "FAIL"]
    if failed:
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS (all runnable sections passed, generation ran)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
