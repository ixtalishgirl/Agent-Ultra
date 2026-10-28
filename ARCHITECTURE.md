# Agent-Ultra — Architecture

Local scaffold for the owner's system: **1000 agent copies**, each with
its **own machine** and its **own real browser** that opens **inside
the chat**, live real screen, real websites, account login capable,
real live time, no guessing — plus **one HEAD agent** above all copies
that every copy reports to, and the model able to **use Kaggle**.

This document separates what is proven from what is not. Nothing here
claims a live test that was never run.

## 1. Proven pieces (taken from verified local work)

| Piece | Source (local path) | What is proven |
|---|---|---|
| Per-Bot machine + browser | `~/workspace/projects/OpenBot` | OpenBot's model: the supervisor gives each Bot its own container, its own `/workspace` volume, its own browser profile (real Chromium, its own logins). Any AG-UI endpoint can be a Bot; the server sends the turn to the Bot over AG-UI. |
| Copies + judge + elimination | `~/workspace/projects/arena-skill` | Arena: 100 sub-agents, each a different strategy card, pair off, attack/defend/revise, judge scores on a rubric, bracket 100 → 50 → 25 → 13 → 7 → 4 → 2 → 1. |
| Tools + pipelines | `~/workspace/agent-os` | 761 registered tools, 5-stage pipelines, dispatcher with schema validation. Verified on this host: `dispatcher.load()` → 761 tools. Tiers: 541 implemented + 220 external_attempt (real missing-dependency errors, never fake success). |
| Trained model adapter | `~/workspace/agent-os/training/adapter/` | LoRA adapter verified local: `adapter_model.safetensors` 275,341,720 bytes, sha256 `8b327d88…69bf96aa`, plus tokenizer + config. Base model GGUF Q8_0 (15.70 GB) verified local. |

## 2. NEW and UNTESTED (do not claim these work)

- **1000 simultaneous copies.** OpenBot itself does not verify 100
  simultaneous Bots. 1000 is an order of magnitude beyond anything
  verified. See §5 for the math.
- **Per-copy containers from this scaffold.** Docker is not installed
  on this host; the spawner records machines as local directories and
  marks the container path UNTESTED. No container has been launched
  from this code.
- **Live Chromium per copy.** No Chromium binary exists on this host.
  `BrowserProfile.launch()` refuses instead of faking a session. A
  real browser launch, login, and Kaggle navigation have never been
  run from this skeleton.
- **AG-UI compatibility with OpenBot.** The skeleton serves `/health`
  and a `/agui` shape, but no AG-UI event stream has been validated
  against a real OpenBot/CopilotKit server. Do not claim a Bot works
  in OpenBot until that handshake is tested live.
- **Model serving.** The adapter is verified as files, but it has
  never been served (llama.cpp) from this scaffold, and no copy has
  ever received a model reply through it.
- **Model judging quality.** The head's ranking is mechanical only
  (status + evidence count). A model judging solution quality is
  UNTESTED and needs owner-approved criteria first.
- **Kaggle use by copies.** Route is the per-copy real browser
  (login-capable), which is UNTESTED. No Kaggle account, token, or
  credential is stored in this scaffold. Which account copies may use
  is PENDING the owner's decision, and Kaggle quotas apply per
  account. Nothing here assumes the training account's quota.
- **In-chat browser display.** The Muse-style in-chat browser card is
  the target UX (AG-UI display in the chat middle). The panel +
  protocol now exist and are tested (§9): the panel is a section
  inside the chat view (not a popup, not a new window) and shows
  real AG-UI-shaped browser events. The live Chromium render inside
  it is still UNTESTED: no Chromium binary exists on this host, so
  the panel shows the honest refusal event instead of a fake screen.

## 3. Component map (this scaffold)

