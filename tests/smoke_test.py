"""Smoke test for the Agent-Ultra scaffold. Run from ~/workspace/agent-ultra:

    python3 tests/smoke_test.py

Asserts only what this scaffold really does: copy dirs + browser
profiles exist, reports land in JSONL, the head bracket ends with one
winner, the AG-UI skeleton answers /health, and the dispatcher bridge
loads the real 761 Agent OS tools — PLUS the revision checks: the
calculator really computes (and refuses unsafe input), weather /
internet tools return real data or report the failure honestly,
imagine saves real image bytes or reports the provider failure
honestly, per-chat delete removes only that chat (never outside the
agent-ultra workdirs), the chat UI files exist with the browser panel
and per-row delete buttons, and the chat server API works end to end.

Prints PASS lines; exits non-zero on any failure. Network-dependent
checks accept an honest error result (never a fake one) so the suite
also passes on a host without internet — but the output then says
plainly which tools fell back to honest errors.
"""

import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_ultra import HeadAgent, Spawner, ChatStore  # noqa: E402
from agent_ultra import dispatcher_bridge as bridge  # noqa: E402
from agent_ultra import tools_extra  # noqa: E402
from agent_ultra.agui_server import serve as agui_serve  # noqa: E402
from agent_ultra.chat_server import serve as chat_serve  # noqa: E402
from agent_ultra.report_protocol import read_reports  # noqa: E402


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}: {name} {detail}")
    if not cond:
        raise SystemExit(1)


