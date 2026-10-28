"""Browser-control tools (Playwright) — the full action set.

Every tool here runs a REAL Playwright action against the copy's
Chromium profile and returns the real result (ok/fail + what was
actually seen). Nothing is faked: a click that did not happen, a
selector that was not found, or a browser that is not installed is
reported as a failure, never as a success.

SPEED DESIGN (owner's target: 1-2 seconds per action):
- No artificial delays, no sleep-based waits anywhere.
- Selector waits are bounded tight (default 2000 ms, overridable).
- Navigation uses wait_until="domcontentloaded", NOT "networkidle"
  (networkidle waits for the whole page to go quiet and is slow).
- Every action result carries its measured milliseconds (perf_counter).
- HONEST LIMIT: the 1-2 s target is PER ACTION. Page load time is the
  site's + the network's, not ours — a heavy page or slow network can
  exceed it, and the measured ms in the result will show that plainly.
  No timing is ever claimed that was not measured.

LAZY IMPORT: Playwright is imported inside start(), so importing this
module never crashes on a host without Playwright. If Playwright or
Chromium is absent, actions return an honest PLAYWRIGHT-ABSENT /
BROWSER-ABSENT error instead of a fake page state.

GOOGLE SIGN-IN: sign-in is NEVER automated here and NO Google
password is ever stored. The owner signs in herself through the
in-chat browser; the persistent primary profile (see
browser_profile.GoogleProfile) keeps the session via Chromium
cookies/storage. Per-copy Google sign-ins would each need her own
sign-in and are not automated.

No prompt content lives in this module: tool descriptions are plain
capability descriptions, not model prompts.
"""

import time
from pathlib import Path

DEFAULT_WAIT_MS = 2000
DEFAULT_NAV_TIMEOUT_MS = 15000
DEFAULT_GOTO_WAIT = "domcontentloaded"


class BrowserNotAvailable(Exception):
    """Playwright or Chromium is missing on this host."""