```
agent-ultra/
  config.yaml               placeholders only; prompt: null (see §6)
  agent_ultra/
    __init__.py             exports HeadAgent, CopyAgent, Spawner, ChatStore
    __main__.py             demo: python3 -m agent_ultra [--copies N]
    spawner.py              creates N copy dirs + profiles; machine record
    copy_agent.py           a copy: workspace + browser profile + work + report
    browser_profile.py      per-copy Chromium profile dir; launch() refuses (UNTESTED)
    head.py                 collects reports; mechanical Arena-style bracket
    report_protocol.py      Report schema + JSONL append/read
    dispatcher_bridge.py    real bridge to Agent OS dispatcher (761 tools)
                            + extra tools (calculator, weather, internet,
                              imagine, understand) via dispatch_extra()
    agui_server.py          /health + /agui shape (protocol UNTESTED)
    chat_store.py           file-backed chats; scoped per-chat delete
    chat_server.py          chat UI server: static UI + JSON API
    tools_extra.py          extra tools (see §10)
    ui/
      index.html            sidebar + messages + in-chat browser panel
      style.css             professional dark theme (real CSS)
      app.js                chat list, messages, per-row delete, panel
  chats/                    chat store (created on first run, gitignored
                            in spirit: local runtime data, not source)
  tests/smoke_test.py       runnable checks (see §7)
```

Data flow: spawner → copies (own workdir + browser profile) → each
copy works and appends a Report to `reports.jsonl` → head collects,
ranks mechanically, runs the elimination bracket → one winner. Copies
call Agent OS tools only through `dispatcher_bridge`, so the existing
pipeline + validation + tier behavior applies unchanged.

The model is deliberately NOT per copy. Copies share one model
service (to be served, UNTESTED); giving each of 1000 copies its own
14B model would need 1000 × ~15.7 GB and is not part of this design.

## 4. Report protocol

One JSON object per line in `reports.jsonl`: `copy_id`, `task_id`,
`status` (`ok` | `error` | `pending`), `summary`, `evidence`
(list of facts), `ts`. Reports carry facts only — no prompt content,
no invented results. A copy that cannot do something reports `error`
or `pending` with the reason, never a fake success.

## 5. Scaling math — 1000 copies (PLANNING ESTIMATES, not measurements)

Per-copy running container estimates (from known component sizes,
NOT measured here — no container has run from this scaffold):

- Chromium with a real profile: ~300–600 MB RAM
- Agent process (Python): ~100–200 MB RAM
- Container overhead: ~50–100 MB RAM
- Per-copy total: **~0.5–1.0 GB RAM, ~0.25–0.5 CPU, ~1–2 GB disk**

| Simultaneous copies | RAM | CPU | Disk |
|---|---|---|---|
| 10 | 5–10 GB | 2.5–5 cores | 10–20 GB |
| 50 | 25–50 GB | 12–25 cores | 50–100 GB |
| 100 | 50–100 GB | 25–50 cores | 100–200 GB |
| **1000** | **500 GB – 1 TB** | **250–500 cores** | **1–2 TB** |

Plain conclusion: **1000 simultaneous copies do not fit on one VPS.**
This host (7.9 GB RAM, 2 cores, no Docker, no Chromium) cannot run
even 10 live copies — the demo here proves dirs, profiles, reports,
and ranking only. Honest scaling paths, in order:

1. **Waves/batches (default):** run 10–50 copies at a time per host;
   the head queues the rest and runs the bracket across waves.
2. **Fleet:** spread copies across many hosts/containers; the head
   aggregates reports centrally. Needs real infrastructure work.
3. **Do not** claim 1000-simultaneous until a fleet test proves it.

## 6. Standing rules honored in this scaffold

- **No prompt content anywhere.** The owner forbids writing any
  prompt (for any model, agent, or document) without asking her first.
  `config.yaml` carries `prompt: null` with that note. No prompt
  files, templates, or strings exist in this scaffold. Prompts are
  PENDING her explicit ask.
- **No refusal rules, no sandbox limits, no isolation rules** added
  beyond what the owner specifies. Copies are not restricted by this
  scaffold; any policy belongs to the owner, not to this code.
