"""Bridge to the Agent OS dispatcher (~/workspace/agent-os).

REAL: imports the existing dispatcher and exposes its public API.
Verified on this host: dispatcher loads 761 tools. A copy uses this
bridge to call tools through the same 5-stage pipeline + validation
the Agent OS already enforces. Tool tiers still apply: 541 implemented
+ 220 external_attempt (a real missing-dependency error, never a fake
success). This bridge adds no tools, no rules, no prompts.
"""

import sys
from pathlib import Path

AGENT_OS = Path(__file__).resolve().parent.parent.parent / "agent-os"
CORE = AGENT_OS / "core"


def _load():
    if not (CORE / "dispatcher.py").exists():
        raise FileNotFoundError(f"Agent OS dispatcher not found at {CORE}")
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    import dispatcher  # noqa: E402

    dispatcher.load()
    return dispatcher


_dispatcher = _load()


def tool_count():
    return len(_dispatcher.list_tools())


def list_tools(category=None):
    return _dispatcher.list_tools(category)


def get_schema(tool_name):
    return _dispatcher.get_schema(tool_name)


def dispatch(tool_name, args):
    """Dispatch one tool call. Returns the dispatcher's result dict."""
    return _dispatcher.dispatch(tool_name, args)


def list_extra_tools():
    """The extra tools the agent knows (calculator, weather, internet,
    imagine, understand). Lazy import: tools_extra is stdlib-only and
    never imports this bridge, so no cycle."""
    from . import tools_extra

    return tools_extra.list_extra_tools()


def dispatch_extra(tool_name, args=None):
    """Dispatch one extra tool call. Returns its result dict."""
    from . import tools_extra

    return tools_extra.dispatch_tool(tool_name, args)


def list_browser_tools():
    """The browser tools copies know (Playwright action set). Lazy
    import: browser_tools imports Playwright only inside start(), so
    no cycle and no crash on hosts without Playwright."""
    from . import browser_tools

    return browser_tools.list_browser_tools()


def dispatch_browser_action(session, tool_name, args=None):
    """Dispatch one browser tool on an open BrowserSession. Returns
    the timed real result dict (ok/fail + measured ms)."""
    from . import browser_tools

    return browser_tools.dispatch_browser_action(session, tool_name, args)


# ------------------------------------------------------- Supabase + Drive
# Both integrations are env-only (see supabase_client.py and
# drive_client.py). On a host without their env vars every dispatch
# returns the client's honest NOT CONFIGURED result — never a fake
# row, save, upload, or file list. The wiring itself (list + dispatch)
# is real and provable without any credentials.

SUPABASE_TOOLS = {
    "supabase_status": {"args": [],
                        "description": "Supabase configured or NOT CONFIGURED (key never shown)."},
    "supabase_select": {"args": ["table", "columns", "filters", "limit", "order"],
                        "description": "Select rows from a Supabase table (real PostgREST call)."},
    "supabase_insert": {"args": ["table", "rows"],
                        "description": "Insert rows into a Supabase table."},
    "supabase_update": {"args": ["table", "values", "filters"],
                        "description": "Update rows in a Supabase table."},
    "supabase_delete": {"args": ["table", "filters"],
                        "description": "Delete rows from a Supabase table."},
    "supabase_save_memory": {"args": ["content", "kind", "meta"],
                             "description": "Save one memory/conversation row."},
    "supabase_recall_memories": {"args": ["query", "kind", "limit"],
                                 "description": "Recall memory rows, latest first."},
    "supabase_create_table": {"args": ["sql"],
                              "description": "Create a table via the exec_sql RPC if the project defines it; otherwise an honest error (PostgREST has no DDL)."},
    "supabase_rpc": {"args": ["fn", "params"],
                     "description": "Call a Supabase RPC function."},
}

DRIVE_TOOLS = {
    "drive_status": {"args": [],
                     "description": "Drive configured or NOT CONFIGURED (no secret shown)."},
    "drive_list_tools": {"args": ["page_size"],
                         "description": "List stored tool files (the agent's tool memory)."},
    "drive_upload_tool": {"args": ["local_path", "name"],
                          "description": "Upload one built tool file to Drive."},
    "drive_download_tool": {"args": ["name", "dest_dir"],
                           "description": "Download a stored tool file by name."},
}


