"""Tool pipeline — how the agent creates its OWN tools (self-modification
mechanism, no model call needed for the mechanism itself).

The five stages mirror the Agent OS per-tool pipeline
(intake, validated_call, execute, evidence, report):

  1. intake: accept a tool spec — name, description, source code, the
     argument names it takes, and test cases (input -> expected output).
  2. validated_call: validate the spec before anything is written:
     the name must be a plain identifier and must NOT collide with the
     761 Agent OS tools, the extra tools, the browser tools, or an
     existing custom tool; the source must parse as Python, define
     exactly one module-level function with the tool's name, and must
     NOT contain imports, eval/exec/compile, open(), __import__(), or
     dunder attribute access. Custom tools are pure computation.
  3. execute: the PIPELINE writes the tool file into
     agent_ultra/custom_tools/ (never a hand-written file outside the
     pipeline), imports it, and runs its declared test cases.
  4. evidence: write <name>.test_evidence.json next to the tool file
     (source sha256, file size, per-test input/expected/actual).
  5. report: return the report dict. A tool whose tests fail is NOT
     registered: its file is removed and the report says so.

HONEST LIMIT: this pipeline validates provenance and tests. It is NOT
a sandbox — a registered custom tool runs in-process with the agent's
own privileges inside the agent's own container, exactly like the
agent's own code. That is documented here so nobody mistakes the
pipeline for isolation.

No prompt content lives in this module. Tool descriptions are plain
capability descriptions, not model prompts.
"""

import ast
import hashlib
import importlib.util
import json
import keyword
import sys
from datetime import datetime, timezone
from pathlib import Path

CUSTOM_DIR = Path(__file__).resolve().parent / "custom_tools"

_BANNED_CALLS = {"eval", "exec", "compile", "open", "__import__", "input"}


def _custom_names():
    """Names of already-registered custom tools (files on disk)."""
    if not CUSTOM_DIR.exists():
        return set()
    return {p.stem for p in CUSTOM_DIR.glob("*.py")
            if p.name != "__init__.py"}


def _reserved_names():
    """Names the new tool must not collide with: Agent OS registry,
    extra tools, browser tools. Lazily imported so this module stays
    importable without the Agent OS dispatcher."""
    names = set()
    try:
        from . import dispatcher_bridge as bridge
        names.update(bridge.list_tools())
        names.update(bridge.list_extra_tools().keys())
        names.update(t["tool"] for t in bridge.list_browser_tools())
    except Exception:
        # If the Agent OS dispatcher cannot load here, collision
        # checking against it is skipped — but the custom-dir check
        # above still applies, and dispatch re-validates at call time.
        pass
    return names


