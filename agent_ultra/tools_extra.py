"""Extra agent tools: calculator, weather, internet, imagine, understand.

These are the tools the owner named (imagine, understand, calculator,
weather) so the agent "knows" them: they are registered here and wired
into the dispatcher bridge, so copies can call them.

HONESTY RULE for this module: a tool either returns a real result
(computed here, or fetched live from the internet) or an error that
says so. Nothing is faked.

- calculator: REAL. Safe arithmetic via ast parsing — no eval() on
  raw input. Numbers, + - * / // % **, parentheses, unary minus, and
  a small allow-list of functions (abs, round, min, max, sqrt, floor,
  ceil). Anything else (names, attributes, imports, calls outside the
  allow-list) is rejected with an error.
- weather: REAL. Open-Meteo, no API key: geocode the place name, then
  fetch current weather. Network failure is reported as an error,
  never as invented weather.
- internet_fetch / internet_search: REAL. Fetch a page's text (tags
  stripped) and DuckDuckGo HTML search (no key). A failed or
  unparseable provider response is reported as an error, never as
  invented results.
- imagine: REAL if the no-key provider answers (Pollinations, no key
  needed); the returned bytes are checked to be an actual image
  before they are saved. If the provider fails, the tool returns an
  error — it never writes a fake image.
- understand_text / understand_file / understand_page: REAL local
  extractive understanding (sentence scoring by word frequency, no
  model call, no faked summary).
- understand_image: UNTESTED. Image understanding needs a vision
  model; the 14B base is text-only, so this refuses instead of
  faking an image description.

No prompt content lives in this module: tool descriptions below are
plain capability descriptions, not model prompts.
"""

import ast
import html
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

UA = {"User-Agent": "Agent-Ultra/1.0 (tool; +https://github.com/ixtalishgirl/Agent-Ultra)"}
TIMEOUT = 20


def _http_get(url, timeout=TIMEOUT):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


# ---------------------------------------------------------------- calculator
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
}

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_ALLOWED_UNOPS = (ast.UAdd, ast.USub)


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            # Guard against absurd exponents (10**10**10 hangs memory).
            if abs(right) > 1000 or (abs(left) > 10 and abs(right) > 100):
                raise ValueError("exponent too large")
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.FloorDiv):
            return left // right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNOPS):
        val = _eval_node(node.operand)
        return val if isinstance(node.op, ast.UAdd) else -val
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None:
            raise ValueError(f"function not allowed: {node.func.id}")
        args = [_eval_node(a) for a in node.args]
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        return fn(*args)
    raise ValueError(f"not allowed in arithmetic: {type(node).__name__}")


def calculator(expression):
    """REAL: safely compute an arithmetic expression. No eval()."""
    if not isinstance(expression, str) or not expression.strip():
        return {"status": "error", "detail": "empty expression"}
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 200:
            return {"status": "error", "detail": "expression too long"}
        result = _eval_node(tree)
    except ZeroDivisionError:
        return {"status": "error", "detail": "division by zero"}
    except (SyntaxError, ValueError, TypeError, OverflowError) as exc:
        return {"status": "error", "detail": f"invalid expression: {exc}"}
    if isinstance(result, float) and (math.isinf(result) or math.isnan(result)):
        return {"status": "error", "detail": "result is not a finite number"}
    return {"status": "ok", "expression": expression, "result": result}


# ---------------------------------------------------------------- weather
def weather(place):
    """REAL: current weather via Open-Meteo (no API key)."""
    if not isinstance(place, str) or not place.strip():
        return {"status": "error", "detail": "empty place name"}
    try:
        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search?name="
            + urllib.parse.quote(place.strip())
            + "&count=1&language=en&format=json"
        )
        _, _, geo_raw = _http_get(geo_url)
        import json

        geo = json.loads(geo_raw.decode("utf-8", "replace"))
        results = geo.get("results") or []
        if not results:
            return {"status": "error", "detail": f"place not found: {place}"}
        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        wx_url = (
            "https://api.open-meteo.com/v1/forecast?latitude="
            f"{lat}&longitude={lon}&current=temperature_2m,"
            "relative_humidity_2m,apparent_temperature,weather_code,"
            "wind_speed_10m&timezone=auto"
        )
        _, _, wx_raw = _http_get(wx_url)
        wx = json.loads(wx_raw.decode("utf-8", "replace"))
        cur = wx.get("current") or {}
        if "temperature_2m" not in cur:
            return {"status": "error", "detail": "weather provider returned no current data"}
        return {
            "status": "ok",
            "place": loc.get("name"),
            "country": loc.get("country"),
            "latitude": lat,
            "longitude": lon,
            "temperature_2m": cur.get("temperature_2m"),
            "apparent_temperature": cur.get("apparent_temperature"),
            "relative_humidity_2m": cur.get("relative_humidity_2m"),
            "weather_code": cur.get("weather_code"),
            "wind_speed_10m": cur.get("wind_speed_10m"),
            "time": cur.get("time"),
            "source": "open-meteo",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "error", "detail": f"network failure: {exc}"}
    except (ValueError, KeyError) as exc:
        return {"status": "error", "detail": f"provider response unusable: {exc}"}