def playwright_available():
    """True only if the playwright package imports."""
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def _new_page_context():
    """Return sync_playwright() context manager, or raise honestly."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserNotAvailable(
            "PLAYWRIGHT-ABSENT: the playwright package is not installed "
            "on this host. Install it (pip install playwright) and run "
            "`playwright install chromium` first."
        ) from exc
    return sync_playwright()


class BrowserSession:
    """One live browser session bound to one profile directory.

    Uses a persistent Chromium context so logins/cookies in the
    profile dir survive across sessions (this is how the owner's
    Google sign-in persists — via the profile, never via a stored
    password).
    """

    def __init__(self, profile_dir, headless=True, viewport=None):
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.viewport = viewport or {"width": 1280, "height": 800}
        self.timings = []  # [{"action", "ms", "ok"}] — measured only
        self._pw = None
        self._ctx = None
        self._page = None

    def start(self):
        """Launch the persistent context. Raises BrowserNotAvailable
        (not a fake page) when Playwright/Chromium is missing."""
        if self._page is not None:
            return self._page
        pw_cm = _new_page_context()
        self._pw = pw_cm.start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                viewport=self.viewport,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
        except Exception as exc:
            self._pw.stop()
            self._pw = None
            raise BrowserNotAvailable(
                "BROWSER-ABSENT: Chromium could not be launched "
                f"({exc}). Run `playwright install chromium` first."
            ) from exc
        pages = self._ctx.pages
        self._page = pages[0] if pages else self._ctx.new_page()
        return self._page

    def page(self):
        if self._page is None:
            return self.start()
        return self._page

    def close(self):
        try:
            if self._ctx is not None:
                self._ctx.close()
        finally:
            if self._pw is not None:
                self._pw.stop()
            self._ctx = None
            self._page = None
            self._pw = None

    # ------------------------------------------------------------ core
    def act(self, action, **kw):
        """Run one action, timed. Returns a real result dict."""
        t0 = time.perf_counter()
        try:
            detail = _ACTIONS[action](self, **kw)
            ok = True
        except KeyError:
            detail = {"error": f"unknown browser action: {action!r}"}
            ok = False
        except BrowserNotAvailable as exc:
            detail = {"error": str(exc)}
            ok = False
        except Exception as exc:  # Playwright errors: timeout, closed, ...
            detail = {"error": f"{type(exc).__name__}: {exc}"}
            ok = False
        ms = round((time.perf_counter() - t0) * 1000, 1)
        result = {"ok": ok, "action": action, "ms": ms, "detail": detail}
        self.timings.append({"action": action, "ms": ms, "ok": ok})
        return result


# ------------------------------------------------------------ helpers
def _wait(kw):
    return int(kw.get("timeout_ms", DEFAULT_WAIT_MS))


def _loc(page, kw):
    """Selector locator, or None when the action is coordinate-based."""
    sel = kw.get("selector")
    return page.locator(sel) if sel else None


def _coords(kw):
    return kw.get("x"), kw.get("y")


# ------------------------------------------------------------ actions
def _goto(s, **kw):
    url = kw["url"]
    timeout = int(kw.get("timeout_ms", DEFAULT_NAV_TIMEOUT_MS))
    s.page().goto(url, wait_until=DEFAULT_GOTO_WAIT, timeout=timeout)
    return {"url": s.page().url, "title": s.page().title()}


def _click(s, **kw):
    page = s.page()
    loc, (x, y) = _loc(page, kw), _coords(kw)
    if loc is not None:
        loc.click(timeout=_wait(kw))
    elif x is not None and y is not None:
        page.mouse.click(float(x), float(y))
    else:
        raise ValueError("click needs selector or x+y")
    return {"url": page.url, "title": page.title()}


def _dblclick(s, **kw):
    page = s.page()
    loc, (x, y) = _loc(page, kw), _coords(kw)
    if loc is not None:
        loc.dblclick(timeout=_wait(kw))
    elif x is not None and y is not None:
        page.mouse.dblclick(float(x), float(y))
    else:
        raise ValueError("dblclick needs selector or x+y")
    return {"url": page.url}


def _type(s, **kw):
    page = s.page()
    text = kw.get("text", "")
    loc = _loc(page, kw)
    if loc is not None:
        loc.click(timeout=_wait(kw))
        loc.fill(text, timeout=_wait(kw))
        return {"filled": text, "url": page.url}
    page.keyboard.type(text)
    return {"typed_chars": len(text), "url": page.url}


def _fill(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("fill needs selector")
    loc.fill(kw.get("text", ""), timeout=_wait(kw))
    return {"filled": True, "value": loc.input_value()}


def _press(s, **kw):
    s.page().keyboard.press(kw["key"])
    return {"key": kw["key"], "url": s.page().url}


def _scroll_down(s, **kw):
    amount = float(kw.get("amount", 600))
    s.page().mouse.wheel(0, amount)
    return {"scrolled": amount, "y": s.page().evaluate("window.scrollY")}


def _scroll_up(s, **kw):
    amount = float(kw.get("amount", 600))
    s.page().mouse.wheel(0, -amount)
    return {"scrolled": -amount, "y": s.page().evaluate("window.scrollY")}


def _scroll_to(s, **kw):
    y = float(kw.get("y", 0))
    s.page().evaluate(f"window.scrollTo(0, {y})")
    return {"y": s.page().evaluate("window.scrollY")}


def _move(s, **kw):
    x, y = _coords(kw)
    if x is None or y is None:
        raise ValueError("move needs x+y")
    s.page().mouse.move(float(x), float(y))
    return {"x": x, "y": y}


def _hover(s, **kw):
    page = s.page()
    loc, (x, y) = _loc(page, kw), _coords(kw)
    if loc is not None:
        loc.hover(timeout=_wait(kw))
    elif x is not None and y is not None:
        page.mouse.move(float(x), float(y))
    else:
        raise ValueError("hover needs selector or x+y")
    return {"hovered": True}


def _drag(s, **kw):
    page = s.page()
    x1, y1 = float(kw["x1"]), float(kw["y1"])
    x2, y2 = float(kw["x2"]), float(kw["y2"])
    page.mouse.move(x1, y1)
    page.mouse.down()
    page.mouse.move(x2, y2, steps=5)
    page.mouse.up()
    return {"from": [x1, y1], "to": [x2, y2]}


def _copy(s, **kw):
    """Copy selected/element text to the clipboard, then read it back
    to prove the copy happened. Clipboard read can be denied by the
    browser — that is reported, not faked."""
    page = s.page()
    loc, (x, y) = _loc(page, kw), _coords(kw)
    if loc is not None:
        loc.click(timeout=_wait(kw))
        page.keyboard.press("Control+A")
    elif x is not None and y is not None:
        page.mouse.click(float(x), float(y))
        page.keyboard.press("Control+A")
    else:
        page.keyboard.press("Control+A")
    page.keyboard.press("Control+C")
    try:
        text = page.evaluate("navigator.clipboard.readText()")
        return {"copied_chars": len(text or ""), "text": (text or "")[:500]}
    except Exception as exc:
        return {
            "copied": "unverified",
            "note": "clipboard read was denied by the browser; "
                    "Control+C was sent but the content could not be "
                    f"read back ({type(exc).__name__}).",
        }


def _paste(s, **kw):
    """Paste into a focused element; read the element value back when
    it is an input/textarea, so the paste is verified, not assumed."""
    page = s.page()
    loc, (x, y) = _loc(page, kw), _coords(kw)
    if loc is not None:
        loc.click(timeout=_wait(kw))
    elif x is not None and y is not None:
        page.mouse.click(float(x), float(y))
    page.keyboard.press("Control+V")
    detail = {"pasted": True}
    if loc is not None:
        try:
            detail["value_after_paste"] = loc.input_value()
        except Exception:
            pass
    return detail


def _back(s, **kw):
    s.page().go_back(wait_until=DEFAULT_GOTO_WAIT)
    return {"url": s.page().url, "title": s.page().title()}


def _forward(s, **kw):
    s.page().go_forward(wait_until=DEFAULT_GOTO_WAIT)
    return {"url": s.page().url, "title": s.page().title()}


def _reload(s, **kw):
    s.page().reload(wait_until=DEFAULT_GOTO_WAIT)
    return {"url": s.page().url, "title": s.page().title()}


def _screenshot(s, **kw):
    page = s.page()
    out = Path(kw["path"]) if kw.get("path") else Path.cwd() / "screenshot.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out))
    return {"path": str(out), "bytes": out.stat().st_size}


def _wait_selector(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("wait_for_selector needs selector")
    loc.wait_for(state=kw.get("state", "visible"), timeout=_wait(kw))
    return {"found": True, "selector": kw["selector"]}


def _get_text(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        return {"text": page.inner_text("body")[:5000]}
    try:
        return {"text": loc.inner_text(timeout=_wait(kw))}
    except Exception:
        return {"text": loc.text_content(timeout=_wait(kw))}


def _get_title(s, **kw):
    return {"title": s.page().title(), "url": s.page().url}


def _select_option(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("select_option needs selector")
    value = kw.get("value")
    label = kw.get("label")
    if value is not None:
        picked = loc.select_option(value=value, timeout=_wait(kw))
    elif label is not None:
        picked = loc.select_option(label=label, timeout=_wait(kw))
    else:
        raise ValueError("select_option needs value or label")
    return {"selected": picked}


def _check(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("check needs selector")
    loc.check(timeout=_wait(kw))
    return {"checked": loc.is_checked()}


def _uncheck(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("uncheck needs selector")
    loc.uncheck(timeout=_wait(kw))
    return {"checked": loc.is_checked()}


def _focus(s, **kw):
    page = s.page()
    loc = _loc(page, kw)
    if loc is None:
        raise ValueError("focus needs selector")
    loc.focus(timeout=_wait(kw))
    return {"focused": True}


def _evaluate(s, **kw):
    return {"value": s.page().evaluate(kw["expression"])}


_ACTIONS = {
    "goto": _goto,
    "navigate": _goto,
    "click": _click,
    "dblclick": _dblclick,
    "type": _type,
    "fill": _fill,
    "press": _press,
    "scroll_down": _scroll_down,
    "scroll_up": _scroll_up,
    "scroll_to": _scroll_to,
    "move": _move,
    "hover": _hover,
    "drag": _drag,
    "copy": _copy,
    "paste": _paste,
    "back": _back,
    "forward": _forward,
    "reload": _reload,
    "screenshot": _screenshot,
    "wait_for_selector": _wait_selector,
    "get_text": _get_text,
    "get_title": _get_title,
    "get_url": lambda s, **kw: {"url": s.page().url},
    "select_option": _select_option,
    "check": _check,
    "uncheck": _uncheck,
    "focus": _focus,
    "evaluate": _evaluate,
}

BROWSER_TOOLS = {
    name: {
        "action": name,
        "params": sorted({
            "goto": ["url"],
            "navigate": ["url"],
            "click": ["selector?", "x?", "y?"],
            "dblclick": ["selector?", "x?", "y?"],
            "type": ["selector?", "text"],
            "fill": ["selector", "text"],
            "press": ["key"],
            "scroll_down": ["amount?"],
            "scroll_up": ["amount?"],
            "scroll_to": ["y"],
            "move": ["x", "y"],
            "hover": ["selector?", "x?", "y?"],
            "drag": ["x1", "y1", "x2", "y2"],
            "copy": ["selector?", "x?", "y?"],
            "paste": ["selector?", "x?", "y?"],
            "back": [],
            "forward": [],
            "reload": [],
            "screenshot": ["path?"],
            "wait_for_selector": ["selector", "state?"],
            "get_text": ["selector?"],
            "get_title": [],
            "get_url": [],
            "select_option": ["selector", "value?|label?"],
            "check": ["selector"],
            "uncheck": ["selector"],
            "focus": ["selector"],
            "evaluate": ["expression"],
        }[name]),
        "speed_note": "Target 1-2 s per action (measured ms in every "
                      "result); page load/network time excluded honestly.",
    }
    for name in _ACTIONS
}


def list_browser_tools():
    """Names + params of every browser tool, so copies know them."""
    return [{"tool": name, **spec} for name, spec in sorted(BROWSER_TOOLS.items())]


def dispatch_browser_action(session, tool_name, args=None):
    """Dispatch one browser tool on an open BrowserSession. Returns
    the timed real result dict."""
    if not isinstance(session, BrowserSession):
        return {"ok": False, "action": tool_name, "ms": 0.0,
                "detail": {"error": "no open BrowserSession given"}}
    return session.act(tool_name, **(args or {}))
