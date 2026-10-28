"""Shell tool — FULL shell/python/terminal/bash/pip/playwright access
INSIDE the agent's own container only.

This is the agent's own machine (OpenBot-style: one container, one
/workspace per copy). The tool runs real commands via subprocess and
captures real stdout/stderr/exit codes/timeouts. Nothing is faked: a
failed command returns its real stderr and non-zero code.

WORKDIR SCOPING (a container boundary, NOT a model refusal rule):
commands run with cwd inside the agent workdir root (env AGENT_WORKDIR,
default <repo>/work). A cwd outside that root is refused with an
error, because the container's workspace is the agent's machine — the
host outside it is not. This scoping is documented here, in
ARCHITECTURE.md, and in TUNNEL.md as a boundary of the container,
not as a rule placed on the model. Absolute command paths outside
the workdir (system binaries like /usr/bin/python3, pip, playwright)
still work — only the working directory is scoped.

No prompt content lives in this module.
"""

import os
import subprocess
import time
from pathlib import Path

DEFAULT_TIMEOUT = 60
PIP_TIMEOUT = 300


def workdir_root():
    root = Path(os.environ.get("AGENT_WORKDIR", "") or
                (Path(__file__).resolve().parent.parent / "work"))
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _inside(path, root):
    """REAL containment check. is_relative_to() returns a bool — it
    does NOT raise for outside paths, so its return value must be
    used (an earlier version ignored it and returned True always;
    the verification suite caught that bug)."""
    try:
        return Path(path).resolve().is_relative_to(root)
    except Exception:
        return False


def _resolve_cwd(cwd, root):
    target = Path(cwd) if cwd else root
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if not _inside(target, root):
        raise ValueError(
            f"cwd {target} is outside the agent workdir {root}; "
            "commands run inside the agent's own machine only."
        )
    target.mkdir(parents=True, exist_ok=True)
    return target


def run(command, cwd=None, timeout=DEFAULT_TIMEOUT, shell="bash"):
    """Run one shell command. Returns real stdout/stderr/rc/ms."""
    root = workdir_root()
    t0 = time.perf_counter()
    try:
        run_cwd = _resolve_cwd(cwd, root)
    except ValueError as exc:
        return {"ok": False, "command": command, "rc": None,
                "stdout": "", "stderr": str(exc),
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    try:
        proc = subprocess.run(
            [shell, "-c", command],
            cwd=str(run_cwd), capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": proc.returncode == 0, "command": command,
                "rc": proc.returncode, "stdout": proc.stdout,
                "stderr": proc.stderr, "cwd": str(run_cwd),
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "command": command, "rc": None,
                "stdout": "", "stderr": f"timed out after {timeout}s",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except FileNotFoundError as exc:
        return {"ok": False, "command": command, "rc": None,
                "stdout": "", "stderr": f"shell not found: {exc}",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}


def run_python(code, cwd=None, timeout=DEFAULT_TIMEOUT):
    """Run python3 -c <code> inside the workdir. Real output."""
    root = workdir_root()
    t0 = time.perf_counter()
    try:
        run_cwd = _resolve_cwd(cwd, root)
    except ValueError as exc:
        return {"ok": False, "rc": None, "stdout": "", "stderr": str(exc),
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    try:
        proc = subprocess.run(
            ["python3", "-c", code],
            cwd=str(run_cwd), capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": proc.returncode == 0, "rc": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr,
                "cwd": str(run_cwd),
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": None, "stdout": "",
                "stderr": f"timed out after {timeout}s",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}


def run_python_file(path, cwd=None, timeout=DEFAULT_TIMEOUT, args=()):
    """Run a python file that lives inside the workdir."""
    root = workdir_root()
    target = Path(path)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if not _inside(target, root):
        return {"ok": False, "rc": None, "stdout": "",
                "stderr": f"file {target} is outside the agent workdir {root}"}
    if not target.exists():
        return {"ok": False, "rc": None, "stdout": "",
                "stderr": f"file not found: {target}"}
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            ["python3", str(target), *[str(a) for a in args]],
            cwd=str(_resolve_cwd(cwd, root)), capture_output=True,
            text=True, timeout=timeout,
        )
        return {"ok": proc.returncode == 0, "rc": proc.returncode,
                "stdout": proc.stdout, "stderr": proc.stderr,
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": None, "stdout": "",
                "stderr": f"timed out after {timeout}s",
                "ms": round((time.perf_counter() - t0) * 1000, 1)}


def pip_install(package, timeout=PIP_TIMEOUT):
    """pip install inside the container. Real pip output."""
    return run(f"python3 -m pip install {package}", timeout=timeout)


def pip_list():
    """Real pip list output (first lines are enough for a check)."""
    return run("python3 -m pip list", timeout=DEFAULT_TIMEOUT)
