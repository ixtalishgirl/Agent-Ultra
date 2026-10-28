"""AG-UI endpoint skeleton (stdlib only).

Shape only, NOT protocol-complete: OpenBot treats any AG-UI endpoint
as a Bot, but the AG-UI event stream has never been validated against
a real OpenBot/CopilotKit server from this skeleton. /health proves
the server runs; /agui accepts a run request and answers honestly
that the event stream is UNTESTED, instead of faking agent output.

No prompt content is accepted, stored, or emitted by this server.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {
                "status": "ok",
                "service": "agent-ultra-agui-skeleton",
                "agui_protocol": "UNTESTED",
            })
        else:
            self._send(404, {"status": "error", "detail": "unknown path"})

    def do_POST(self):  # noqa: N802
        if self.path != "/agui":
            self._send(404, {"status": "error", "detail": "unknown path"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"status": "error", "detail": "invalid JSON"})
            return
        self._send(200, {
            "status": "accepted",
            "run_id": req.get("run_id"),
            "events": "UNTESTED",
            "note": (
                "Endpoint shape only. No AG-UI event stream is produced "
                "yet; validate against a real OpenBot server before "
                "claiming compatibility. No agent output is faked here."
            ),
        })

    def log_message(self, *args):  # keep test output clean
        pass


def serve(port=0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server
