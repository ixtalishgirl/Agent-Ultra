"""Google Drive client — the agent's 15 GB tool memory, env-only.

Tools the agent builds get stored here and loaded on demand:
  upload_tool(local_path, name)  — store a built tool file
  list_tools()                    — list stored tool files
  download_tool(name, dest_dir)   — fetch a tool back when needed

Credentials come ONLY from environment variables, never from code
or files, and are never printed:
  DRIVE_REFRESH_TOKEN + DRIVE_CLIENT_ID + DRIVE_CLIENT_SECRET
      (OAuth refresh flow — the standard user-consent path), or
  DRIVE_SERVICE_ACCOUNT_JSON  (path to a service-account JSON file,
      whose path — never its content — is read from env), or
  DRIVE_ACCESS_TOKEN  (a short-lived token supplied via env only).

Service-account JWT signing needs RS256: it is implemented when the
`cryptography` package is available; otherwise this module returns
an honest error instead of pretending to authenticate.

This repo is PUBLIC. No token, secret, or key is ever written to a
file or printed by this module.

Without credentials every call returns {"configured": False, ...} —
never a fake upload, never a fake file list.

No prompt content lives in this module.
"""

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"


def _env(name):
    value = os.environ.get(name, "").strip()
    return value or None


class DriveClient:
    def __init__(self):
        self.refresh_token = _env("DRIVE_REFRESH_TOKEN")
        self.client_id = _env("DRIVE_CLIENT_ID")
        self.client_secret = _env("DRIVE_CLIENT_SECRET")
        self.service_account_path = _env("DRIVE_SERVICE_ACCOUNT_JSON")
        self.access_token = _env("DRIVE_ACCESS_TOKEN")
        self.folder_id = _env("DRIVE_TOOL_FOLDER_ID")  # optional
        self._token = None
        self._token_expires = 0
        self.configured = bool(
            (self.refresh_token and self.client_id and self.client_secret)
            or self.service_account_path
            or self.access_token
        )

    def status(self):
        if not self.configured:
            return {"configured": False,
                    "detail": "NOT CONFIGURED: set DRIVE_REFRESH_TOKEN + "
                              "DRIVE_CLIENT_ID + DRIVE_CLIENT_SECRET, or "
                              "DRIVE_SERVICE_ACCOUNT_JSON, or "
                              "DRIVE_ACCESS_TOKEN in env. No storage faked."}
        method = ("oauth-refresh" if self.refresh_token else
                  "service-account" if self.service_account_path else
                  "access-token")
        return {"configured": True, "method": method,
                "detail": "configured via env (no secret shown)"}

    # ------------------------------------------------------------ auth
    def _token_from_refresh(self):
        body = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }).encode("utf-8")
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def _token_from_service_account(self):
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:
            raise RuntimeError(
                "SERVICE-ACCOUNT-NEEDS-CRYPTO: the cryptography package "
                "is not installed, so RS256 signing is unavailable. "
                "Install cryptography, or use the OAuth refresh-token "
                "path instead."
            ) from exc
        with open(self.service_account_path, "r", encoding="utf-8") as f:
            sa = json.load(f)
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claim = {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/drive.file",
                 "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
        def b64(obj):
            raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        signing_input = f"{b64(header)}.{b64(claim)}".encode("ascii")
        key = serialization.load_pem_private_key(
            sa["private_key"].encode("utf-8"), password=None)
        sig = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        jwt = signing_input.decode("ascii") + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")
        body = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt,
        }).encode("utf-8")
        req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        self._token = data["access_token"]
        self._token_expires = time.time() + int(data.get("expires_in", 3600)) - 60
        return self._token

    def token(self):
        """Real access token, or raises with the honest reason."""
        if self.access_token:
            return self.access_token
        if self._token and time.time() < self._token_expires:
            return self._token
        if self.refresh_token:
            return self._token_from_refresh()
        if self.service_account_path:
            return self._token_from_service_account()
        raise RuntimeError("NOT CONFIGURED: no Drive credentials in env")

    # ------------------------------------------------------------ calls
    def _request(self, method, url, body=None, headers=None, raw=False):
        if not self.configured:
            return {"configured": False,
                    "error": "NOT CONFIGURED: no Drive credentials in env"}
        try:
            tok = self.token()
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Bearer {tok}")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
                if raw:
                    return {"ok": True, "status": resp.status, "data": data}
                text = data.decode("utf-8")
                return {"ok": True, "status": resp.status,
                        "data": json.loads(text) if text else None}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "status": exc.code,
                    "error": exc.read().decode("utf-8", "replace")[:500]}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def list_tools(self, page_size=100):
        """List stored tool files (the tool-memory folder when
        DRIVE_TOOL_FOLDER_ID is set, else Drive root)."""
        query = "trashed = false"
        if self.folder_id:
            query += f" and '{self.folder_id}' in parents"
        url = (f"{DRIVE_API}/files?q={urllib.parse.quote(query)}"
               f"&pageSize={page_size}&fields=files(id,name,mimeType,size,modifiedTime)")
        result = self._request("GET", url)
        if result.get("ok"):
            result["tools"] = result.pop("data", {}).get("files", [])
        return result

    def upload_tool(self, local_path, name=None):
        """Upload one built tool file. Real multipart upload."""
        from pathlib import Path
        path = Path(local_path)
        if not path.exists():
            return {"ok": False, "error": f"file not found: {path}"}
        meta = {"name": name or path.name}
        if self.folder_id:
            meta["parents"] = [self.folder_id]
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        boundary = "agent-ultra-boundary"
        body = (
            f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(meta)}\r\n"
            f"--{boundary}\r\nContent-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self._request(
            "POST", f"{UPLOAD_API}/files?uploadType=multipart",
            body=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"})

    def download_tool(self, name, dest_dir):
        """Find a stored tool by name and download its bytes."""
        from pathlib import Path
        found = self.list_tools()
        if not found.get("ok"):
            return found
        match = [f for f in found.get("tools", []) if f.get("name") == name]
        if not match:
            return {"ok": False, "error": f"no stored tool named {name!r}"}
        file_id = match[0]["id"]
        result = self._request("GET", f"{DRIVE_API}/files/{file_id}?alt=media", raw=True)
        if not result.get("ok"):
            return result
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / name
        out.write_bytes(result["data"])
        return {"ok": True, "path": str(out), "bytes": out.stat().st_size,
                "file_id": file_id}
