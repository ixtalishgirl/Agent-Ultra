# Agent-Ultra — Railway container.
# This container IS the agent's own machine (OpenBot-style per-copy
# machine): inside it the agent gets full shell/python/bash/pip/
# playwright access, scoped to the container's own workdir.
# The 14B model is NOT in this image (15.7 GB GGUF cannot run in a
# small Railway container) — the model serves on the owner's VPS and
# is reached via the ngrok tunnel (MODEL_API_URL). See TUNNEL.md.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# bash + Chromium system deps (Playwright needs these).
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
  && python -m playwright install --with-deps chromium

# App code only. Secrets, .env files, workdirs, profiles and chats
# are excluded by .dockerignore and must NEVER be baked into an image
# (this repo is PUBLIC).
COPY agent_ultra ./agent_ultra
COPY config.yaml ./

ENV PORT=8000 \
    AGENT_WORKDIR=/app/work

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health')"

CMD ["sh", "-c", "python3 -m agent_ultra.chat_server --host 0.0.0.0 --port ${PORT:-8000}"]
