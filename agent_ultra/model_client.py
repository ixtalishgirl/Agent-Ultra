"""Model client — talks to the model ONLY through a tunnel URL.

  MODEL_API_URL  e.g. https://xxxx.ngrok-free.app  (ngrok tunnel to
                 the owner's VPS, where llama.cpp serves the model)

No model is bundled in the container and no model load is ever faked.
The 14B Q8_0 GGUF (15.7 GB) cannot run inside a small Railway
container (RAM) — that is why the model serves on the owner's VPS
and the Railway app reaches it through the ngrok tunnel (see
TUNNEL.md). Kaggle's sandbox is NOT in this route, by design.

health() hits {MODEL_API_URL}/health (llama.cpp's health endpoint)
and reports live/dead honestly, with measured ms.
chat() posts OpenAI-compatible /v1/chat/completions to the tunnel
URL (llama.cpp serves that shape). Messages come from the CALLER —
this module contains no prompt content of its own.

Without MODEL_API_URL every call returns {"configured": False, ...}.
"""

import json
import os
import time
import urllib.error
import urllib.request

TIMEOUT = 30


def model_api_url():
    return os.environ.get("MODEL_API_URL", "").strip().rstrip("/") or None


class ModelClient:
    def __init__(self, base_url=None):
        self.base_url = base_url or model_api_url()
        self.configured = self.base_url is not None

    def status(self):
        if not self.configured:
            return {"configured": False,
                    "detail": "NOT CONFIGURED: set MODEL_API_URL to the "
                              "ngrok tunnel URL of the VPS llama.cpp "
                              "server. No model reply is faked."}
        return {"configured": True,
                "detail": "configured (tunnel URL from env, not shown in full)"}

    def health(self):
        """Real health check against the tunnel URL. Live or dead,
        measured, never assumed."""
        if not self.configured:
            return {"configured": False, "live": False,
                    "error": "NOT CONFIGURED: MODEL_API_URL missing"}
        t0 = time.perf_counter()
        url = f"{self.base_url}/health"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace")[:300]
            return {"configured": True, "live": True, "status": resp.status,
                    "body": body,
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
        except urllib.error.HTTPError as exc:
            return {"configured": True, "live": False, "status": exc.code,
                    "error": exc.read().decode("utf-8", "replace")[:300],
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as exc:
            return {"configured": True, "live": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}

    def chat(self, messages, max_tokens=512, temperature=0.7):
        """Real chat completion through the tunnel. Messages are the
        caller's; this module adds no prompt of its own."""
        if not self.configured:
            return {"configured": False,
                    "error": "NOT CONFIGURED: MODEL_API_URL missing"}
        if not isinstance(messages, list) or not messages:
            return {"ok": False, "error": "messages must be a non-empty list"}
        payload = json.dumps({
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }).encode("utf-8")
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                f"{self.base_url}/v1/chat/completions",
                data=payload, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            return {"ok": True,
                    "reply": message.get("content", ""),
                    "usage": data.get("usage"),
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "status": exc.code,
                    "error": exc.read().decode("utf-8", "replace")[:500],
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
