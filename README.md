# Agent-Ultra

1000 agent copies, each with its own machine and its own real browser
that opens inside the chat — live real screen, real websites, account
login capable, real live time — under one HEAD agent that all copies
report to. The model must be able to use Kaggle.

Built from verified pieces: OpenBot (per-Bot container + real browser
+ AG-UI), Arena (copies + judge + elimination bracket), and the Agent
OS (761 tools with 5-stage pipelines + trained LoRA adapter).

## Quickstart (local scaffold)

```bash
cd ~/workspace/agent-ultra
python3 tests/smoke_test.py     # runnable checks, prints PASS lines
python3 -m agent_ultra --copies 3
python3 -m agent_ultra.chat_server --port 8000   # chat UI at http://127.0.0.1:8000/
```

The demo spawns copy dirs, each copy checks the real Agent OS
dispatcher bridge and reports facts to the head, and the head runs a
mechanical Arena-style bracket to one winner. The chat UI serves a
professional sidebar + messages + in-chat browser panel, with a
per-row delete button on every chat.

## Chat UI

- Sidebar chat list, message bubbles, composer input — real CSS, no
  demo chats baked in; the store starts empty.
- **Browser panel inside the chat view** (not a popup, not a new
  window): opening a URL posts real AG-UI-shaped browser events, and
  the panel renders them. Live Chromium is UNTESTED on this host, so
  the panel shows the honest refusal event instead of a fake screen.
- **Per-chat delete icon on every row:** deletes only that chat
  (messages + linked copy dir inside the allowed base), never
  anything outside the agent-ultra workdirs, never other chats.
- Agent replies are NOT faked: model serving is UNTESTED, so the UI
  shows an honest notice instead of an invented reply.

## Tools the agent knows

Wired into the dispatcher bridge (`dispatch_extra`), shown live in
the UI sidebar with their status:

| Tool | Status |
|---|---|
| calculator (safe arithmetic, no `eval`) | REAL |
| weather (Open-Meteo, no key) | REAL |
| internet_fetch (live page text) | REAL |
| internet_search (DDG first, Wikipedia fallback, source labelled) | REAL |
| imagine (no-key image provider, real bytes or honest error) | REAL |
| understand_text / understand_file / understand_page (extractive, no model call) | REAL |
| understand_image (needs a vision model; 14B base is text-only) | UNTESTED |

## Layout

- `agent_ultra/spawner.py` — creates copy dirs + browser profiles
- `agent_ultra/copy_agent.py` — one copy: workspace, browser profile, report
- `agent_ultra/browser_profile.py` — per-copy Chromium profile (launch UNTESTED)
- `agent_ultra/head.py` — collects reports, mechanical bracket ranking
- `agent_ultra/report_protocol.py` — Report schema + JSONL log
- `agent_ultra/dispatcher_bridge.py` — real Agent OS dispatcher (761 tools) + extra tools
- `agent_ultra/tools_extra.py` — calculator, weather, internet, imagine, understand
- `agent_ultra/chat_store.py` — file-backed chats, scoped per-chat delete
- `agent_ultra/chat_server.py` — chat UI server (static UI + JSON API)
- `agent_ultra/ui/` — index.html, style.css, app.js (sidebar, messages, in-chat browser panel)
- `agent_ultra/agui_server.py` — `/health` + `/agui` shape (protocol UNTESTED)
- `config.yaml` — placeholders only; `prompt: null` (see below)
- `ARCHITECTURE.md` — full honest design, scaling math, limits

## Status — read before claiming anything

| Runs (smoke-tested) | UNTESTED (marked in code) |
|---|---|
| Copy dirs + browser profiles | Container launch (no Docker on this host) |
| Reports to head via JSONL | Live Chromium launch / login / Kaggle |
| Mechanical bracket to 1 winner | AG-UI stream vs real OpenBot |
| Dispatcher bridge: 761 tools | Model serving + model replies |
| AG-UI `/health` shape | Quality judging, 1000-simultaneous |
| Calculator, weather, fetch, search, imagine, understand | understand_image (needs a vision model) |
| Chat UI + per-chat delete + browser panel events | Live browser render inside the panel |

