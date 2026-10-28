"""Model-driven reply loop for the in-chat browser.

The model decides on its own when to open the browser: the loop sends
the model ONE tool (browser_open, name + parameter schema ONLY — no
description sentences, per the owner's no-prompt rule) alongside the
chat's messages. When the model returns a tool call for browser_open,
the loop runs the open through the REAL browser path — a
BrowserProfile directory plus browser_tools.BrowserSession (real
Playwright actions, measured ms) — and records the real events in the
chat's browser event log. The user never has to type a URL for the
model to open the browser.

The loop appends exactly one stored agent message per user message:
- the model's text reply, when it gives one;
- an honest "model not live yet" message when MODEL_API_URL is unset;
- an honest failure message when the model call itself fails;
- an honest "no text reply" message when the model acts (e.g. opens
  the browser) but returns no text (the browser events stay visible
  in the panel).

Tool-protocol messages (tool calls / tool results) are kept in memory
for the loop only and are NEVER stored as chat messages.

Self-made tools, live in the loop: alongside browser_open the model
also gets ONE more tool, tool_create (name + parameter schema ONLY —
no description sentences). When the model calls it, the loop runs
the REAL tool_pipeline (5 stages: intake, validated_call, execute,
evidence, report). A tool whose tests fail is NOT registered — its
file is removed by the pipeline and the failure report is fed back.
When creation succeeds, the new tool is added to the tools offered
in later rounds of the SAME turn, so the model can then USE the tool
it just made; its calls dispatch through tool_pipeline.dispatch_custom
(validated at call time). Tool definitions sent to the model carry
names + parameter names/types only, never prose from this module.

Memory context: run_model_reply accepts an optional `context` list
of verbatim stored-memory strings (see memory_loop.py). They are
appended after the chat's messages, unchanged. When context is None
(the default) the model's messages are exactly the chat's messages.

Live screen: a successful model browser open keeps its BrowserSession
in BROWSER_SESSIONS (one per chat). browser_screenshot() returns the
live Playwright screenshot bytes for the chat's session, or raises
LookupError when no live session exists — never a placeholder image.

UNTESTED until the model is live: a real model reply, a real model
tool call, a real live Chromium open on Render, and a real screenshot
stream. On this host Playwright/Chromium are absent, so a model
browser open here records an honest open_failed event.
"""

import json

from .browser_profile import BrowserProfile
from .browser_tools import BrowserSession
from .model_client import ModelClient
from . import tool_pipeline

# Tool definition sent to the model: name + parameter schema ONLY.
# No description sentences anywhere (owner rule: no prompt content).
MODEL_BROWSER_TOOL = {
    "type": "function",
    "function": {
        "name": "browser_open",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
}

# Second tool offered to the model: create a pure-computation tool
# through the real pipeline. Name + parameter schema ONLY — no
# description sentences anywhere. "description" below is a parameter
# NAME whose value the model supplies; this module writes no prose.
MODEL_TOOL_CREATE = {
    "type": "function",
    "function": {
        "name": "tool_create",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "source": {"type": "string"},
                "arg_names": {"type": "array",
                              "items": {"type": "string"}},
                "tests": {"type": "array",
                          "items": {"type": "object"}},
            },
            "required": ["name", "description", "source", "arg_names",
                         "tests"],
        },
    },
}


def _custom_tool_entry(name, arg_names):
    """Tool definition for a just-created custom tool: name +
    parameter names only (no types invented, no prose)."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {a: {} for a in arg_names},
                "required": list(arg_names),
            },
        },
    }

MODEL_NOT_LIVE_TEXT = (
    "Model is not live yet — no agent reply is available, so none is "
    "faked here. (MODEL_API_URL is not configured.)"
)

MAX_TOOL_ROUNDS = 3

# chat_id -> live BrowserSession. One session per chat, kept only
# while its browser is actually open.
BROWSER_SESSIONS = {}


def _to_model_messages(stored):
    """Map stored chat messages to model messages. The user's text is
    passed through unchanged; stored agent messages become assistant
    messages. No prompt content is added."""
    out = []
    for m in stored:
        role = "assistant" if m.get("role") == "agent" else "user"
        out.append({"role": role, "content": m.get("text", "")})
    return out


def _record(store, chat_id, event):
    return store.append_browser_event(chat_id, event)


def model_browser_open(store, chat_id, url):
    """Run one model-decided browser open through the real browser
    path and record the real events. Returns the event list.

    Reuses BrowserProfile (real profile dir) + BrowserSession (real
    Playwright goto action, measured ms). On any failure the session
    is NOT registered and the failure event carries the real error.
    """
    events = [{
        "type": "browser.open_requested",
        "chat_id": chat_id,
        "url": url,
        "panel": "in-chat",
        "status": "requested",
        "source": "model",
    }]
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        events.append({
            "type": "browser.open_failed",
            "chat_id": chat_id,
            "url": url,
            "status": "error",
            "detail": "url must start with http:// or https://",
            "source": "model",
        })
        for ev in events:
            _record(store, chat_id, ev)
        return events

    profile = BrowserProfile(chat_id, store.chat_dir(chat_id))
    session = BROWSER_SESSIONS.get(chat_id)
    try:
        if session is None:
            session = BrowserSession(profile.path)
        result = session.act("goto", url=url)
        if not result.get("ok"):
            raise RuntimeError(
                (result.get("detail") or {}).get("error", "browser action failed")
            )
        BROWSER_SESSIONS[chat_id] = session
        events.append({
            "type": "browser.opened",
            "chat_id": chat_id,
            "url": result["detail"].get("url", url),
            "title": result["detail"].get("title", ""),
            "ms": result["ms"],
            "profile": str(profile.path),
            "status": "ok",
            "source": "model",
        })
    except Exception as exc:
        if session is not None and BROWSER_SESSIONS.get(chat_id) is not session:
            try:
                session.close()
            except Exception:
                pass
        elif session is not None:
            # A previously registered session died mid-action.
            try:
                session.close()
            except Exception:
                pass
            BROWSER_SESSIONS.pop(chat_id, None)
        events.append({
            "type": "browser.open_failed",
            "chat_id": chat_id,
            "url": url,
            "status": "error",
            "detail": f"{type(exc).__name__}: {exc}",
            "source": "model",
        })
    for ev in events:
        _record(store, chat_id, ev)
    return events


def browser_screenshot(chat_id):
    """Live screenshot bytes for a chat's browser session.

    Raises LookupError when no live session exists (never a
    placeholder image) and KeyError is left to the caller for an
    unknown chat.
    """
    session = BROWSER_SESSIONS.get(chat_id)
    if session is None:
        raise LookupError("no live browser session for this chat")
    try:
        return session.page().screenshot()
    except Exception:
        BROWSER_SESSIONS.pop(chat_id, None)
        raise LookupError("no live browser session for this chat")


def close_browser_session(chat_id):
    """Best-effort close + forget of a chat's browser session."""
    session = BROWSER_SESSIONS.pop(chat_id, None)
    if session is not None:
        try:
            session.close()
        except Exception:
            pass


