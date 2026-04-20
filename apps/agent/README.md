# Plane COW Chat Agent

A small FastAPI + LiteLLM service that exposes a chat UI for driving Plane
through natural language. Every request it makes to Plane's REST API carries an
`x-agent-session-id` COW header, so writes stage in shadow tables until the
user explicitly commits or discards them.

## Layout

```
apps/agent/
  main.py            FastAPI app: GET /, POST /chat, POST /commit, POST /discard
  plane_client.py    httpx wrapper that adds X-Api-Key + x-agent-session-id + x-operation-id
  tools.py           One generic plane_request tool + OpenAPI schema fetcher
  llm.py             LiteLLM tool-calling loop (model picked per request)
  static/index.html  Vanilla-JS chat UI
  Dockerfile.dev     Image for docker-compose
  requirements.txt   Python deps
  .env.example       Config template
```

## Running under docker-compose (recommended)

The service is already wired into
[../docker-compose-local.yml](../docker-compose-local.yml) as the `agent`
service. Configure, then bring it up with the rest of the stack:

```bash
cp apps/agent/.env.example apps/agent/.env
# fill in PLANE_API_TOKEN, PLANE_WORKSPACE_SLUG, and at least one LLM key
docker compose -f docker-compose-local.yml up -d agent
```

Open http://localhost:8765.

The container uses `PLANE_BASE_URL=http://api:8000` (set via compose
`environment:`) so it talks to the API over the `dev_env` Docker network.

## Running locally (outside docker)

Useful for iterating without rebuilding containers.

```bash
cd apps/agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --port 8765 --reload
```

When running on the host, set `PLANE_BASE_URL=http://localhost:8000` in
`.env` (the default in `.env.example`).

## Getting a Plane API token

In Plane, go to **profile avatar -> Settings -> Profile -> API tokens** (direct
URL: `/settings/profile/api-tokens/`). Generate one; copy it into
`PLANE_API_TOKEN`. Your workspace slug is the path segment after the host in
Plane's URL (`http://localhost:3000/<slug>/...`).

## How a turn works

1. Browser mints `session_id = crypto.randomUUID()` on page load.
2. Each user message POSTs `{model, session_id, messages}` to `/chat`.
3. `llm.py` runs a LiteLLM tool-calling loop. The only tool needed for actions
   is `plane_request(method, path, body?, params?)`; the system prompt contains
   the `/api/v1/` endpoint catalog so the LLM knows what to call. A
   `get_api_schema` tool is available for drilling into the OpenAPI spec.
4. Every call from `plane_client.py` attaches:
   - `X-Api-Key: <token>`
   - `x-agent-session-id: <session_id>` — routes writes to shadow tables
   - `x-operation-id: <fresh uuid>` — marks this HTTP call as one COW operation
5. After each turn the server queries
   `GET /api/cow/sessions/<id>/operations/` and returns the pending-op count.
6. **Commit** -> `POST /api/cow/commit/` promotes staged changes.
   **Discard** -> `POST /api/cow/operations/discard/` throws them away.
   Either button also mints a fresh `session_id` for the next turn so the
   sandbox is clean.

## Model selection

The `model` field on each `/chat` request is passed straight through to
LiteLLM. Supported values include:

- `gemini/gemini-2.5-pro` (default; needs `GEMINI_API_KEY`)
- `anthropic/claude-sonnet-4-5`, `anthropic/claude-opus-4-5` (`ANTHROPIC_API_KEY`)
- `openai/gpt-5`, `openai/gpt-5-mini` (`OPENAI_API_KEY`)

Add more options by editing the `<select>` in `static/index.html`.

## Config

See `.env.example`:

```
PLANE_BASE_URL=http://localhost:8000      # http://api:8000 under compose
PLANE_API_TOKEN=
PLANE_WORKSPACE_SLUG=

ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
```

## Non-goals

- No persistent conversation storage; refresh clears the chat.
- No auth on the agent itself; it's a dev-side tool sitting behind the Plane
  API token.
- No streaming; one request/response per turn.
