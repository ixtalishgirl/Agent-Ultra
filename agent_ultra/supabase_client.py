"""Supabase client — env-only, stdlib REST (no SDK needed).

Credentials come ONLY from environment variables, never from code
or files:
  SUPABASE_URL  e.g. https://xyzcompany.supabase.co
  SUPABASE_KEY  anon key (or service key for privileged writes)

This repo is PUBLIC, so a key committed here would be catastrophic.
No key is ever printed, logged, or written by this module — status()
reports only configured/not-configured and the URL host, never the
key itself.

What the agent can do through this module (all real PostgREST calls):
  select / insert / update / delete rows in any table,
  save_memory / recall_memories (a `memories` table the owner creates
  once — see the SQL note below),
  create_table_via_sql — HONEST LIMIT: PostgREST cannot run arbitrary
  DDL. This method tries the `exec_sql` RPC function (only works if
  the owner created that function in their project); otherwise it
  returns a plain error telling the owner to run the DDL in the
  Supabase SQL editor or via a direct Postgres connection. It never
  pretends a table was created.

Without SUPABASE_URL + SUPABASE_KEY every call returns
{"configured": False, ...} — never a fake save, never a fake row.

No prompt content lives in this module.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 20

# SQL the owner runs ONCE in the Supabase SQL editor to create the
# memories table (documented here so it is visible, not hidden):
MEMORIES_TABLE_SQL = """
create table if not exists memories (
  id bigint generated always as identity primary key,
  kind text not null default 'note',
  content text not null,
  meta jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
""".strip()


def config_from_env():
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if url and key:
        return url, key
    return None


class SupabaseClient:
    def __init__(self, url=None, key=None):
        cfg = (url, key) if (url and key) else config_from_env()
        self.configured = cfg is not None
        self.url, self.key = cfg if cfg else (None, None)

    def status(self):
        """Configured or not — never prints the key."""
        if not self.configured:
            return {"configured": False,
                    "detail": "NOT CONFIGURED: set SUPABASE_URL + "
                              "SUPABASE_KEY in the environment (Railway "
                              "variables). No save is faked."}
        host = urllib.parse.urlparse(self.url).netloc
        return {"configured": True, "host": host,
                "detail": "configured (key present in env, not shown)"}

    def _request(self, method, path, body=None, params=None):
        if not self.configured:
            return {"configured": False,
                    "error": "NOT CONFIGURED: SUPABASE_URL/SUPABASE_KEY missing"}
        url = f"{self.url}/rest/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("apikey", self.key)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Prefer", "return=representation")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8")
                return {"ok": True, "status": resp.status,
                        "data": json.loads(raw) if raw else None}
        except urllib.error.HTTPError as exc:
            return {"ok": False, "status": exc.code,
                    "error": exc.read().decode("utf-8", "replace")[:500]}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    def select(self, table, columns="*", filters=None, limit=50, order=None):
        params = {"select": columns, "limit": str(limit)}
        if order:
            params["order"] = order
        for key, value in (filters or {}).items():
            params[key] = f"eq.{value}"
        return self._request("GET", f"/{table}", params=params)

    def insert(self, table, rows):
        if isinstance(rows, dict):
            rows = [rows]
        return self._request("POST", f"/{table}", body=rows)

    def update(self, table, values, filters):
        params = {}
        for key, value in filters.items():
            params[key] = f"eq.{value}"
        return self._request("PATCH", f"/{table}", body=values, params=params)

    def delete(self, table, filters):
        params = {}
        for key, value in filters.items():
            params[key] = f"eq.{value}"
        return self._request("DELETE", f"/{table}", params=params)

    def rpc(self, fn, params=None):
        return self._request("POST", f"/rpc/{fn}", body=params or {})

    def create_table_via_sql(self, sql):
        """HONEST LIMIT: PostgREST has no DDL endpoint. Only works if
        the project defines an `exec_sql` RPC function; otherwise this
        returns an error with the manual path. Never claims creation."""
        result = self.rpc("exec_sql", {"sql": sql})
        if result.get("ok"):
            return result
        return {"ok": False,
                "error": "DDL is not available through PostgREST. "
                         "Run the SQL in the Supabase SQL editor (or a "
                         "direct Postgres connection) — no table was "
                         "created by this call.",
                "rpc_error": result.get("error", "")[:300]}

    # ------------------------------------------------------- memories
    def save_memory(self, content, kind="note", meta=None):
        """Save one memory/conversation row. Real insert or real error."""
        if not isinstance(content, str) or not content:
            return {"ok": False, "error": "content must be a non-empty string"}
        return self.insert("memories", {
            "kind": kind, "content": content, "meta": meta or {}})

    def recall_memories(self, query=None, kind=None, limit=20):
        """Recall memories: latest first, or filtered by content text
        (ilike) and/or kind. Real rows or a real PostgREST error."""
        params = {"select": "*", "limit": str(limit),
                  "order": "created_at.desc"}
        if query:
            params["content"] = f"ilike.*{query}*"
        if kind:
            params["kind"] = f"eq.{kind}"
        return self._request("GET", "/memories", params=params)