# ---------------------------------------------------------------- internet
class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.title = ""
        self._in_title = False
        self._skip = 0  # inside script/style

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
        else:
            self.parts.append(text)


def internet_fetch(url, max_chars=4000):
    """REAL: fetch a page and return its visible text (tags stripped)."""
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return {"status": "error", "detail": "url must start with http:// or https://"}
    try:
        status, ctype, raw = _http_get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "error", "detail": f"network failure: {exc}"}
    if status != 200:
        return {"status": "error", "detail": f"HTTP {status}"}
    text = raw.decode("utf-8", "replace")
    if "html" in ctype:
        parser = _TextExtractor()
        parser.feed(text)
        body = " ".join(parser.parts)
        body = re.sub(r"\s+", " ", body).strip()
        title = parser.title
    else:
        body, title = re.sub(r"\s+", " ", text).strip(), ""
    return {
        "status": "ok",
        "url": url,
        "http_status": status,
        "title": title,
        "text": body[:max_chars],
        "text_length": len(body),
        "source": "live fetch",
    }


_DDG_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.DOTALL
)


def internet_search(query, max_results=8):
    """REAL: web search. Primary route is DuckDuckGo HTML (no key).
    DDG bot-blocks some hosts (HTTP 202 challenge page); when its
    results cannot be parsed, the tool falls back to the Wikipedia
    OpenSearch API (no key, official) and labels the source honestly.
    If both routes fail, it returns an error — never fake results."""
    if not isinstance(query, str) or not query.strip():
        return {"status": "error", "detail": "empty query"}
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query.strip())
    try:
        status, _, raw = _http_get(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        status, raw = None, b""
        ddg_error = f"network failure: {exc}"
    else:
        ddg_error = None
    if status == 200:
        page = raw.decode("utf-8", "replace")
        results = []
        for href, title_html in _DDG_RE.findall(page):
            title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            link = html.unescape(href)
            # DuckDuckGo wraps results as //duckduckgo.com/l/?uddg=<target>
            parsed = urllib.parse.urlparse(link)
            qs = urllib.parse.parse_qs(parsed.query)
            if "uddg" in qs:
                link = qs["uddg"][0]
            if title and link.startswith("http"):
                results.append({"title": title, "url": link})
            if len(results) >= max_results:
                break
        if results:
            return {"status": "ok", "query": query, "results": results,
                    "source": "duckduckgo-html"}
    # Fallback: Wikipedia OpenSearch (no key). Labelled as such, so the
    # caller always knows where the results came from.
    try:
        import json

        wiki_url = (
            "https://en.wikipedia.org/w/api.php?action=opensearch&search="
            + urllib.parse.quote(query.strip())
            + f"&limit={max_results}&namespace=0&format=json"
        )
        _, _, wiki_raw = _http_get(wiki_url)
        data = json.loads(wiki_raw.decode("utf-8", "replace"))
        titles, descs, links = data[1], data[2], data[3]
        results = [
            {"title": t, "url": u, "snippet": d}
            for t, d, u in zip(titles, descs, links)
        ]
        if results:
            return {
                "status": "ok",
                "query": query,
                "results": results,
                "source": "wikipedia-opensearch",
                "note": "DuckDuckGo HTML was unreachable/unparseable from "
                        "this host (bot challenge); results are Wikipedia.",
            }
    except (urllib.error.URLError, TimeoutError, OSError, ValueError,
            IndexError, KeyError) as exc:
        return {"status": "error",
                "detail": f"search failed (ddg: {ddg_error or 'unparseable'}; "
                          f"wikipedia fallback: {exc})"}
    return {
        "status": "error",
        "detail": "no results from any search route "
                  f"(ddg: {ddg_error or 'unparseable'})",
    }


# ---------------------------------------------------------------- imagine
def imagine(description, out_dir):
    """REAL if the no-key provider answers: generate an image and save
    its real bytes. Never writes a fake image: on provider failure it
    returns an error instead of a file."""
    if not isinstance(description, str) or not description.strip():
        return {"status": "error", "detail": "empty description"}
    url = (
        "https://image.pollinations.ai/prompt/"
        + urllib.parse.quote(description.strip())
        + "?width=1024&height=1024&nologo=true"
    )
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=60) as resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"status": "error", "detail": f"image provider unreachable: {exc}"}
    if not ctype.startswith("image/") or len(data) < 1000:
        return {
            "status": "error",
            "detail": f"image provider returned non-image data ({ctype}, {len(data)} bytes)",
        }
    ext = "jpg" if "jpeg" in ctype else "png"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"imagine-{uuid.uuid4().hex[:12]}.{ext}"
    with open(path, "wb") as f:
        f.write(data)
    return {
        "status": "ok",
        "path": str(path),
        "bytes": len(data),
        "content_type": ctype,
        "source": "pollinations (no key)",
    }