def http(method, url, body=None):
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agent-ultra-test-"))
    root = Path(__file__).resolve().parent.parent

    # ---- original skeleton checks -----------------------------------
    spawner = Spawner(tmp / "copies")
    copies = spawner.spawn(3)
    check("spawn 3 copies", len(copies) == 3)
    for c in copies:
        check(f"copy dir {c.copy_id}", c.workdir.is_dir())
        check(f"browser profile {c.copy_id}", c.browser.path.is_dir())
        check(f"profile meta {c.copy_id}", (c.browser.path / "PROFILE.json").is_file())
    try:
        copies[0].browser.launch()
        check("browser launch refuses (UNTESTED)", False)
    except NotImplementedError:
        check("browser launch refuses (UNTESTED)", True)

    log_path = tmp / "reports.jsonl"
    for c in copies:
        c.work("smoke-001", log_path)
    reports = read_reports(log_path)
    check("3 reports in JSONL", len(reports) == 3, f"got {len(reports)}")
    check("reports ok", all(r["status"] == "ok" for r in reports))

    head = HeadAgent(log_path)
    rounds, winner = head.run_bracket(head.collect())
    check("bracket ends with 1 winner", winner is not None, f"winner={winner}")
    check("bracket rounds shrink", all(len(r) < 3 for r in rounds) if rounds else True)

    count = bridge.tool_count()
    check("dispatcher bridge loads Agent OS tools", count == 761, f"count={count}")

    server = agui_serve(0)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as resp:
            body = json.loads(resp.read())
        check("AG-UI /health ok", body.get("status") == "ok")
        check("AG-UI marked UNTESTED", body.get("agui_protocol") == "UNTESTED")
    finally:
        server.shutdown()

    # ---- calculator: real math, safe parsing ------------------------
    check("calculator 2+3*4=14", tools_extra.calculator("2+3*4").get("result") == 14)
    check("calculator (10-2)/4=2", tools_extra.calculator("(10-2)/4").get("result") == 2.0)
    check("calculator sqrt(16)=4", tools_extra.calculator("sqrt(16)").get("result") == 4.0)
    check(
        "calculator refuses import",
        tools_extra.calculator("__import__('os')")["status"] == "error",
    )
    check(
        "calculator refuses names",
        tools_extra.calculator("os.system('id')")["status"] == "error",
    )
    check(
        "calculator refuses division by zero as error",
        tools_extra.calculator("1/0")["status"] == "error",
    )

    # ---- weather / internet: real data or honest error ---------------
    wx = tools_extra.weather("London")
    check(
        "weather real-or-honest",
        (wx["status"] == "ok" and "temperature_2m" in wx)
        or (wx["status"] == "error" and bool(wx.get("detail"))),
        f"status={wx['status']}",
    )
    fetched = tools_extra.internet_fetch("https://example.org")
    check(
        "internet fetch real-or-honest",
        (fetched["status"] == "ok" and fetched.get("text_length", 0) > 0)
        or (fetched["status"] == "error" and bool(fetched.get("detail"))),
        f"status={fetched['status']}",
    )
    found = tools_extra.internet_search("Open-Meteo")
    check(
        "internet search real-or-honest",
        (found["status"] == "ok" and len(found.get("results", [])) >= 1)
        or (found["status"] == "error" and bool(found.get("detail"))),
        f"status={found['status']}",
    )

    # ---- imagine: real bytes or honest error, never a fake file ------
    img = tools_extra.imagine("a red circle", tmp / "images")
    if img["status"] == "ok":
        p = Path(img["path"])
        check("imagine saves real image bytes", p.is_file() and p.stat().st_size > 1000,
              f"bytes={img.get('bytes')}")
    else:
        check("imagine reports provider failure honestly", bool(img.get("detail")),
              f"detail={img.get('detail')}")

    # ---- understand: real extractive summary, image refuses ----------
    understood = tools_extra.understand_text(
        "Cats are small mammals. Cats sleep for long hours every day. "
        "Dogs are loyal animals. Dogs enjoy long walks in the park."
    )
    check("understand text ok", understood["status"] == "ok")
    check("understand key sentences", len(understood.get("key_sentences", [])) >= 1)
    check("understand word count", understood.get("words", 0) > 10)
    img_under = tools_extra.dispatch_tool("understand_image", {"path": "x.png"})
    check("understand image refuses (UNTESTED)",
          img_under["status"] == "error" and img_under.get("untested") is True)

    # ---- extra tools wired into the bridge ----------------------------
    extra = bridge.list_extra_tools()
    for name in ("calculator", "weather", "internet_fetch", "internet_search",
                 "imagine", "understand_text", "understand_image"):
        check(f"bridge lists extra tool {name}", name in extra)
    check("bridge dispatches calculator",
          bridge.dispatch_extra("calculator", {"expression": "7*6"}).get("result") == 42)

    # ---- per-chat delete: only that chat, never outside --------------
    store = ChatStore(tmp / "chats", copies_base=tmp / "copies")
    chat_a = store.create(title="chat A")
    chat_b = store.create(title="chat B")
    store.append_message(chat_a["chat_id"], "user", "hello A")
    store.append_message(chat_b["chat_id"], "user", "hello B")
    # Linked copy dir inside the allowed base must be removed too.
    linked = tmp / "copies" / "copy-9999"
    (linked / "workspace").mkdir(parents=True)
    (linked / "workspace" / "marker.txt").write_text("x")
    chat_c = store.create(title="chat C", copy_dir=str(linked))
    # Copy dir OUTSIDE the allowed base must be refused, never deleted.
    outside = tmp / "outside-copy"
    outside.mkdir()
    (outside / "marker.txt").write_text("do not delete")
    chat_d = store.create(title="chat D", copy_dir=str(outside))

    result = store.delete(chat_a["chat_id"])
    check("delete removes chat A dir", not store.chat_dir(chat_a["chat_id"]).exists())
    check("delete keeps chat B", store.exists(chat_b["chat_id"]))
    check("delete keeps chat B messages",
          store.get(chat_b["chat_id"])["messages"][0]["text"] == "hello B")
    store.delete(chat_c["chat_id"])
    check("delete removes linked copy dir inside base", not linked.exists())
    result_d = store.delete(chat_d["chat_id"])
    check("delete refuses copy dir outside base",
          result_d.get("copy_dir") == "REFUSED-OUTSIDE-BASE")
    check("outside copy dir untouched", (outside / "marker.txt").is_file())
    try:
        store.delete("no-such-chat")
        check("delete unknown chat raises", False)
    except KeyError:
        check("delete unknown chat raises", True)
    try:
        store.delete("../escape")
        check("delete rejects path traversal id", False)
    except ValueError:
        check("delete rejects path traversal id", True)

    # ---- chat UI files exist, with panel + per-row delete ------------
    index = (root / "agent_ultra" / "ui" / "index.html").read_text()
    check("UI index exists with browser panel", "browser-panel" in index)
    check("UI index has chat list container", "chat-list" in index)
    check("UI index has no baked-in fake chats", "lorem" not in index.lower())
    css = (root / "agent_ultra" / "ui" / "style.css").read_text()
    check("UI CSS is real styling", len(css) > 1000 and ".sidebar" in css)
    check("UI CSS styles per-row delete button", ".chat-delete" in css)
    js = (root / "agent_ultra" / "ui" / "app.js").read_text()
    check("UI JS talks to chat API", "/api/chats" in js and "DELETE" in js)
    check("UI JS creates per-row delete button", "chat-delete" in js)

    # ---- Supabase + Drive wired into the bridge; custom tools --------
    check("bridge lists supabase tools",
          "supabase_save_memory" in bridge.list_supabase_tools())
    check("bridge supabase dispatch is honest NOT CONFIGURED",
          bridge.dispatch_supabase(
              "supabase_save_memory", {"content": "probe"}).get("configured") is False)
    check("bridge lists drive tools",
          "drive_list_tools" in bridge.list_drive_tools())
    check("bridge drive dispatch is honest NOT CONFIGURED",
          bridge.dispatch_drive(
              "drive_list_tools", {}).get("configured") is False)
    check("bridge lists agent-created custom tool",
          "text_counts" in bridge.list_custom_tools())
    _cout = bridge.dispatch_custom("text_counts", {"text": "one two three"})
    check("bridge dispatches custom tool with real output",
          _cout.get("status") == "ok"
          and _cout.get("result") == {"words": 3, "chars": 13, "lines": 1})
    check("UI CSS carries the self-mod focus rule",
          "focus-visible" in css)

    # ---- chat server API end to end -----------------------------------
    chat_server = chat_serve(0, base_dir=tmp / "srv-chats")
    sport = chat_server.server_address[1]
    sthread = threading.Thread(target=chat_server.serve_forever, daemon=True)
    sthread.start()
    try:
        base = f"http://127.0.0.1:{sport}"
        with urllib.request.urlopen(base + "/", timeout=10) as resp:
            page = resp.read().decode("utf-8", "replace")
            code = resp.status
        check("chat server serves UI", code == 200 and "browser-panel" in page)
        code, created = http("POST", base + "/api/chats", {"title": "srv chat"})
        check("chat server creates chat", code == 201 and "chat_id" in created)
        cid = created["chat_id"]
        code, _ = http("POST", base + f"/api/chats/{cid}/messages",
                       {"role": "user", "text": "hi server"})
        check("chat server appends message", code == 201)
        code, got = http("GET", base + f"/api/chats/{cid}")
        check("chat server returns message",
              code == 200 and got["messages"][0]["text"] == "hi server")
        code, brows = http("POST", base + f"/api/chats/{cid}/browser/open",
                           {"url": "https://example.org"})
        check("chat server browser panel returns honest UNTESTED events",
              code == 200 and brows["status"] == "UNTESTED"
              and any(e["type"] == "browser.open_requested" for e in brows["events"])
              and any(e["type"] == "browser.open_failed" for e in brows["events"]))
        code, tools = http("GET", base + "/api/tools")
        check("chat server lists tools the agent knows",
              code == 200 and "calculator" in tools["tools"] and "imagine" in tools["tools"])
        check("chat server lists supabase + drive + custom tools",
              code == 200 and "supabase_save_memory" in tools.get("supabase", {})
              and "drive_list_tools" in tools.get("drive", {})
              and "text_counts" in tools.get("custom", {}))
        with urllib.request.urlopen(base + "/style.css", timeout=10) as resp:
            served_css = resp.read().decode("utf-8", "replace")
            served_code = resp.status
        check("chat server serves updated CSS (self-mod accent + focus rule)",
              served_code == 200 and "--accent: #14b8a6" in served_css
              and "focus-visible" in served_css)
        code, _ = http("DELETE", base + f"/api/chats/{cid}")
        check("chat server deletes chat", code == 200)
        code, _ = http("GET", base + f"/api/chats/{cid}")
        check("deleted chat is gone from server", code == 404)
    finally:
        chat_server.shutdown()

    print(f"ALL PASS (workdir: {tmp})")


if __name__ == "__main__":
    main()
