# Recording Creation Guide (plane-cow)

How to create a COW (Copy-on-Write) recording on top of Plane. A recording is a captured sequence of Plane REST writes executed inside a COW session — a replayable "ground-truth trace" that an agent-under-test is later asked to reproduce.

This is the plane-cow equivalent of `monotrail/docs/recording-creation-guide.md`, adapted for Plane's REST API (`/api/v1/...`), `X-Api-Key` auth, and Plane's data model (workspaces, projects, issues, modules, cycles, labels, states).

## Table of Contents

1. [Quick Start](#quick-start)
2. [Concepts](#concepts)
3. [Environment Setup](#environment-setup)
4. [Recording Lifecycle](#recording-lifecycle)
5. [COW Headers](#cow-headers)
6. [Designing Good Recordings](#designing-good-recordings)
7. [REST Reference](#rest-reference)
8. [Replaying a Recording](#replaying-a-recording)
9. [Examples](#examples)
10. [Troubleshooting](#troubleshooting)

---

## Quick Start

Assuming the local stack is already running (`docker compose -f docker-compose-local.yml up -d`) and the API container has `ENABLE_COW=1` (see [Environment Setup](#environment-setup)):

```bash
set -a; . apps/agent/.env; set +a
API="$PLANE_BASE_URL"
SLUG="$PLANE_WORKSPACE_SLUG"
AUTH=(-H "X-Api-Key: $PLANE_API_TOKEN")

# 1. Start a recording
SESSION_ID=$(curl -s -X POST "$API/api/cow/recordings/start/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"demo","prompt":"...","workspace_id":"'"$WORKSPACE_ID"'"}' \
  | jq -r .session_id)

# 2. Do writes with COW headers
OP=$(python3 -c "import uuid; print(uuid.uuid4())")
curl -s -X PATCH "$API/api/v1/workspaces/$SLUG/projects/$PID/work-items/$IID/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -H "x-agent-session-id: $SESSION_ID" \
  -H "x-operation-id: $OP" \
  -d '{"state":"'"$STATE_ID"'"}'

# 3. Stop and verify
curl -s -X POST "$API/api/cow/recordings/stop/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\"}"

curl -s "$API/api/cow/recordings/$SESSION_ID/" "${AUTH[@]}" | jq .
# -> should show non-empty operation_ids and dirty_tables
```

If `operation_ids` comes back empty, the middleware isn't active — see [Troubleshooting](#troubleshooting).

---

## Concepts

### What is a recording?

A captured sequence of Plane REST writes executed inside a COW session. All writes are staged in `<table>_changes` shadow tables keyed by `(session_id, operation_id)` — they never touch the primary tables until a reviewer commits. That gives you:

- **Reproducible evaluation**: the ground-truth recording and the agent-under-test both run against the same base data.
- **Safe experimentation**: rollback is a discard, not a restore.
- **Dependency tracking**: each call has a unique `x-operation-id`, and `agentcow.postgres.core` knows which ops touched which rows.

### Storage layout

- **`cow_recording_session`** (`plane.cow.models.CowRecordingSession`) — one row per recording: `session_id`, `name`, `prompt`, `tags`, `started_at`, `ended_at`.
- **`cow_agent_session`** (`plane.cow.models.CowAgentSession`) — one row per agent run, optionally linked to the recording it attempted to reproduce.
- **`<table>_changes`** — the staging tables, keyed by `(session_id, operation_id)`. This is where the trace actually lives.

There is **no** separate `cow_operation_log` table (unlike monotrail). To inspect a recording you join on `session_id`; the helpers

```
cow_lib.get_session_operations(session_id)  # -> list[UUID]
cow_lib.get_dirty_tables(session_id)        # -> list[str]
```

are implemented in [plane-cow/apps/api/plane/cow/adapter/cow_lib.py](../apps/api/plane/cow/adapter/cow_lib.py) and surfaced by `GET /api/cow/recordings/<session_id>/`.

---

## Environment Setup

### Config

Scripts should read config from `apps/agent/.env` rather than hardcoding. See [apps/agent/.env.example](../apps/agent/.env.example):

```bash
PLANE_BASE_URL=http://localhost:8000
PLANE_API_TOKEN=plane_api_...
PLANE_WORKSPACE_SLUG=my-workspace       # slug only, not a URL
```

Load it into the current shell with:

```bash
set -a; . apps/agent/.env; set +a
```

### Services

- **Plane API**: `http://localhost:8000/api/v1/...`
- **COW endpoints**: `http://localhost:8000/api/cow/...`
- **Agent chat** (optional, FastAPI in [apps/agent](../apps/agent)): `http://localhost:8765`
- **Auth**: `X-Api-Key: <token>` on every call — a Plane API key created via the Plane UI.

### Enabling COW

Two independent things have to be on:

1. **DB-side state** (`cow.enabled` flag + the per-table shadow functions), managed with:

   ```bash
   cd apps/api
   python manage.py cow_deploy_functions    # one-time per DB
   python manage.py cow_migrate             # disable -> migrate -> enable
   ```

2. **Process-side feature flag** — `ENABLE_COW=1` must be visible to the API (and worker) process. Without it the middleware does nothing and writes land in the real tables even when you send COW headers.
   - **Running Django directly**: `export ENABLE_COW=1` before starting.
   - **Docker Compose**: add `ENABLE_COW=1` to `apps/api/.env`, then **recreate** the container:
     ```bash
     docker compose -f docker-compose-local.yml up -d api worker
     ```
     `docker compose restart` does **not** re-read `env_file`. Verify with
     ```bash
     docker compose -f docker-compose-local.yml exec api printenv ENABLE_COW
     ```

> ⚠️ `GET /api/cow/status/` returning `"enabled": true` only reflects the DB-side state. It does **not** tell you whether the middleware is active. The only reliable check is to run a test write with COW headers and confirm `operation_ids` on the recording is non-empty.

See [apps/api/plane/cow/README.md](../apps/api/plane/cow/README.md) for background.

### Prerequisites

- Local `api` service on port 8000 with `ENABLE_COW=1` in its process env.
- `jq`, `python3`, `curl`.
- A valid `PLANE_API_TOKEN` with access to the target workspace.

---

## Recording Lifecycle

### 1. Start a recording

```bash
RESULT=$(curl -s -X POST "$API/api/cow/recordings/start/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"Sprint Q3 setup","prompt":"Move all Ready issues into a new Q3 cycle","workspace_id":"'"$WORKSPACE_ID"'"}')
SESSION_ID=$(echo "$RESULT" | jq -r .session_id)
RECORDING_ID=$(echo "$RESULT" | jq -r .id)
```

`session_id` is the COW session identifier — use it as `x-agent-session-id` on every subsequent write.

### 2. (Optional) Tag / update the recording

```bash
curl -s -X PATCH "$API/api/cow/recordings/$SESSION_ID/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"tags":["revision2","sprint-setup"]}'
```

Patchable fields: `name`, `prompt`, `tags`.

### 3. Execute REST writes with COW headers

Every write during the recording **must** include `x-agent-session-id` and a fresh `x-operation-id`:

```bash
OP_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
curl -s -X POST "$API/api/v1/workspaces/$SLUG/projects/$PROJECT_ID/work-items/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -H "x-agent-session-id: $SESSION_ID" \
  -H "x-operation-id: $OP_ID" \
  -H "x-visible-operations: $PREV_OP1,$PREV_OP2" \
  -d '{"name":"...","state":"'"$STATE_ID"'"}'
```

Add `x-visible-operations` only when this call depends on an entity created by an earlier COW call in the same session — see [COW Headers](#cow-headers). Reads never take COW headers.

### 4. Stop the recording

```bash
curl -s -X POST "$API/api/cow/recordings/stop/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\"}"
```

### 5. Verify

```bash
curl -s "$API/api/cow/recordings/$SESSION_ID/" "${AUTH[@]}" | jq .
```

The detail response includes `operation_ids` (from `cow_lib.get_session_operations`) and `dirty_tables` (from `cow_lib.get_dirty_tables`). Expect one `operation_id` per write and `dirty_tables` covering every table you touched. An empty `operation_ids` list means the middleware wasn't active — jump to [Troubleshooting](#troubleshooting).

You can also sanity-check isolation: read with no session header and confirm the real tables are unchanged.

---

## COW Headers

Three request headers drive the COW middleware. All UUIDs.

| Header                 | When                                                              | Purpose                                                         |
| ---------------------- | ----------------------------------------------------------------- | --------------------------------------------------------------- |
| `x-agent-session-id`   | Every COW write                                                   | Scopes writes to a session — all staging rows carry this id.    |
| `x-operation-id`       | Every COW write                                                   | Unique per call. Enables dependency tracking + partial discard. |
| `x-visible-operations` | When the call references an entity created earlier in the session | Comma-separated op ids. Reads see these ops + the base data.    |

### When `x-visible-operations` is needed

**Needed** — the target entity was created by a previous COW call in the same session:

```
Op1: POST .../cycles/                               -> returns cycle_id "abc"  (staged)
Op2: POST .../cycles/abc/cycle-issues/ body: {...}  -> MUST set x-visible-operations: <Op1>
```

Without it, the COW layer doesn't "see" cycle `abc` and the second call fails or stages garbage.

**Not needed** — the entity already exists in base data:

```
Op1: PATCH .../work-items/<existing-id>/ body: {...}
```

**Not needed** — independent writes with no dependency:

```
Op1: PATCH .../work-items/A/ ...
Op2: PATCH .../work-items/B/ ...
```

### Generating UUIDs

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

---

## Designing Good Recordings

Recordings serve as **golden traces** — the ground truth against which an agent's work is evaluated. For that to work, the `prompt` you store on the recording must produce a **deterministic, objectively verifiable outcome**.

### Principles

1. **Evaluability.** The prompt must lead to exactly one correct set of actions. Ask yourself: can I write a script that checks whether the agent did the right thing?
2. **Manipulate existing data.** COW's value is that recording and agent both see the same base data. A recording that only creates brand-new objects doesn't leverage that — any random creation would "pass". Prefer updates, moves, relabels, state transitions.
3. **Criteria-based instructions.** "Find every issue in module X still in state 'In Review'" forces discovery. "Close issues 123, 456, 789" is a checklist.
4. **Multi-step, realistic workflows.** Sprint setup, triage, backlog grooming, release prep — 4–8 writes across multiple entity types.

### Good vs bad prompts

| Bad (ambiguous)        | Good (deterministic)                                                                             |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| "Clean up the backlog" | "Close every issue in project X whose state is 'Backlog' and was created more than 90 days ago." |
| "Organize sprint work" | "Move every issue with label 'bug' currently in state 'Ready' into cycle 'Q3-2026'."             |
| "Assign some owners"   | "Assign issues matching label 'security' in project Y to user @alice."                           |

### Recording categories

| Category                  | Description                                                | Example                                                                                           |
| ------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Criteria-based**        | Query, filter by criteria, then act                        | "Close all issues in module X in 'In Progress' for more than 30 days."                            |
| **Specific manipulation** | Update a filtered set of existing entities to exact values | "Add label 'bug' to every issue assigned to @alice in project Y and move them to state 'Triage'." |
| **Mixed create + update** | Create new entities that reference existing ones           | "Create cycle 'Q3-2026' and move all Ready issues into it."                                       |
| **State transition**      | Move a set of entities through lifecycle stages            | "Transition every issue in module 'Launch' from 'In Review' to 'Done' and set completed_at."      |

### Planning workflow

Before executing a recording, write it down:

1. **Discover base data** with plain reads (no COW headers):

   ```bash
   curl -s "$API/api/v1/workspaces/$SLUG/projects/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/states/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/labels/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/modules/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/cycles/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/work-items/" "${AUTH[@]}" | jq .
   curl -s "$API/api/v1/workspaces/$SLUG/members/" "${AUTH[@]}" | jq .
   ```

2. **Document the recording**:

   ```markdown
   ### Recording N: "<name>"

   **Prompt (agent-facing):** "<exact text>"

   **Expected writes:**

   1. PATCH .../work-items/<id>/ body: {state: ...}
   2. PATCH .../work-items/<id>/ body: {labels: [...]}
      ...

   **Evaluable criteria:** <what to query and compare to verify correctness>
   ```

3. **Sanity-check** before running:
   - Is the prompt deterministic?
   - Can the outcome be verified programmatically?
   - Does it manipulate existing data (not just create from scratch)?
   - Good mix of criteria-based vs specific-manipulation across your recordings?

4. **Run in parallel** when creating many recordings — one subagent per recording, each receiving the plan above.

---

## REST Reference

Minimal surface for Plane recordings. Every write takes `x-agent-session-id` + `x-operation-id` (and optionally `x-visible-operations`); reads take none.

### Projects

```
GET    /api/v1/workspaces/<slug>/projects/
POST   /api/v1/workspaces/<slug>/projects/
GET    /api/v1/workspaces/<slug>/projects/<project_id>/
PATCH  /api/v1/workspaces/<slug>/projects/<project_id>/
DELETE /api/v1/workspaces/<slug>/projects/<project_id>/
```

Create body: `{"name": "...", "identifier": "ABC", "network": 2}`

### Work items (issues)

```
GET    /api/v1/workspaces/<slug>/projects/<project_id>/work-items/
POST   /api/v1/workspaces/<slug>/projects/<project_id>/work-items/
GET    /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<issue_id>/
PATCH  /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<issue_id>/
DELETE /api/v1/workspaces/<slug>/projects/<project_id>/work-items/<issue_id>/
```

Create body: `{"name": "...", "description_html": "...", "state": "<state_id>", "priority": "medium", "assignees": ["<user_id>"], "labels": ["<label_id>"]}`

### Modules

```
GET   /api/v1/workspaces/<slug>/projects/<project_id>/modules/
POST  /api/v1/workspaces/<slug>/projects/<project_id>/modules/
PATCH /api/v1/workspaces/<slug>/projects/<project_id>/modules/<module_id>/
POST  /api/v1/workspaces/<slug>/projects/<project_id>/modules/<module_id>/module-issues/
```

Add issues to a module: `{"issues": ["<issue_id>", ...]}`.

### Cycles

```
GET   /api/v1/workspaces/<slug>/projects/<project_id>/cycles/
POST  /api/v1/workspaces/<slug>/projects/<project_id>/cycles/
PATCH /api/v1/workspaces/<slug>/projects/<project_id>/cycles/<cycle_id>/
POST  /api/v1/workspaces/<slug>/projects/<project_id>/cycles/<cycle_id>/cycle-issues/
```

### Labels

```
GET    /api/v1/workspaces/<slug>/projects/<project_id>/labels/
POST   /api/v1/workspaces/<slug>/projects/<project_id>/labels/
PATCH  /api/v1/workspaces/<slug>/projects/<project_id>/labels/<label_id>/
```

### States

```
GET    /api/v1/workspaces/<slug>/projects/<project_id>/states/
POST   /api/v1/workspaces/<slug>/projects/<project_id>/states/
PATCH  /api/v1/workspaces/<slug>/projects/<project_id>/states/<state_id>/
```

### Recording / agent-session management (never take COW headers)

```
POST   /api/cow/recordings/start/          {name?, prompt?, tags?, workspace_id?}
POST   /api/cow/recordings/stop/           {session_id}
GET    /api/cow/recordings/                ?workspace_id=&tag=&active=1
GET    /api/cow/recordings/<session_id>/
PATCH  /api/cow/recordings/<session_id>/   {name?, prompt?, tags?}
DELETE /api/cow/recordings/<session_id>/

POST   /api/cow/agent-sessions/start/      {recording_id?, starting_prompt?, model?, workspace_id?}
POST   /api/cow/agent-sessions/finish/     {session_id, status: RUNNING|COMMITTED|DISCARDED|FAILED}
GET    /api/cow/agent-sessions/            ?recording_id=&workspace_id=&status=
GET    /api/cow/agent-sessions/<session_id>/
DELETE /api/cow/agent-sessions/<session_id>/
```

### COW session management (never take COW headers)

```
GET    /api/cow/status/
POST   /api/cow/commit/                    {session_id}
POST   /api/cow/operations/commit/         {session_id, operation_ids: [...]}
POST   /api/cow/operations/discard/        {session_id, operation_ids: [...]}
GET    /api/cow/sessions/<session_id>/operations/
```

---

## Replaying a Recording

Replay is a standalone script — [scripts/replay_recording.py](../scripts/replay_recording.py) — that leaves the `apps/agent` FastAPI app unchanged:

```bash
python scripts/replay_recording.py \
  --recording-session-id <uuid> \
  --model gpt-4o
```

Flow:

1. `GET /api/cow/recordings/<session_id>/` — pull the recording's `prompt`.
2. `POST /api/cow/agent-sessions/start/` with `{recording_id, starting_prompt, model}` — mints a **fresh** `session_id` distinct from the recording's.
3. `POST http://localhost:8765/chat` with `{model, session_id: <agent_session_id>, messages: [{role: "user", content: prompt}]}`. The agent's [plane_client.py](../apps/agent/plane_client.py) stamps `x-agent-session-id` on every Plane call.
4. `GET /api/cow/sessions/<agent_session_id>/operations/` — print the operation ids + dirty tables the agent staged.
5. Optional `--commit` / `--discard` forwards to `/api/cow/commit/` or `/api/cow/operations/discard/`.

The recording's staged ops and the agent's staged ops live in the same `*_changes` tables under different `session_id`s, so comparing them is a straightforward query (scoring is out of scope for this guide).

---

## Examples

### Example 1: Criteria-based (canonical)

**Name:** "Sprint Q3 Setup: move Ready issues into Q3 cycle"

**Prompt:**

> "Create a cycle named 'Q3-2026' on project Demo (start_date 2026-07-01, end_date 2026-09-30). Then find every issue in project Demo currently in state 'Ready' with priority 'high' or 'urgent', and move them into the new cycle."

Why it's good:

- Agent must query to discover matching issues (Ready state + priority filter).
- Criteria are unambiguous and verifiable (query cycle-issues after, compare sets).
- Exercises both CREATE (cycle) and UPDATE (cycle-issues) + `x-visible-operations`.

Expected flow:

1. `POST .../cycles/` — create "Q3-2026" → cycle_id, op_id = `Op1`.
2. `POST .../cycles/<cycle_id>/cycle-issues/` body `{issues: [id1, id2, ...]}` with `x-visible-operations: <Op1>`.

### Example 2: Specific manipulation

**Name:** "Triage: assign security bugs to @alice"

**Prompt:**

> "Find every work item in project Demo labeled 'security' and currently unassigned. Add @alice as an assignee and move them to state 'In Progress'."

Manipulates existing objects, every selector is a filter, multi-write across two fields per issue.

### Example 3: Mixed create + update

**Name:** "Release 1.2 cleanup"

**Prompt:**

> "On project Demo, create a label 'released-1.2' (color #22c55e). Then find every work item in module 'v1.2' currently in state 'Done' and add the new label. Finally, create a new module 'v1.3' and move any work item in state 'In Progress' from 'v1.2' into 'v1.3'."

Creates new entities that reference existing ones (exercises `x-visible-operations` twice), uses module-issues endpoints.

---

## Troubleshooting

### Recording comes back with `operation_ids: []`

The middleware didn't stage anything — writes went to real tables. Most common causes:

1. **`ENABLE_COW` not in the API process env.** `GET /api/cow/status/` can still return `enabled: true` (that's DB state). Verify the process:
   ```bash
   docker compose -f docker-compose-local.yml exec api printenv ENABLE_COW
   ```
   If blank, add `ENABLE_COW=1` to `apps/api/.env` and `docker compose up -d api worker` (not `restart`).
2. **Session header mistyped.** Must be exactly `x-agent-session-id`; a typo silently falls through.
3. **`x-operation-id` missing or reused** within the same session.
4. **Request hitting `/api/cow/*`** — that prefix is bypassed (see `bypass_prefixes` in [plane-cow/apps/api/plane/cow/middleware.py](../apps/api/plane/cow/middleware.py)).

### Gotchas

- **Reads never take COW headers.** Adding `x-agent-session-id` to GETs confuses bypass logic and can return 500.
- **`/api/cow/*` bypasses COW entirely.** Sending `x-agent-session-id` to `start_recording` does nothing useful.
- **Always generate a fresh UUID per operation.** Reusing `x-operation-id` corrupts the dependency graph.
- **`x-visible-operations` is only for entities staged in the current session.** Base-data references don't need it.
- **Workspace slug vs. UUID.** Plane URLs use the slug (`PLANE_WORKSPACE_SLUG`, e.g. `my-workspace`); the recording row stores the workspace UUID for join-friendliness. Don't put a URL in `PLANE_WORKSPACE_SLUG`.
- **`Content-Type: application/json` is required** on every POST/PATCH; DRF returns 415 otherwise.
- **Don't forget to stop the recording.** Unfinished recordings have `ended_at = NULL`; list them with `GET /api/cow/recordings/?active=1`.
- **No operation-log table.** Inspect a recording via `GET /api/cow/recordings/<session_id>/` — `operation_ids` and `dirty_tables` are derived on the fly from `*_changes`.
- **Recordings are never staged in COW.** `cow_recording_session` and `cow_agent_session` are in `COW_EXCLUDED_TABLES`, so their rows always hit the real table.
- **`api_tokens` in `dirty_tables` is expected noise.** Every authenticated API-key request updates `api_tokens.last_used_at`; with `ENABLE_COW=1` that update lands in `api_tokens_changes`. Harmless — ignore it when auditing what the recording "did".
- **zsh doesn't word-split unquoted variables** the way bash does. When iterating over a space-separated list of IDs in zsh, either list them explicitly (`for id in id1 id2 id3`) or use `${=VAR}` to force split.