def supabase_status():
    from . import supabase_client

    return supabase_client.SupabaseClient().status()


def list_supabase_tools():
    """Supabase tools the agent knows. Status is NOT CONFIGURED on a
    host without SUPABASE_URL + SUPABASE_KEY; the code itself is real."""
    status = supabase_status().get("configured", False)
    return {name: {"status": "READY" if status else "NOT CONFIGURED",
                   "args": meta["args"],
                   "description": meta["description"]}
            for name, meta in SUPABASE_TOOLS.items()}


def dispatch_supabase(tool_name, args=None):
    """Dispatch one Supabase tool. Returns the client's real result
    dict (or its honest NOT CONFIGURED result without credentials)."""
    from . import supabase_client

    args = args or {}
    client = supabase_client.SupabaseClient()
    if tool_name == "supabase_status":
        return client.status()
    method = {
        "supabase_select": client.select,
        "supabase_insert": client.insert,
        "supabase_update": client.update,
        "supabase_delete": client.delete,
        "supabase_save_memory": client.save_memory,
        "supabase_recall_memories": client.recall_memories,
        "supabase_create_table": client.create_table_via_sql,
        "supabase_rpc": client.rpc,
    }.get(tool_name)
    if method is None:
        return {"ok": False, "error": f"unknown supabase tool: {tool_name}"}
    try:
        if tool_name == "supabase_select":
            return method(args["table"], args.get("columns", "*"),
                          args.get("filters"), args.get("limit", 50),
                          args.get("order"))
        if tool_name == "supabase_insert":
            return method(args["table"], args["rows"])
        if tool_name == "supabase_update":
            return method(args["table"], args["values"], args["filters"])
        if tool_name == "supabase_delete":
            return method(args["table"], args["filters"])
        if tool_name == "supabase_save_memory":
            return method(args["content"], args.get("kind", "note"),
                          args.get("meta"))
        if tool_name == "supabase_recall_memories":
            return method(args.get("query"), args.get("kind"),
                          args.get("limit", 20))
        if tool_name == "supabase_create_table":
            return method(args["sql"])
        if tool_name == "supabase_rpc":
            return method(args["fn"], args.get("params"))
    except KeyError as exc:
        return {"ok": False, "error": f"missing argument: {exc}"}
    return {"ok": False, "error": f"unhandled supabase tool: {tool_name}"}


def drive_status():
    from . import drive_client

    return drive_client.DriveClient().status()


def list_drive_tools():
    """Drive tools the agent knows. Status is NOT CONFIGURED on a host
    without Drive credentials in env; the code itself is real."""
    status = drive_status().get("configured", False)
    return {name: {"status": "READY" if status else "NOT CONFIGURED",
                   "args": meta["args"],
                   "description": meta["description"]}
            for name, meta in DRIVE_TOOLS.items()}


def dispatch_drive(tool_name, args=None):
    """Dispatch one Drive tool. Returns the client's real result dict
    (or its honest NOT CONFIGURED result without credentials)."""
    from . import drive_client
    from . import shell_tool

    args = args or {}
    client = drive_client.DriveClient()
    if tool_name == "drive_status":
        return client.status()
    if tool_name == "drive_list_tools":
        return client.list_tools(args.get("page_size", 100))
    if tool_name == "drive_upload_tool":
        if "local_path" not in args:
            return {"ok": False, "error": "missing argument: 'local_path'"}
        return client.upload_tool(args["local_path"], args.get("name"))
    if tool_name == "drive_download_tool":
        if "name" not in args:
            return {"ok": False, "error": "missing argument: 'name'"}
        dest = args.get("dest_dir") or str(shell_tool.workdir_root() / "tools")
        return client.download_tool(args["name"], dest)
    return {"ok": False, "error": f"unknown drive tool: {tool_name}"}


# ---------------------------------------------------------- custom tools
def list_custom_tools():
    """Tools the agent created through its own tool pipeline
    (agent_ultra/custom_tools/, evidence-backed)."""
    from . import tool_pipeline

    return tool_pipeline.list_custom_tools()


def dispatch_custom(tool_name, args=None):
    """Dispatch one agent-created custom tool (validated at call time)."""
    from . import tool_pipeline

    return tool_pipeline.dispatch_custom(tool_name, args)
