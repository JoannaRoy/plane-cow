# Local Setup

## 1. Clone and run setup

```bash
git clone <repo-url>
cd plane-cow
./setup.sh
```

This copies all `.env.example` files, generates the Django `SECRET_KEY`, and installs Node dependencies.

## 2. Add API keys to the agent

Edit `apps/agent/.env`:

```bash
PLANE_BASE_URL=http://localhost:8000
PLANE_API_TOKEN=           # fill in after step 4
PLANE_WORKSPACE_SLUG=      # fill in after step 4

GEMINI_API_KEY=            # at minimum, add one LLM key
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
```

## 3. Start the backend stack

```bash
docker compose -f docker-compose-local.yml up -d
```

This starts Postgres, Redis, RabbitMQ, MinIO, the API (port 8000), the Celery worker, and the agent (port 8765). Database migrations run automatically via the `migrator` service on first start.

## 4. Start the frontend

In a separate terminal:

```bash
pnpm dev
```

This starts the web app (port 3000) and admin panel (port 3001).

## 5. Create a Plane account and workspace

1. Go to `http://localhost:3001/god-mode/` and register as the instance admin.
2. Go to `http://localhost:3000` and log in with the same credentials. Create a workspace.
3. Note the workspace slug from the URL (`http://localhost:3000/<slug>/...`).
4. Go to **Profile avatar → Settings → Personal Access Tokens → Add API token** and generate a token.
5. Copy both values into `apps/agent/.env`.

## 6. Enable COW

Add `ENABLE_COW=1` to `apps/api/.env`, then run the one-time COW setup:

```bash
docker compose -f docker-compose-local.yml exec api python manage.py cow_deploy_functions
docker compose -f docker-compose-local.yml exec api python manage.py cow_migrate
docker compose -f docker-compose-local.yml restart api
```

## 7. Create recordings

Follow `docs/recording-creation-guide.md`. The short version: use the agent chat at `http://localhost:8765` or curl to drive Plane through a workflow while a COW recording session is open. Each recording captures a multi-step sequence of REST writes as a replayable ground-truth trace.

## 8. Run agent sessions from recordings

```bash
docker compose -f docker-compose-local.yml exec api python manage.py run_recordings
```

This replays each recording's prompt through the agent and creates `CowAgentSession` rows. The staged operations are kept so they can be scored.

## 9. Score the sessions

```bash
docker compose -f docker-compose-local.yml exec api python manage.py eval_recordings
```

Outputs a `.csv` summary and a `.jsonl` with detailed feedback. See `docs/recording-scoring-guide.md` for filtering options and flags.