- **No fabrication.** Every untested piece is marked UNTESTED in code,
  config, and this document. Failures are reported as errors, never
  as fake successes.

## 7. What runs vs what is untested (verified on this host)

RUNS (smoke test, `python3 tests/smoke_test.py`, ALL PASS):
- Spawner creates N copy dirs, each with `workspace/` + `browser-profile/` + `PROFILE.json`.
- Copies check the real dispatcher bridge (761 tools) and append reports to JSONL.
- Head collects, ranks, and runs the bracket to one winner.
- AG-UI skeleton answers `/health` with `agui_protocol: UNTESTED`.
- Calculator really computes (2+3*4=14) and refuses unsafe input
  (imports, names, division by zero come back as errors).
- Weather returns real Open-Meteo data (London: real temperature);
  internet fetch returns real page text (example.org).
- Internet search returns real results (DuckDuckGo HTML first;
  Wikipedia OpenSearch fallback when DDG bot-blocks this host —
  source is labelled on every result set).
- Imagine saves real image bytes from a no-key provider (48,338
  bytes in the smoke run) or reports the provider failure honestly.
- Understand returns real extractive key sentences for text; image
  understanding refuses (UNTESTED, needs a vision model).
- Per-chat delete removes only that chat (messages + linked copy dir
  inside the allowed base), keeps every other chat intact, refuses
  copy dirs outside the allowed base, and rejects path-traversal IDs.
- Chat UI files exist (sidebar, messages, in-chat browser panel,
  per-row delete button); the chat server API works end to end over
  HTTP (create, message, browser events, tools list, delete).

UNTESTED (marked as such in code): container launch, live Chromium
launch/login/navigation, AG-UI event stream vs real OpenBot, model
serving + model replies (the UI shows an honest notice instead of a
faked reply), quality judging, Kaggle use, 1000-simultaneous
execution.

## 8. Still missing before GitHub push

1. Git setup: `git init`, first commit, remote to the new repo, and
   authentication (no git auth is set up yet — push is pending).
2. A host with Docker + Chromium to test containers and live browsers.
3. Model serving (llama.cpp) so copies can get real model replies
   (the chat UI currently shows an honest "serving UNTESTED" notice
   instead of faking replies).
4. AG-UI event-stream validation against a real OpenBot server.
5. Owner decisions: prompt content (explicit ask required), which
   Kaggle account copies may use, and the 1000-copy execution mode
   (waves vs fleet).

## 9. Chat UI — professional, in-chat browser, per-chat delete

Run it: `python3 -m agent_ultra.chat_server --port 8000`, then open
`http://127.0.0.1:8000/`. Stdlib only, no build step, no framework.

- **Layout (real CSS, `ui/style.css`):** dark modern theme — sidebar
  with the chat list, main message area with bubbles, composer input.
  The store starts empty: no demo chats, no placeholder content, no
  lorem ipsum. The UI only ever shows chats and messages that were
  really created through the API.
- **In-chat browser panel (`ui/index.html` §browser-panel):** a
  section INSIDE the chat view, below the messages — not a popup,
  not a new window. Opening a URL posts AG-UI-shaped events
  (`browser.open_requested`, then `browser.opened` or
  `browser.open_failed`) into the chat's `browser_events.jsonl`, and
  the panel renders those events. On this host the live launch
  refuses (no Chromium binary), so the panel shows the UNTESTED
  refusal event with the profile path — never a fake screenshot.
  On a host with Chromium, the same panel is where the live view
  plugs in.
- **Per-chat delete (every row has its own ✕ button):** clicking a
  row's delete button calls `DELETE /api/chats/<id>`, which removes
  exactly that chat's directory (messages + meta + browser events)
  and, if the chat links a copy dir, that copy dir — but ONLY when
  it resolves inside the allowed copies base. Anything outside the
  bases is refused, never deleted (smoke-tested, including a
  path-traversal ID rejection). Deleting a chat never touches other
  chats, Agent OS files, or anything outside the agent-ultra workdirs.
