# Agent-Ultra — Tunnel Pipeline

The full route from the model to the Railway app, with no Kaggle
sandbox anywhere in it. That is the point: Kaggle's sandbox must
never come between the model and the agent again.

## The route

```
Owner's VPS
  llama.cpp serves the model (base GGUF Q8_0 15.7 GB + verified
  LoRA adapter) on localhost, e.g. http://127.0.0.1:8080
        │
        ▼
  ngrok tunnel (owner runs: ngrok http 8080)
  → public https URL, e.g. https://xxxx.ngrok-free.app
        │
        ▼  (env var MODEL_API_URL on Railway)
Railway app (this repo, Dockerfile)
  agent_ultra/chat_server.py  — chat UI + AG-UI shape
  agent_ultra/model_client.py — health() + chat() via the tunnel
        │
        ▼
  Copies (waves/batches; head queues the rest)
  each copy: own workdir + own browser profile + tools
        │
        ├── Supabase (env SUPABASE_URL + SUPABASE_KEY)
        │    memories table: save_memory / recall_memories,
        │    any table: select / insert / update / delete.
        │    DDL note: PostgREST cannot run CREATE TABLE — run the
        │    SQL in the Supabase SQL editor (see
        │    supabase_client.MEMORIES_TABLE_SQL).
        │
        └── Google Drive (env OAuth refresh token / service account)
             the agent's 15 GB tool memory: tools it builds are
             uploaded, listed, and downloaded on demand.
```

## Why the model is NOT in the Railway container

The 14B Q8_0 GGUF is 15.70 GB and needs far more RAM than a small
Railway container provides. Putting it in the image would also make
deploys huge and slow. So the model serves on the owner's VPS
(where the weights already live) and the Railway app reaches it
through the ngrok tunnel. This matches the owner's own plan §17:
Kaggle + temporary tunnel is a temporary experiment; durable
serving belongs on the VPS.

## Kaggle is NOT in this route

Kaggle is used only where the owner explicitly orders training
(its own notebooks, its own quotas). Inference for the deployed
agent never goes through Kaggle's sandbox, so no Kaggle queue,
quota, or sandbox limit can stall the deployed agent.

## Railway env vars (set in the Railway dashboard, never in code)

| Variable | Purpose |
|---|---|
| `MODEL_API_URL` | ngrok https URL of the VPS llama.cpp server |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon/service key |
| `DRIVE_REFRESH_TOKEN` | Google OAuth refresh token (Drive) |
| `DRIVE_CLIENT_ID` | Google OAuth client id |
| `DRIVE_CLIENT_SECRET` | Google OAuth client secret |
| `DRIVE_TOOL_FOLDER_ID` | (optional) Drive folder for stored tools |
| `DRIVE_SERVICE_ACCOUNT_JSON` | (optional) path to service-account JSON, instead of OAuth |
| `AGENT_WORKDIR` | (optional) agent workdir root, default /app/work |

## Order of operations (owner's sequence)

1. Build (this repo, local) → verify with `tests/verify_deployment.py`.
2. Push to GitHub (needs git auth — pending the owner's approval).
3. Railway: connect the repo, deploy the Dockerfile service, set
   the env vars above, confirm `/health` answers.
4. Supabase: create the project + `memories` table (SQL editor),
   set the two env vars, confirm a real save + recall.
5. Drive: OAuth consent / service account, set env vars, confirm a
   real upload + list + download.
6. Model LAST via the tunnel: start llama.cpp on the VPS, start
   ngrok, set MODEL_API_URL, confirm model_client.health() = live
   and a real chat reply comes back through the tunnel.
7. Only then is the deployed agent "active" — an empty deploy with
   no model, no Supabase, and no Drive is NOT counted as working.

## Status honesty

- Tunnel + Railway files: REAL code, UNTESTED end-to-end here (no
  Docker, no Railway account, no VPS, no ngrok URL on this host).
- Supabase / Drive / Model clients: REAL code; on this host they
  report NOT CONFIGURED (no env vars set) — that is the honest
  result until the owner connects them.
- Shell tool: REAL (runs on this host in tests).
- Browser tools: REAL code; live Chromium is UNTESTED here (no
  Chromium binary, no Playwright package on this host).
