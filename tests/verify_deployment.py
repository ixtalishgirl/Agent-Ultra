"""Deployment verification suite — prints REAL pass/fail per piece.

RULE: this suite NEVER prints a pass for something it did not run.
- DOCKER-ABSENT: docker is not installed on this host; no build ran.
- NOT CONFIGURED: an integration's env vars are absent; no call ran.
- UNTESTED / BROWSER-ABSENT: Playwright/Chromium missing; no live
  browser action ran, and no browser timing is claimed.
- Timings shown (ms) are measured with perf_counter on THIS run.
- The secret scan reads file contents; it prints file+line on a hit
  and NEVER prints a matched secret value (only the pattern name).

Exit code: 0 when nothing FAILED (NOT CONFIGURED / ABSENT / UNTESTED
are not failures — they are honest pending states). 1 on any FAIL.

Run:  python3 tests/verify_deployment.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = []  # (name, verdict, detail)


def report(name, verdict, detail=""):
    RESULTS.append((name, verdict, detail))
    print(f"[{verdict}] {name}" + (f" — {detail}" if detail else ""))


def timed(fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        return out, round((time.perf_counter() - t0) * 1000, 1)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}, round(
            (time.perf_counter() - t0) * 1000, 1)


def main():
    print("Agent-Ultra deployment verification")
    print(f"repo root: {ROOT}")
    print()

    # ------------------------------------------------------------ env
    print("== env vars (names only, values never printed) ==")
    for var in ("MODEL_API_URL", "SUPABASE_URL", "SUPABASE_KEY",
                "DRIVE_REFRESH_TOKEN", "DRIVE_CLIENT_ID",
                "DRIVE_CLIENT_SECRET", "DRIVE_SERVICE_ACCOUNT_JSON",
                "DRIVE_ACCESS_TOKEN", "DRIVE_TOOL_FOLDER_ID"):
        print(f"  {var}: {'set' if os.environ.get(var) else 'unset'}")
    print()

    # ------------------------------------------------------------ docker
    print("== docker build ==")
    docker = shutil.which("docker")
    if not docker:
        report("docker build", "DOCKER-ABSENT",
               "docker is not installed on this host; no build ran")
    else:
        try:
            proc = subprocess.run(
                ["docker", "build", "-t", "agent-ultra:verify", "."],
                cwd=str(ROOT), capture_output=True, text=True, timeout=600)
            if proc.returncode == 0:
                report("docker build", "PASS", "image agent-ultra:verify built")
            else:
                report("docker build", "FAIL",
                       proc.stderr.strip().splitlines()[-1][:300]
                       if proc.stderr.strip() else "unknown build error")
        except subprocess.TimeoutExpired:
            report("docker build", "FAIL", "build timed out after 600s")
    print()

    # ------------------------------------------------------------ shell
    print("== shell tool (real subprocess) ==")
    from agent_ultra import shell_tool
    res, ms = timed(lambda: shell_tool.run("echo hello-shell && pwd"))
    if res.get("ok") and "hello-shell" in res.get("stdout", ""):
        report("shell: echo+pwd", "PASS", f"{ms} ms, cwd={res['cwd']}")
    else:
        report("shell: echo+pwd", "FAIL", json.dumps(res)[:300])
    res, ms = timed(lambda: shell_tool.run_python("print(2 + 3)"))
    if res.get("ok") and res.get("stdout", "").strip() == "5":
        report("shell: python3 -c", "PASS", f"{ms} ms, output=5")
    else:
        report("shell: python3 -c", "FAIL", json.dumps(res)[:300])
    res, _ = timed(lambda: shell_tool.run("echo x", cwd="/etc"))
    if not res.get("ok") and "outside the agent workdir" in res.get("stderr", ""):
        report("shell: workdir scoping", "PASS",
               "outside-root cwd refused (container boundary)")
    else:
        report("shell: workdir scoping", "FAIL", json.dumps(res)[:300])
    print()

    # ------------------------------------------------------------ tools
    print("== extra tools (real calls) ==")
    from agent_ultra import tools_extra
    res, ms = timed(lambda: tools_extra.dispatch_tool(
        "calculator", {"expression": "2 + 3 * 4"}))
    if res.get("status") == "ok" and res.get("result") == 14:
        report("tool: calculator", "PASS", f"{ms} ms, 2+3*4=14")
    else:
        report("tool: calculator", "FAIL", json.dumps(res)[:300])
    res, ms = timed(lambda: tools_extra.dispatch_tool(
        "weather", {"place": "London"}))
    if res.get("status") == "ok":
        report("tool: weather", "PASS",
               f"{ms} ms, {str(res.get('place') or res)[:120]}")
    else:
        report("tool: weather", "FAIL", json.dumps(res)[:300])
    res, ms = timed(lambda: tools_extra.dispatch_tool(
        "internet_fetch", {"url": "https://example.org"}))
    if res.get("status") == "ok":
        report("tool: internet_fetch", "PASS",
               f"{ms} ms, example.org fetched")
    else:
        report("tool: internet_fetch", "FAIL", json.dumps(res)[:300])
    print()

    # ------------------------------------------------------------ browser
    print("== browser tools (Playwright) ==")
    from agent_ultra import browser_tools
    if not browser_tools.playwright_available():
        report("browser: playwright", "BROWSER-ABSENT",
               "playwright package not installed; no live action ran, "
               "no browser timing claimed")
    else:
        report("browser: playwright", "PASS", "package imports")
        session = browser_tools.BrowserSession(
            ROOT / "work" / "_verify-profile")
        try:
            t0 = time.perf_counter()
            session.start()
            start_ms = round((time.perf_counter() - t0) * 1000, 1)
            res = session.act("goto", url="https://example.org")
            report("browser: goto example.org",
                   "PASS" if res["ok"] else "FAIL",
                   f"{res['ms']} ms (session start {start_ms} ms), "
                   f"{json.dumps(res['detail'])[:200]}")
            session.close()
        except browser_tools.BrowserNotAvailable as exc:
            attempt_ms = round((time.perf_counter() - t0) * 1000, 1) \
                if 't0' in dir() else 0
            report("browser: session start", "BROWSER-ABSENT",
                   f"Chromium unavailable ({exc}); attempt took "
                   f"{attempt_ms} ms — this is the failure-path time, "
                   "not an action timing")
    # browser tool registry is real regardless of a live browser
    tools = browser_tools.list_browser_tools()
    expected = {"click", "scroll_down", "scroll_up", "copy", "paste",
                "move", "type", "goto", "back", "forward", "reload",
                "screenshot", "wait_for_selector", "get_text",
                "select_option", "drag", "hover"}
    names = {t["tool"] for t in tools}
    if expected.issubset(names):
        report("browser: tool registry", "PASS",
               f"{len(tools)} actions registered, required set present")
    else:
        report("browser: tool registry", "FAIL",
               f"missing: {sorted(expected - names)}")
    from agent_ultra.browser_profile import GoogleProfile
    gstat = GoogleProfile(ROOT / "work" / "_verify-google").status()
    report("browser: Google primary profile", "UNTESTED" if gstat["status"] in
           ("no-profile-yet", "no-google-cookies", "unreadable") else "PASS",
           f"status={gstat['status']}, cookies_db_exists="
           f"{gstat['cookies_db_exists']} (owner signs in herself; "
           "no password stored, no automated login)")
    print()

    # ------------------------------------------------------------ integrations
    print("== integrations (env-gated, never faked) ==")
    from agent_ultra.supabase_client import SupabaseClient
    from agent_ultra.drive_client import DriveClient
    from agent_ultra.model_client import ModelClient
    sstat = SupabaseClient().status()
    report("supabase", "NOT CONFIGURED" if not sstat["configured"] else "PASS",
           sstat["detail"][:160])
    dstat = DriveClient().status()
    report("drive", "NOT CONFIGURED" if not dstat["configured"] else "PASS",
           dstat["detail"][:160])
    mstat = ModelClient().status()
    if not mstat["configured"]:
        report("model (tunnel)", "NOT CONFIGURED", mstat["detail"][:160])
    else:
        health, ms = timed(lambda: ModelClient().health())
        report("model (tunnel) health",
               "PASS" if health.get("live") else "FAIL",
               f"{ms} ms, {json.dumps(health)[:200]}")
    print()

    # ------------------------------------------------------------ secret scan
    print("== secret scan (values never printed) ==")
    patterns = [
        ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
        ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
        ("aws-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
        ("api-key-literal", re.compile(r"sk-[A-Za-z0-9]{16,}")),
        ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
        ("key-assignment-literal", re.compile(
            r"(?i)(api[_-]?key|secret|passwd|password)\s*[:=]\s*['\"][^'\"\n]{8,}['\"]")),
    ]
    hits = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if rel.parts[0] in (".git", "__pycache__") or "work" in rel.parts \
                or "__pycache__" in rel.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pname, pat in patterns:
                if pat.search(line):
                    hits.append(f"{rel}:{line_no} [{pname}]")
    if hits:
        for hit in hits[:20]:
            print(f"  HIT {hit}")
        report("secret scan", "FAIL", f"{len(hits)} suspicious literal(s)")
    else:
        report("secret scan", "PASS",
               "no secret literals in repo files (env-only holds)")
    print()

    # ------------------------------------------------------------ summary
    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"SUMMARY: {len(RESULTS)} checks, {len(fails)} FAIL")
    for name, verdict, detail in RESULTS:
        print(f"  [{verdict}] {name}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