def _run_tool_create(args):
    """Run one model-requested tool creation through the real
    pipeline. Returns the pipeline report (ok False + error when the
    arguments are malformed or the tool's tests fail — a failed tool
    is never registered). On success the report also carries the
    tool's arg_names so the loop can offer it in later rounds."""
    if not isinstance(args, dict):
        return {"ok": False, "error": "tool_create arguments must be an object"}
    name = args.get("name")
    description = args.get("description")
    source = args.get("source")
    arg_names = args.get("arg_names")
    tests = args.get("tests")
    if not isinstance(name, str) or not isinstance(description, str):
        return {"ok": False, "error": "tool_create needs string name + description"}
    if not isinstance(source, str) or not isinstance(arg_names, list):
        return {"ok": False, "error": "tool_create needs string source + arg_names list"}
    if not isinstance(tests, list):
        return {"ok": False, "error": "tool_create needs a tests list"}
    report = tool_pipeline.tool_create(name, description, source,
                                       arg_names, tests)
    if report.get("ok"):
        report["arg_names"] = list(arg_names)
    return report


def run_model_reply(store, chat_id, client=None, context=None):
    """One model reply turn for a chat. Call after appending the
    user's message. Appends exactly one stored agent message and
    returns a result dict describing what happened.

    client defaults to ModelClient() (reads MODEL_API_URL from env at
    call time). Tests pass a fake client; the browser path is
    patchable via model_loop.BrowserSession. `context`, when given,
    is a list of verbatim stored-memory strings appended after the
    chat's messages (see memory_loop.py); None means the model's
    messages are exactly the chat's messages.
    """
    if client is None:
        client = ModelClient()
    if not getattr(client, "configured", False):
        text = MODEL_NOT_LIVE_TEXT
        store.append_message(chat_id, "agent", text)
        return {"live": False, "reply": text}

    messages = _to_model_messages(store.get(chat_id)["messages"])
    for row in context or []:
        if isinstance(row, str) and row:
            messages.append({"role": "user", "content": row})
    tools = [MODEL_BROWSER_TOOL, MODEL_TOOL_CREATE]
    custom_tools = {}  # name -> arg_names, for tools made this turn
    tool_calls_seen = 0
    for _round in range(MAX_TOOL_ROUNDS + 1):
        result = client.chat(messages, tools=tools)
        if not result.get("ok"):
            text = f"Model call failed: {result.get('error', 'unknown error')}"
            store.append_message(chat_id, "agent", text)
            return {"live": True, "ok": False, "reply": text,
                    "error": result.get("error")}
        reply = result.get("reply") or ""
        tool_calls = result.get("tool_calls") or []
        if not tool_calls:
            if reply:
                store.append_message(chat_id, "agent", reply)
                return {"live": True, "ok": True, "reply": reply,
                        "tool_calls": tool_calls_seen}
            text = ("Model returned no text reply. (Any browser action "
                    "it took is shown in the browser panel.)")
            store.append_message(chat_id, "agent", text)
            return {"live": True, "ok": True, "reply": text,
                    "tool_calls": tool_calls_seen}
        # Model chose tool(s): execute them, feed the real results
        # back so the model can continue.
        messages.append({"role": "assistant", "content": reply,
                         "tool_calls": tool_calls})
        for call in tool_calls:
            tool_calls_seen += 1
            fn = (call or {}).get("function") or {}
            name = fn.get("name")
            call_id = call.get("id") or f"call_{tool_calls_seen}"
            if name == "browser_open":
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                events = model_browser_open(store, chat_id, args.get("url"))
                content = json.dumps({"events": events})
            elif name == "tool_create":
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                report = _run_tool_create(args)
                content = json.dumps(report)
                if report.get("ok") and report.get("tool") not in custom_tools:
                    custom_tools[report["tool"]] = report.get(
                        "arg_names") or []
                    tools = tools + [_custom_tool_entry(
                        report["tool"], custom_tools[report["tool"]])]
            elif name in custom_tools:
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                content = json.dumps(
                    tool_pipeline.dispatch_custom(name, args))
            else:
                content = json.dumps(
                    {"error": f"unknown tool: {name!r}; not executed"})
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": content})
    text = ("Model kept calling tools without a text reply. (Its "
            "browser actions are shown in the browser panel.)")
    store.append_message(chat_id, "agent", text)
    return {"live": True, "ok": True, "reply": text,
            "tool_calls": tool_calls_seen}