- **Agent replies are not faked:** model serving is UNTESTED, so
  after a user message the UI shows a plain notice ("Model serving
  is UNTESTED — no agent reply is available yet") that is stored
  nowhere as an agent message.

## 10. Extra tools the agent knows (wired into the bridge)

`agent_ultra/tools_extra.py`, callable via
`dispatcher_bridge.dispatch_extra(name, args)` and listed via
`list_extra_tools()`. The UI's sidebar footer shows these chips with
their REAL / UNTESTED status, fetched live from `/api/tools`.

| Tool | Status | What is real |
|---|---|---|
| `calculator` | REAL | Safe `ast` arithmetic (no `eval`); 2+3*4=14, sqrt(16)=4; imports/names/zero-division → errors |
| `weather` | REAL | Open-Meteo, no key: geocode + current weather (smoke run: London, real temperature) |
| `internet_fetch` | REAL | Live page text, tags stripped (smoke run: example.org, real text) |
| `internet_search` | REAL | DuckDuckGo HTML first; Wikipedia OpenSearch fallback when DDG bot-blocks this host (HTTP 202 challenge page) — source labelled on every result set |
| `imagine` | REAL | No-key image provider (Pollinations); bytes checked to be a real image before saving (smoke run: 48,338 bytes); provider failure → error, never a fake file |
| `understand_text` | REAL | Extractive key sentences by word frequency, no model call |
| `understand_file` | REAL | Same, over a local text file |
| `understand_page` | REAL | Fetch a page, then understand its text |
| `understand_image` | UNTESTED | Needs a vision model; the 14B base is text-only, so it refuses instead of faking a description |

Search honesty note: from this host, DuckDuckGo (html + lite) and
Mojeek all answer with JS/bot challenge pages, so the primary search
route is currently unusable here even though the code is real. The
fallback (Wikipedia OpenSearch, official, no key) is what returned
real results in the smoke run, and the tool says so on every call.
On a host where DDG answers normally, the primary route is used and
labelled `duckduckgo-html`.

1. Git setup: `git init`, first commit, remote to the new repo, and
   authentication (no git auth is set up yet — push is pending).
2. A host with Docker + Chromium to test containers and live browsers.
3. Model serving (llama.cpp) so copies can get real model replies.
4. AG-UI event-stream validation against a real OpenBot server.
5. Owner decisions: prompt content (explicit ask required), which
   Kaggle account copies may use, and the 1000-copy execution mode
   (waves vs fleet).

## 9. Deployment — Railway (added 2026-10-28)

The repo is deployable as a Railway Dockerfile service:

- `Dockerfile` — python:3.12-slim, bash, Chromium system deps,
  `pip install playwright` + `playwright install --with-deps
  chromium`, entrypoint `python3 -m agent_ultra.chat_server --host
  0.0.0.0 --port $PORT`. The container IS the agent's own machine:
  full shell/python/bash/pip/playwright access inside it, scoped to
  the container workdir (`AGENT_WORKDIR`, default /app/work).
- `railway.toml` — Dockerfile builder, start command, `/health`
  healthcheck, restart ON_FAILURE.
- `.dockerignore` / `.gitignore` — exclude ALL secrets, `.env`
  files, credentials, workdirs, chats, browser profiles (profiles
  hold session cookies — never committed). The repo is PUBLIC; a
  leaked key would be catastrophic, so keys live in env only.
- `tests/verify_deployment.py` — prints REAL pass/fail per piece
  (docker build if docker exists, shell, tools, browser, Supabase,
  Drive, model tunnel, secret scan). Never a pass for unrun work.

Status: files are REAL, end-to-end deploy is UNTESTED here (no
Docker, no Railway account, no VPS, no ngrok URL on this host).
Push is pending git auth; Railway/Supabase/Drive sign-ins are
pending the owner's approvals at those steps.

## 10. Browser-control tools (added 2026-10-28)

`agent_ultra/browser_tools.py` — full Playwright action set wired
into `dispatcher_bridge` (`list_browser_tools` /
`dispatch_browser_action`), so copies can call them: goto/navigate,
click, dblclick, type, fill, press, scroll_down, scroll_up,
scroll_to, move, hover, drag, copy, paste, back, forward, reload,
screenshot, wait_for_selector, get_text, get_title, get_url,
select_option, check, uncheck, focus, evaluate.

Every action result carries measured milliseconds. SPEED DESIGN:
no artificial delays, no sleep-based waits; selector waits bounded
tight (default 2000 ms); navigation uses `domcontentloaded`, not
`networkidle`. TARGET: 1–2 s per action. HONEST LIMIT: that target
is per action — page load time is the site's + the network's, not
ours, and heavy pages or slow networks can exceed it; the measured
ms in each result shows that plainly. No timing is claimed that was
not measured. If Playwright/Chromium is absent, actions return an
honest PLAYWRIGHT-ABSENT / BROWSER-ABSENT error — never a fake
click or page state. Live Chromium actions are UNTESTED on this
host (no Chromium binary, no Playwright package here).

## 11. Google-logged-in primary profile (added 2026-10-28)

`browser_profile.GoogleProfile` — one persistent primary profile
(`profiles/primary-google`) whose Chromium cookies/storage hold the
OWNER'S OWN Google sign-in. Rules, enforced by design:

- The owner signs in HERSELF through the in-chat browser. This code
  never types, stores, or automates a Google login, and never stores
  her Google password anywhere.
- `GoogleProfile.status()` counts Google cookie rows in the
  profile's Cookies database (read-only; values are never read or
  printed) and reports signed_in_likely only when cookies exist.
  Anything unreadable is "unknown", never "signed in".
