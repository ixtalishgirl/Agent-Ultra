"""Test for the model-driven in-chat browser loop. Run from
~/workspace/agent-ultra:

    python3 tests/test_model_browser_loop.py

Proves WITHOUT a live model or a live browser:
  (a) a user message with no MODEL_API_URL yields the honest
      not-live agent message (never a fake reply);
  (b) a model tool call for browser_open reaches the browser path
      (mocked BrowserSession launch, asserting the call path — the
      exact URL the model chose — plus the event recorded in the
      chat's browser event log) and the loop then stores the model's
      follow-up text reply;
  (c) the screenshot endpoint returns an honest error with no
      session, and real PNG bytes when a session is registered.

Prints PASS lines; exits non-zero on any failure.
"""

import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_ultra import model_loop  # noqa: E402
from agent_ultra.chat_server import serve as chat_serve  # noqa: E402
from agent_ultra.chat_store import ChatStore  # noqa: E402


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
            return resp.status, resp.headers.get("Content-Type"), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type"), exc.read()


def http_json(method, url, body=None):
    code, _, raw = http(method, url, body)
    try:
        return code, json.loads(raw or b"{}")
    except json.JSONDecodeError:
        return code, {}


class FakeClient:
    """Stands in for a live model: first call chooses browser_open,
    second call answers with text. Records what it was sent."""

    def __init__(self):
        self.configured = True
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        if len(self.calls) == 1:
            return {"ok": True, "reply": "", "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "browser_open",
                             "arguments": json.dumps(
                                 {"url": "https://example.org"})},
            }]}
        return {"ok": True, "reply": "opened it, here is what I found",
                "tool_calls": []}


class FakePage:
    def __init__(self, session):
        self.session = session

    def screenshot(self):
        return b"\x89PNG\r\n\x1a\nFAKE-SCREENSHOT-BYTES"


class FakeSession:
    """Stands in for BrowserSession: records goto, never launches."""

    instances = []

    def __init__(self, profile_dir):
        self.profile_dir = str(profile_dir)
        self.goto_urls = []
        self.closed = False
        FakeSession.instances.append(self)

    def act(self, action, **kw):
        if action == "goto":
            self.goto_urls.append(kw.get("url"))
            return {"ok": True, "action": "goto", "ms": 1.2,
                    "detail": {"url": kw.get("url"), "title": "Example"}}
        return {"ok": False, "action": action, "ms": 0.0,
                "detail": {"error": "unsupported in fake"}}

    def page(self):
        return FakePage(self)

    def close(self):
        self.closed = True


def main():
    tmp = Path(tempfile.mkdtemp(prefix="agent-ultra-model-loop-"))
    saved_env = os.environ.pop("MODEL_API_URL", None)
    real_session_cls = model_loop.BrowserSession
    try:
        # ---- (a) no MODEL_API_URL: honest not-live message ----------
        server = chat_serve(0, base_dir=tmp / "srv-chats")
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            code, created = http_json("POST", base + "/api/chats", {"title": "loop chat"})
            check("(a) chat created", code == 201 and "chat_id" in created)
            cid = created["chat_id"]
            code, posted = http_json(
                "POST", base + f"/api/chats/{cid}/messages",
                {"role": "user", "text": "hello model"})
            check("(a) user message accepted", code == 201)
            check("(a) model_reply reports not live",
                  posted.get("model_reply", {}).get("live") is False)
            code, got = http_json("GET", base + f"/api/chats/{cid}")
            msgs = got["messages"]
            check("(a) user message stored unchanged",
                  len(msgs) >= 1 and msgs[0]["text"] == "hello model")
            check("(a) honest not-live agent message appended",
                  len(msgs) >= 2 and msgs[1]["role"] == "agent"
                  and "not live" in msgs[1]["text"].lower()
                  and "MODEL_API_URL" in msgs[1]["text"])
            # ---- (c) screenshot endpoint, no session -----------------
            code, ctype, raw = http(
                "GET", base + f"/api/chats/{cid}/browser/screenshot")
            check("(c) screenshot with no session is an honest error",
                  code == 404 and b"no live browser session" in raw)
            # ---- (c) screenshot with a registered session ------------
            model_loop.BROWSER_SESSIONS[cid] = FakeSession(tmp / "fake-profile")
            code, ctype, raw = http(
                "GET", base + f"/api/chats/{cid}/browser/screenshot")
            check("(c) screenshot with session returns PNG bytes",
                  code == 200 and ctype == "image/png"
                  and raw.startswith(b"\x89PNG"))
            model_loop.BROWSER_SESSIONS.pop(cid, None)
            code, _ = http_json("DELETE", base + f"/api/chats/{cid}")
            check("(a/c) chat deleted", code == 200)
        finally:
            server.shutdown()

        # ---- (b) model tool call reaches the browser path ------------
        model_loop.BrowserSession = FakeSession
        FakeSession.instances.clear()
        store = ChatStore(tmp / "loop-chats")
        chat = store.create(title="tool chat")
        chat_id = chat["chat_id"]
        store.append_message(chat_id, "user", "open example for me")
        fake = FakeClient()
        result = model_loop.run_model_reply(store, chat_id, client=fake)
        check("(b) loop reports ok with one tool call",
              result.get("ok") is True and result.get("tool_calls") == 1)
        check("(b) tool definition carries no description sentences",
              "description" not in json.dumps(model_loop.MODEL_BROWSER_TOOL)
              and model_loop.MODEL_BROWSER_TOOL["function"]["name"] == "browser_open")
        check("(b) user message passed to model unchanged",
              fake.calls[0]["messages"][0] == {"role": "user",
                                               "content": "open example for me"})
        check("(b) browser path received the model's exact URL",
              len(FakeSession.instances) == 1
              and FakeSession.instances[0].goto_urls == ["https://example.org"])
        events = store.browser_events(chat_id)
        check("(b) browser.opened event recorded in chat log",
              any(e["type"] == "browser.opened"
                  and e["url"] == "https://example.org"
                  and e.get("source") == "model" for e in events),
              f"events={events}")
        msgs = store.get(chat_id)["messages"]
        check("(b) model follow-up text stored as agent message",
              msgs[-1]["role"] == "agent"
              and msgs[-1]["text"] == "opened it, here is what I found")
        # Tool result fed back: second call saw the tool result.
        second = fake.calls[1]["messages"]
        check("(b) tool result fed back to model",
              any(m.get("role") == "tool"
                  and "browser.opened" in m.get("content", "")
                  for m in second))
        model_loop.close_browser_session(chat_id)
        check("(b) session closed on chat cleanup",
              FakeSession.instances[0].closed is True)
    finally:
        model_loop.BrowserSession = real_session_cls
        model_loop.BROWSER_SESSIONS.clear()
        if saved_env is not None:
            os.environ["MODEL_API_URL"] = saved_env

    print(f"ALL PASS (workdir: {tmp})")


if __name__ == "__main__":
    main()