def _validate_source(name, source, arg_names):
    """Stage 2 validation. Returns an error string, or None if valid."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"source does not parse: {exc}"
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(funcs) != 1 or funcs[0].name != name:
        return ("source must define exactly one module-level function "
                f"named {name!r}")
    fn = funcs[0]
    declared = [a.arg for a in fn.args.args]
    if declared != list(arg_names):
        return (f"function arguments {declared} do not match declared "
                f"args {list(arg_names)}")
    if fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs:
        return "variadic / keyword-only arguments are not allowed"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return "imports are not allowed in a custom tool"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _BANNED_CALLS:
                return f"banned call: {node.func.id}()"
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return f"dunder attribute access is not allowed: {node.attr}"
        if isinstance(node, ast.Global):
            return "global statements are not allowed"
    return None


def tool_create(name, description, source, arg_names, tests):
    """Run all five stages and create one custom tool.

    tests: list of {"args": {...}, "expected": {...}} dicts.
    Returns a report dict; ok is True only if the tool was written,
    imported, and passed every test case.
    """
    stages = []
    # Stage 1 — intake.
    if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
        return {"ok": False, "tool": name, "stage": "intake",
                "error": f"invalid tool name: {name!r}"}
    if not isinstance(description, str) or not description.strip():
        return {"ok": False, "tool": name, "stage": "intake",
                "error": "description must be a non-empty string"}
    if not isinstance(tests, list) or not tests:
        return {"ok": False, "tool": name, "stage": "intake",
                "error": "at least one test case is required"}
    stages.append("intake")
    # Stage 2 — validated_call.
    if name in _custom_names():
        return {"ok": False, "tool": name, "stage": "validated_call",
                "error": f"tool {name!r} already exists in custom_tools/"}
    if name in _reserved_names():
        return {"ok": False, "tool": name, "stage": "validated_call",
                "error": f"tool name {name!r} collides with an existing tool"}
    problem = _validate_source(name, source, arg_names)
    if problem:
        return {"ok": False, "tool": name, "stage": "validated_call",
                "error": problem}
    stages.append("validated_call")
    # Stage 3 — execute: the pipeline writes the file, imports it, tests it.
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    header = (f'"""Custom tool {name} — created through the agent tool '
              f'pipeline (tool_create), not hand-written.\n\n'
              f'{description}\n"""\n\n')
    tool_path = CUSTOM_DIR / f"{name}.py"
    tool_path.write_text(header + source.rstrip() + "\n", encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(f"custom_tools.{name}",
                                                      tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, name)
    except Exception as exc:
        tool_path.unlink(missing_ok=True)
        return {"ok": False, "tool": name, "stage": "execute",
                "error": f"tool file failed to import: {type(exc).__name__}: {exc}"}
    results = []
    for case in tests:
        args = case.get("args", {})
        expected = case.get("expected")
        try:
            actual = fn(**args)
            passed = actual == expected
            detail = None
        except Exception as exc:
            actual = None
            passed = False
            detail = f"{type(exc).__name__}: {exc}"
        results.append({"args": args, "expected": expected,
                        "actual": actual, "passed": passed, "detail": detail})
    stages.append("execute")
    # Stage 4 — evidence.
    evidence = {
        "tool": name,
        "description": description,
        "arg_names": list(arg_names),
        "file": str(tool_path),
        "sha256": hashlib.sha256(tool_path.read_bytes()).hexdigest(),
        "bytes": tool_path.stat().st_size,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "tests_total": len(results),
        "tests_passed": sum(1 for r in results if r["passed"]),
        "tests": results,
    }
    evidence_path = CUSTOM_DIR / f"{name}.test_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2),
                             encoding="utf-8")
    stages.append("evidence")
    # Stage 5 — report.
    stages.append("report")
    if evidence["tests_passed"] != evidence["tests_total"]:
        tool_path.unlink(missing_ok=True)
        evidence_path.unlink(missing_ok=True)
        return {"ok": False, "tool": name, "stages": stages,
                "error": "tool tests failed — tool was NOT registered",
                "tests": results}
    return {"ok": True, "tool": name, "stages": stages,
            "file": str(tool_path), "evidence": str(evidence_path),
            "tests_passed": evidence["tests_passed"],
            "tests_total": evidence["tests_total"]}


def list_custom_tools():
    """Registered custom tools: name -> description + status, read
    from their evidence files (a tool without evidence is unlisted)."""
    out = {}
    if not CUSTOM_DIR.exists():
        return out
    for evidence_path in sorted(CUSTOM_DIR.glob("*.test_evidence.json")):
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[evidence["tool"]] = {
            "status": "REAL",
            "description": evidence.get("description", ""),
            "tests_passed": evidence.get("tests_passed"),
            "tests_total": evidence.get("tests_total"),
        }
    return out


def dispatch_custom(name, args=None):
    """Validated call of one custom tool. Returns its result dict;
    unknown tools and bad arguments come back as errors, never fakes."""
    registered = list_custom_tools()
    if name not in registered:
        return {"status": "error", "detail": f"unknown custom tool: {name}"}
    tool_path = CUSTOM_DIR / f"{name}.py"
    try:
        spec = importlib.util.spec_from_file_location(f"custom_tools.{name}",
                                                      tool_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, name)
    except Exception as exc:
        return {"status": "error",
                "detail": f"custom tool {name!r} failed to load: {exc}"}
    args = args or {}
    try:
        import inspect
        params = set(inspect.signature(fn).parameters)
        unknown = set(args) - params
        if unknown:
            return {"status": "error",
                    "detail": f"unknown arguments for {name}: {sorted(unknown)}"}
        result = fn(**args)
    except TypeError as exc:
        return {"status": "error", "detail": f"bad arguments: {exc}"}
    except Exception as exc:
        return {"status": "error",
                "detail": f"tool raised {type(exc).__name__}: {exc}"}
    return {"status": "ok", "tool": name, "result": result}