- Copies keep their OWN profiles. Google-dependent work explicitly
  opts into the primary profile. Per-copy Google sign-ins would
  each need the owner's own sign-in and are NOT automated — a
  deliberate limit, not a missing feature.
- Profile dirs are gitignored AND dockerignored: session cookies
  must never reach the PUBLIC repo or an image.

## 12. Tunnel pipeline (added 2026-10-28)

Full route in `TUNNEL.md`: VPS llama.cpp → ngrok tunnel →
MODEL_API_URL → Railway app → copies, with Supabase (memories +
tables) and Google Drive (15 GB tool memory) alongside. Kaggle's
sandbox is NOT in this route, by design — no Kaggle queue, quota,
or sandbox limit can stall the deployed agent. The 14B Q8_0 GGUF
(15.7 GB) cannot run inside a small Railway container, which is why
the model serves on the VPS and the Railway app reaches it through
the tunnel.

Env vars Railway needs (dashboard only, never in code):
MODEL_API_URL, SUPABASE_URL, SUPABASE_KEY, DRIVE_REFRESH_TOKEN,
DRIVE_CLIENT_ID, DRIVE_CLIENT_SECRET, DRIVE_TOOL_FOLDER_ID
(optional), DRIVE_SERVICE_ACCOUNT_JSON (optional alternative),
AGENT_WORKDIR (optional).

## 13. Supabase + Drive wired into the agent (added 2026-10-28)

`supabase_client.py` and `drive_client.py` are now callable through
the dispatcher bridge, like the extra and browser tools already were:

- `dispatcher_bridge.list_supabase_tools()` / `dispatch_supabase()`
  — 9 tools: status, select, insert, update, delete, save_memory,
  recall_memories, create_table (honest limit: PostgREST has no DDL;
  it tries the `exec_sql` RPC and otherwise errors with the manual SQL
  path — never a fake table), rpc.
- `dispatcher_bridge.list_drive_tools()` / `dispatch_drive()` — 4
  tools: status, list_tools, upload_tool, download_tool (the 15 GB
  tool memory; download defaults to the agent workdir `tools/`).
- `/api/tools` on the chat server now lists extra + supabase + drive
  + custom tools together.

