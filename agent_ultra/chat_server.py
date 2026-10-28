"""Chat UI server (stdlib only).

Serves the professional chat UI (agent_ultra/ui/) plus a JSON API:

  GET  /health
  GET  /api/chats                 list chats (sidebar)
  POST /api/chats                 create a chat  {"title": ...}
  GET  /api/chats/<id>            one chat + its messages
  POST /api/chats/<id>/messages   append {"role": "user"|"agent", "text": ...}
  DELETE /api/chats/<id>          delete THAT chat only (scoped, see
                                  chat_store.py — never outside the
                                  agent-ultra workdirs)
  GET  /api/chats/<id>/browser/events   browser panel event log
  GET  /api/chats/<id>/browser/screenshot  live Playwright screenshot
                                  bytes for the chat's model-opened
                                  browser session; honest error when
                                  no live session exists (never a
                                  placeholder image)
  POST /api/chats/<id>/browser/open     {"url": ...} → AG-UI-shaped
                                  browser events. Live Chromium launch
                                  is UNTESTED on this host, so the
                                  panel shows the honest refusal
                                  event, never a fake screenshot.
  GET  /api/tools                 the extra tools the agent knows

Model reply loop (see model_loop.py): when a USER message arrives,
the server runs the model loop — real model reply when MODEL_API_URL
is configured, honest "model not live yet" agent message otherwise,
never a fake reply. The model itself may open the browser via a
browser_open tool call; the live screen then shows in the panel via
the screenshot endpoint above.

Run:  python3 -m agent_ultra.chat_server --port 8000
Then open http://127.0.0.1:8000/ in a browser.

No prompt content is accepted, stored, or emitted by this server.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .browser_profile import BrowserProfile
from .chat_store import ChatStore
from . import model_loop
from . import tools_extra

UI_DIR = Path(__file__).resolve().parent / "ui"
DEFAULT_CHATS = Path(__file__).resolve().parent.parent / "chats"


def browser_open_events(store, chat_id, url):
    """AG-UI-shaped browser events for one open request, inside the
    chat view. The live launch is UNTESTED here, so the second event
    records the honest refusal from BrowserProfile.launch()."""
    events = [{
        "type": "browser.open_requested",
        "chat_id": chat_id,
        "url": url,
        "panel": "in-chat",
        "status": "requested",
    }]
    profile = BrowserProfile(chat_id, store.chat_dir(chat_id))
    try:
        profile.launch()
        events.append({
            "type": "browser.opened",
            "chat_id": chat_id,
            "url": url,
            "profile": str(profile.path),
            "status": "ok",
        })
    except NotImplementedError as exc:
        events.append({
            "type": "browser.open_failed",
            "chat_id": chat_id,
            "url": url,
            "profile": str(profile.path),
            "status": "UNTESTED",
            "detail": str(exc),
            "note": "Live Chromium is UNTESTED on this host (no binary). "
                    "The panel shows this event instead of a fake screen.",
        })
    for ev in events:
        store.append_browser_event(chat_id, ev)
    return events


def make_handler(store):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path, ctype):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_bytes(self, data, ctype):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                return json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return None

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                self._send_file(UI_DIR / "index.html", "text/html; charset=utf-8")
            elif path == "/style.css":
                self._send_file(UI_DIR / "style.css", "text/css; charset=utf-8")
            elif path == "/app.js":
                self._send_file(UI_DIR / "app.js", "text/javascript; charset=utf-8")
            elif path == "/health":
                self._send_json(200, {"status": "ok", "service": "agent-ultra-chat"})
            elif path == "/api/tools":
                from . import dispatcher_bridge as _bridge
                self._send_json(200, {
                    "tools": tools_extra.list_extra_tools(),
                    "supabase": _bridge.list_supabase_tools(),
                    "drive": _bridge.list_drive_tools(),
                    "custom": _bridge.list_custom_tools(),
                })
            elif path == "/api/chats":
                self._send_json(200, {"chats": store.list_chats()})
            elif path.startswith("/api/chats/"):
                parts = [p for p in path.split("/") if p]
                # /api/chats/<id> or /api/chats/<id>/browser/events
                if len(parts) == 3:
                    try:
                        self._send_json(200, store.get(parts[2]))
                    except KeyError:
                        self._send_json(404, {"status": "error", "detail": "unknown chat"})
                    except ValueError as exc:
                        self._send_json(400, {"status": "error", "detail": str(exc)})
                elif len(parts) == 5 and parts[3] == "browser" and parts[4] == "events":
                    try:
                        self._send_json(200, {"events": store.browser_events(parts[2])})
                    except (KeyError, ValueError) as exc:
                        self._send_json(404, {"status": "error", "detail": str(exc)})
                elif len(parts) == 5 and parts[3] == "browser" and parts[4] == "screenshot":
                    # Live screen, or an honest error: never a placeholder.
                    if not store.exists(parts[2]):
                        self._send_json(404, {"status": "error", "detail": "unknown chat"})
                    else:
                        try:
                            png = model_loop.browser_screenshot(parts[2])
                        except LookupError as exc:
                            self._send_json(404, {"status": "error", "detail": str(exc)})
                        else:
                            self._send_bytes(png, "image/png")
                else:
                    self._send_json(404, {"status": "error", "detail": "unknown path"})
            else:
                self._send_json(404, {"status": "error", "detail": "unknown path"})

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            body = self._read_json()
            if body is None:
                self._send_json(400, {"status": "error", "detail": "invalid JSON"})
                return
            if path == "/api/chats":
                meta = store.create(title=body.get("title"))
                self._send_json(201, meta)
                return
            parts = [p for p in path.split("/") if p]
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "chats" and parts[3] == "messages":
                try:
                    msg = store.append_message(parts[2], body.get("role"), body.get("text"))
                except KeyError:
                    self._send_json(404, {"status": "error", "detail": "unknown chat"})
                except ValueError as exc:
                    self._send_json(400, {"status": "error", "detail": str(exc)})
                else:
                    # Model reply loop, user messages only: the model
                    # answers (or opens the browser on its own) when
                    # MODEL_API_URL is configured; otherwise the loop
                    # appends the honest not-live message, never a fake.
                    reply = None
                    if body.get("role") == "user":
                        reply = model_loop.run_model_reply(store, parts[2])
                    out = dict(msg)
                    if reply is not None:
                        out["model_reply"] = reply
                    self._send_json(201, out)
                return
            if len(parts) == 5 and parts[0] == "api" and parts[1] == "chats" and parts[3] == "browser" and parts[4] == "open":
                url = body.get("url")
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    self._send_json(400, {"status": "error", "detail": "url must start with http:// or https://"})
                    return
                try:
                    events = browser_open_events(store, parts[2], url)
                except KeyError:
                    self._send_json(404, {"status": "error", "detail": "unknown chat"})
                    return
                except ValueError as exc:
                    self._send_json(400, {"status": "error", "detail": str(exc)})
                    return
                last = events[-1]
                self._send_json(200, {
                    "status": last["status"],
                    "events": events,
                    "note": last.get("note", ""),
                })
                return
            self._send_json(404, {"status": "error", "detail": "unknown path"})

        def do_DELETE(self):  # noqa: N802
            parts = [p for p in self.path.split("/") if p]
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "chats":
                try:
                    result = store.delete(parts[2])
                    self._send_json(200, {"status": "deleted", **result})
                except KeyError:
                    self._send_json(404, {"status": "error", "detail": "unknown chat"})
                except ValueError as exc:
                    self._send_json(400, {"status": "error", "detail": str(exc)})
                else:
                    # Best-effort: a deleted chat must not leave a live
                    # browser session behind.
                    model_loop.close_browser_session(parts[2])
                return
            self._send_json(404, {"status": "error", "detail": "unknown path"})

        def log_message(self, *args):  # keep test output clean
            pass

    return Handler


def serve(port=0, base_dir=None, copies_base=None, host="127.0.0.1"):
    store = ChatStore(base_dir or DEFAULT_CHATS, copies_base=copies_base)
    server = ThreadingHTTPServer((host, port), make_handler(store))
    server.chat_store = store
    return server


def main():
    parser = argparse.ArgumentParser(description="Agent-Ultra chat UI server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind host (0.0.0.0 inside a container)")
    parser.add_argument("--base", default=None, help="chat store dir")
    args = parser.parse_args()
    server = serve(args.port, base_dir=args.base, host=args.host)
    print(f"Agent-Ultra chat UI on http://{args.host}:{server.server_address[1]}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