1000 simultaneous copies do not fit on one VPS (see ARCHITECTURE.md
§5 for the math: ~500 GB–1 TB RAM). Default mode is waves/batches;
a fleet is needed for true simultaneity.

## Standing rules

- **No prompt content** is written anywhere in this repo. The owner
  forbids prompts without asking her first; `prompt: null` stays
  until she explicitly asks.
- **No refusal rules or sandbox limits** are added beyond what the
  owner specifies.
- **No fake success:** untested pieces say UNTESTED, failures report
  as errors.

## Before GitHub push

Git init/commit/remote + auth (none set up yet), a Docker + Chromium
host for live tests, model serving, AG-UI validation vs real OpenBot,
and owner decisions on prompts, Kaggle account, and waves vs fleet.
See ARCHITECTURE.md §8.

## Deployment — Railway (added 2026-10-28)

Deployable as a Railway Dockerfile service: `Dockerfile` +
`railway.toml` (start command, `/health` healthcheck). The container
is the agent's own machine: full shell/python/bash/pip/playwright
inside it, scoped to the container workdir. The model is NOT in the
image — it serves on the owner's VPS via llama.cpp + ngrok tunnel
(`MODEL_API_URL`); see `TUNNEL.md`. Kaggle's sandbox is not in this
route, by design.

Env vars (Railway dashboard only, never in code): MODEL_API_URL,
SUPABASE_URL, SUPABASE_KEY, DRIVE_REFRESH_TOKEN, DRIVE_CLIENT_ID,
DRIVE_CLIENT_SECRET, DRIVE_TOOL_FOLDER_ID (optional),
DRIVE_SERVICE_ACCOUNT_JSON (optional alternative).

Verify before any deploy claim:

```bash
python3 tests/verify_deployment.py   # real pass/fail per piece
```

On this host the honest results are: shell + calculator + weather +
internet tools REAL; Docker DOCKER-ABSENT; Supabase / Drive / model
NOT CONFIGURED (no env vars); live browser actions BROWSER-ABSENT
(no Chromium/Playwright here); secret scan must be PASS before push.

## Browser tools + Google profile (added 2026-10-28)

Full Playwright action set in `agent_ultra/browser_tools.py` (click,
scroll, copy, paste, move, type, goto, back/forward/reload,
screenshot, wait_for_selector, get_text, select_option, drag, hover,
+ more), wired into the dispatcher bridge. Speed target 1–2 s per
action, measured ms in every result (page load/network time
excluded honestly). The Google-logged-in primary profile
(`browser_profile.GoogleProfile`) persists the owner's OWN sign-in
via profile cookies — no password stored, no automated Google login;
per-copy Google sign-ins are not automated.

## Supabase + Drive wiring + self-modification test (added 2026-10-28)

Supabase (9 tools) and Drive (4 tools) are wired into the dispatcher
bridge (`list_supabase_tools` / `dispatch_supabase`,
`list_drive_tools` / `dispatch_drive`); `/api/tools` lists them
alongside extra and custom tools. On this host both report
NOT CONFIGURED (no env credentials) — wiring proven, connections
pending keys + real checks.

Model self-test suite (`tests/model_selftest.py`) is prepared and
honestly NOT-RUN until serving: it needs MODEL_API_URL live, and its
generation/long-task sections need an owner-supplied
`--messages-file` (the suite authors no prompts).

Self-modification MECHANISM proven without a model call: the agent
created `text_counts` through its own 5-stage pipeline (4/4 tests),
dispatched it live (`words 11, chars 58, lines 2`), then edited its
own chat UI through its own shell tool (accent `#4f7cff` →
`#14b8a6` + keyboard focus ring). The model's autonomous
self-modification is honestly pending serving.