Connection status on this host: NOT CONFIGURED for both (no
SUPABASE_URL/SUPABASE_KEY, no Drive credentials in env). The wiring
loads and dispatches honestly return NOT CONFIGURED — no Supabase
save and no Drive upload was faked. Real connections need the env
vars (Railway dashboard) plus a real save/recall check (Supabase)
and a real upload/list/download check (Drive), still pending.

## 14. Model self-test suite + self-modification mechanism (added 2026-10-28)

`tests/model_selftest.py` is PREPARED, not run as a model test: it
exits NOT-RUN (code 2) while MODEL_API_URL is unset or the tunnel is
unreachable, and it authors NO prompt content of its own — model
generation and long-task endurance sections run ONLY with an
owner-supplied `--messages-file` (otherwise PENDING-OWNER-INPUT).
Runnable sections (health, tool registries, dispatcher count,
browser registry, local-tool timing) are real whenever the model is
live. Until serving exists, no model result is claimed anywhere.

Self-modification, MECHANISM level — PROVEN on 2026-10-28 with no
model call (the agent's own pipeline drove it):

1. tool_create through the 5-stage pipeline
   (`agent_ultra/tool_pipeline.py`: intake → validated_call →
   execute → evidence → report). First attempt, name `text_stats`,
   was REFUSED at validated_call: it collides with an existing Agent
   OS tool — the collision check works. Second attempt, name
   `text_counts`, passed 4/4 declared tests and was registered with
   evidence (`agent_ultra/custom_tools/text_counts.py` 361 bytes,
   sha256 aff6e8c5…5199fb2, plus `text_counts.test_evidence.json`).
2. USE through the dispatcher: `dispatch_custom('text_counts',
   {'text': 'Agent Ultra builds its own tools\nand then uses them,
   live.'})` returned `{"status": "ok", "result": {"words": 11,
   "chars": 58, "lines": 2}}` — a real dispatch, real output.
3. SELF-EDIT through the agent's own shell tool
   (`shell_tool.run_python_file`, 61.5 ms, rc 0): the chat UI accent
   changed `--accent: #4f7cff` → `#14b8a6` and
   `--accent-hover: #6a8dff` → `#2dd4bf`, plus a small UX
   improvement — a keyboard `focus-visible` ring that follows the
   accent (accessibility, professional, nothing garish). Exact diff
   (from the agent's own `git diff`):
   ```diff
   -  --accent: #4f7cff;
   -  --accent-hover: #6a8dff;
   +  --accent: #14b8a6;
   +  --accent-hover: #2dd4bf;
   +
   +/* Keyboard focus visibility (accessibility): focus ring follows the accent. */
   +button:focus-visible, .chat-row:focus-visible, input:focus-visible {
   +  outline: 2px solid var(--accent);
   +  outline-offset: 2px;
   +}
   ```
   The chat server still serves the UI, and serves the updated CSS
   at `/style.css` (verified over HTTP in the smoke test).
4. The pipeline validates provenance + tests; it is NOT a sandbox —
   custom tools run in-process with the agent's own container
   privileges, like its own code. That limit is documented in
   `tool_pipeline.py`, not hidden.

What this proves: the self-modification MECHANISM (create → test →
register → use → self-edit) works end to end. What it does NOT
prove: the MODEL's autonomous self-modification — that needs the
model served via MODEL_API_URL, and is honestly PENDING. No model
call was made or faked for this test.

## 15. Still pending (updated 2026-10-28)

- GitHub push auth, then Railway sign-in + deploy (jpmorgan).
- Supabase project + `memories` table (SQL editor) + env vars +
  real save + recall check.
- Drive OAuth / service account + env vars + real upload + list +
  download check.
- Model serving on the VPS (llama.cpp) + ngrok tunnel +
  MODEL_API_URL + health + a real reply — then the model self-test
  suite runs for real, including generation and long-task endurance
  with owner-supplied test messages.
- Owner decisions (unchanged): prompt content (config.yaml
  `prompt: null` untouched — never written without her explicit
  ask), which Kaggle account copies may use, waves vs fleet.