# ---------------------------------------------------------------- understand
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that",
    "as", "at", "by", "from", "we", "you", "they", "he", "she", "i",
}


def understand_text(text, max_sentences=3):
    """REAL local extractive understanding: key sentences by word
    frequency. No model call, no invented summary."""
    if not isinstance(text, str) or not text.strip():
        return {"status": "error", "detail": "empty text"}
    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", text.strip())
        if s.strip()
    ]
    words = re.findall(r"[a-z0-9]+", text.lower())
    freq = {}
    for w in words:
        if w not in _STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sentences):
        sw = re.findall(r"[a-z0-9]+", s.lower())
        score = sum(freq.get(w, 0) for w in sw) / max(1, len(sw))
        scored.append((score, i, s))
    scored.sort(key=lambda t: (-t[0], t[1]))
    top = sorted(scored[:max_sentences], key=lambda t: t[1])
    return {
        "status": "ok",
        "chars": len(text),
        "words": len(words),
        "sentences": len(sentences),
        "key_sentences": [s for _, _, s in top],
        "method": "extractive word-frequency (no model call)",
    }


def understand_file(path):
    """REAL: understand a local text file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"status": "error", "detail": f"cannot read file: {exc}"}
    out = understand_text(text)
    out["file"] = str(path)
    return out


def understand_page(url):
    """REAL: fetch a page, then understand its text."""
    fetched = internet_fetch(url, max_chars=20000)
    if fetched["status"] != "ok":
        return fetched
    out = understand_text(fetched["text"])
    out["url"] = url
    out["title"] = fetched["title"]
    return out


def understand_image(path):
    """UNTESTED: image understanding needs a vision model. The 14B
    base is text-only, so this refuses instead of faking a description."""
    raise NotImplementedError(
        "UNTESTED: image understanding needs a vision model; the 14B "
        "base model is text-only. Refusing instead of faking an image "
        "description."
    )


# ---------------------------------------------------------------- registry
TOOLS = {
    "calculator": {"fn": calculator, "status": "REAL",
                   "description": "Safe arithmetic evaluation (no eval)."},
    "weather": {"fn": weather, "status": "REAL",
                "description": "Current weather via Open-Meteo (no key)."},
    "internet_fetch": {"fn": internet_fetch, "status": "REAL",
                       "description": "Fetch a page's visible text."},
    "internet_search": {"fn": internet_search, "status": "REAL",
                        "description": "Web search: DuckDuckGo HTML first, Wikipedia OpenSearch fallback (source labelled)."},
    "imagine": {"fn": imagine, "status": "REAL",
                "description": "Generate an image via a no-key provider; errors honestly if unavailable."},
    "understand_text": {"fn": understand_text, "status": "REAL",
                        "description": "Extractive understanding of text (no model call)."},
    "understand_file": {"fn": understand_file, "status": "REAL",
                        "description": "Extractive understanding of a text file."},
    "understand_page": {"fn": understand_page, "status": "REAL",
                        "description": "Fetch a page, then understand its text."},
    "understand_image": {"fn": understand_image, "status": "UNTESTED",
                         "description": "Image understanding (needs a vision model)."},
}


def list_extra_tools():
    return {
        name: {"status": meta["status"], "description": meta["description"]}
        for name, meta in TOOLS.items()
    }


def dispatch_tool(name, args=None):
    """Call one extra tool by name. Returns its result dict; unknown
    names and UNTESTED refusals come back as errors, never fakes."""
    meta = TOOLS.get(name)
    if meta is None:
        return {"status": "error", "detail": f"unknown extra tool: {name}"}
    try:
        return meta["fn"](**(args or {}))
    except NotImplementedError as exc:
        return {"status": "error", "detail": str(exc), "untested": True}
    except TypeError as exc:
        return {"status": "error", "detail": f"bad arguments: {exc}"}
