# Recording Creation Guide (plane-cow)

Complete guide for creating COW (Copy-on-Write) recordings on top of Plane. A recording captures a multi-step workflow as a replayable trace of REST calls that can later be fed to an AI agent for evaluation.

This is the plane-cow equivalent of `monotrail/docs/recording-creation-guide.md`, rewritten for Plane's REST API (`/api/v1/...`), `X-Api-Key` auth, and Plane's data model (workspaces, projects, issues, modules, cycles, labels, states).

## Table of Contents

1. [Concepts](#concepts)
2. [Environment Setup](#environment-setup)
3. [Recording Lifecycle](#recording-lifecycle)
4. [Designing Good Recordings](#designing-good-recordings)
5. [Planning Workflow](#planning-workflow)
6. [REST Reference](#rest-reference)
7. [COW Headers Deep Dive](#cow-headers-deep-dive)
8. [Replaying a Recording](#replaying-a-recording)
9. [Examples](#examples)
10. [Gotchas](#gotchas)

---

## Concepts

### What is a Recording?

A recording is a captured sequence of Plane REST calls executed within a COW session. The COW mechanism ensures all writes are isolated in `*_changes` shadow tables — they never touch the primary data until a reviewer commits them. This allows:

- **Reproducible evaluation**: an agent-under-test and the ground-truth recording both operate against identical copies of the same base data.
- **Safe experimentation**: all writes happen in a shadow; rolling back is a discard, not a restore.
- **Dependency tracking**: each call gets a unique `x-operation-id`, and `agentcow.postgres.core` tracks which operations depend on which rows.

### Storage layout

- **`cow_recording_session`** (Django model `plane.cow.models.CowRecordingSession`) — one row per recording, holds `session_id`, `name`, `prompt`, `tags`, `started_at`, `ended_at`.
- **`cow_agent_session`** (Django model `plane.cow.models.CowAgentSession`) — one row per agent run, optionally linked to a recording it attempted to reproduce.
- **`<table>_changes`** — agent-cow staging tables, keyed by `(session_id, operation_id)`. This is where the actual ground-truth trace lives; there is **no** separate `cow_operation_log` (unlike monotrail). To replay or inspect a recording you join on `session_id`.

This means the authoritative "what did the user/agent do" is always reconstructed via:

```
cow_lib.get_session_operations(session_id)  # -> list[UUID] of op_ids
cow_lib.get_dirty_tables(session_id)        # -> list[str] of tables touched
```

…both of which are already implemented in [plane-cow/apps/api/plane/cow/adapter/cow_lib.py](../apps/api/plane/cow/adapter/cow_lib.py) and exposed by `GET /api/cow/recordings/<session_id>/`.

### What Makes a Good Recording?

Recordings serve as **golden traces** — the ground truth against which an agent's work is evaluated. For this to work, the recording's `prompt` (what the agent-under-test will receive) must produce a **deterministic, objectively verifiable outcome**.

**Good recordings:**

- Manipulate **existing objects** (update state, re-assign, relabel, move into a module/cycle) — not just create from scratch.
- Use **criteria-based instructions** ("find all issues in project X assigned to user Y still in state 'Backlog', move them to state 'Ready'").
- Have **specific, verifiable outcomes** (you can query the result and compare field-by-field).
- Contain **4–8 REST calls** across multiple entity types.
- Represent realistic Plane workflows (sprint setup, backlog grooming, triage).

**Bad recordings:**

- Only create new issues from scratch (trivial; no COW advantage).
- Use vague prompts ("clean up the backlog").
- Have arbitrary mappings with no criteria ("move issue A to cycle B" without explaining why).

### Recording Categories

| Category                  | Description                                              | Example                                                                                          |
| ------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| **Criteria-based**        | Agent must query, filter by criteria, then act           | "Close all issues in module X that have been in 'In Progress' for more than 30 days"             |
| **Specific manipulation** | Agent updates specific existing entities to exact values | "Add label 'bug' to every issue assigned to @alice in project Y and move them to state 'Triage'" |
| **Mixed create + update** | Creates new entities AND links them to existing ones     | "Create cycle 'Q3-2026' and move all issues currently in state 'Ready' into it"                  |
| **State transition**      | Moves a set of entities through lifecycle stages         | "Transition every issue in module 'Launch' from 'In Review' to 'Done' and set completed_at"      |

---

## Environment Setup

### Loading Config from .env

Scripts and curl commands should read config from `apps/agent/.env` rather than hardcoding. See [apps/agent/.env.example](../apps/agent/.env.example):

```bash
PLANE_BASE_URL=http://localhost:8000
PLANE_API_TOKEN=plane_api_...
PLANE_WORKSPACE_SLUG=my-workspace
```

A shell session can load it with:

```bash
set -a; . apps/agent/.env; set +a
API="$PLANE_BASE_URL"
AUTH=(-H "X-Api-Key: $PLANE_API_TOKEN")
```

### Local Dev Server

- **API endpoint**: `http://localhost:8000/api/v1/...` (Plane REST API)
- **COW endpoints**: `http://localhost:8000/api/cow/...`
- **Agent chat app**: `http://localhost:8001` (FastAPI in [apps/agent](../apps/agent))
- **Auth**: `X-Api-Key: <token>` header on every call. The token is a Plane API key — create one via the Plane UI or settings CLI.
- **Config**: [apps/agent/.env](../apps/agent/.env) (gitignored, copy from `.env.example`).

### Enabling COW

Before recordings can stage writes to shadow tables, the COW machinery must be turned on for the process:

```bash
cd apps/api
python manage.py cow_deploy_functions    # one-time per DB
python manage.py cow_migrate             # runs disable -> migrate -> enable
export ENABLE_COW=1                      # flip the feature flag on the API process
```

See [apps/api/plane/cow/README.md](../apps/api/plane/cow/README.md) for background.

### Prerequisites

- Local `api` service running on port 8000 with `ENABLE_COW=1`.
- `jq` installed (for JSON parsing).
- `python3` available (for UUID generation).
- `curl` available.
- A valid `PLANE_API_TOKEN` with access to the target workspace.

---

## Recording Lifecycle

### Step 1: Start a Recording

```bash
RESULT=$(curl -s -X POST "$API/api/cow/recordings/start/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"name":"Sprint Q3 setup","prompt":"Move all Ready issues into a new Q3 cycle","workspace_id":"'"$WORKSPACE_ID"'"}')
SESSION_ID=$(echo "$RESULT" | jq -r .session_id)
RECORDING_ID=$(echo "$RESULT" | jq -r .id)
echo "Session: $SESSION_ID  Recording: $RECORDING_ID"
```

The `session_id` is the COW session identifier — use it as `x-agent-session-id` on every subsequent call.

### Step 2: Tag / update the recording (optional)

```bash
curl -s -X PATCH "$API/api/cow/recordings/$SESSION_ID/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"tags":["revision2","sprint-setup"]}'
```

Fields you can PATCH: `name`, `prompt`, `tags`.

### Step 3: Execute REST calls with COW headers

Every write during a recording **MUST** include:

```bash
OP_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
curl -s -X POST "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/work-items/" \
  "${AUTH[@]}" \
  -H "Content-Type: application/json" \
  -H "x-agent-session-id: $SESSION_ID" \
  -H "x-operation-id: $OP_ID" \
  -H "x-visible-operations: $PREV_OP1,$PREV_OP2" \
  -d '{"name":"...","state":"'"$STATE_ID"'"}'
```

See [COW Headers Deep Dive](#cow-headers-deep-dive) for when `x-visible-operations` is needed. Reads do **not** need COW headers — only writes.

### Step 4: Stop the recording

```bash
curl -s -X POST "$API/api/cow/recordings/stop/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\"}"
```

### Step 5: Verify

```bash
curl -s "$API/api/cow/recordings/$SESSION_ID/" "${AUTH[@]}" | jq .
```

The detail response includes `operation_ids` (from `cow_lib.get_session_operations`) and `dirty_tables` (from `cow_lib.get_dirty_tables`) — this is how you inspect a recording without a separate operation log.

---

## Designing Good Recordings

### Principle 1: Evaluability

The recording's `prompt` is what the agent-under-test will receive. It must lead to **exactly one correct set of actions**. Ask yourself: "Can I write a script that checks whether the agent did the right thing?"

| Bad (ambiguous)        | Good (deterministic)                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------------------------------- |
| "Clean up the backlog" | "Close every issue in project X whose state name is 'Backlog' and was created more than 90 days ago" |
| "Organize sprint work" | "Move every issue with label 'bug' currently in state 'Ready' into cycle 'Q3-2026'"                  |
| "Assign some owners"   | "Assign issues matching label 'security' in project Y to user @alice"                                |

### Principle 2: Manipulate Existing Data

The COW mechanism's value is that the recording and the agent both see the **same base data**. Recordings that only create new objects don't leverage this — any random creation would "pass". Instead:

- **Update** existing issues (state, priority, assignees, labels, target_date).
- **Move** issues into/out of modules and cycles.
- **Relabel** groups of issues matching a filter.
- **Create** new entities only when they reference existing ones (e.g. a new cycle that pulls existing issues into it).

### Principle 3: Criteria-Based Instructions

```
GOOD: "Find every issue in module 'Launch' still in state 'In Review'. Move each to state 'Done' and set completed_at = today."
      -> Agent must: query issues, filter, PATCH each
      -> Deterministic: same data = same result

BAD:  "Close issues 123, 456, 789."
      -> Trivial: just a checklist
      -> No discovery or reasoning required
```

### Principle 4: Multi-Step with Realistic Workflows

- **Sprint setup**: create cycle + move matching issues into it + tag them.
- **Triage**: find un-assigned high-priority issues + assign + relabel.
- **Backlog grooming**: archive stale + relabel live ones.
- **Release prep**: find issues in a module in state 'Done' + add label 'released' + set completed_at.

### Principle 5: 4–8 Writes Minimum

Each recording should contain 4–8 REST writes across multiple entity types. Not trivial single-field updates, but meaningful workflow actions that form a coherent story.

---

## Planning Workflow

**Before executing recordings, create a plan first.** This keeps the recordings well-designed and avoids wasted effort.

### Step 1: Discover Existing Data

All reads go through the standard Plane API (no COW headers needed):

```bash
# Workspaces (use the slug you already have)
# Projects
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/" "${AUTH[@]}" | jq .

# States (per project)
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/states/" "${AUTH[@]}" | jq .

# Labels (per project)
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/labels/" "${AUTH[@]}" | jq .

# Modules
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/modules/" "${AUTH[@]}" | jq .

# Cycles
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/cycles/" "${AUTH[@]}" | jq .

# Work items (issues)
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/projects/$PROJECT_ID/work-items/" "${AUTH[@]}" | jq .

# Workspace members (for assignees)
curl -s "$API/api/v1/workspaces/$PLANE_WORKSPACE_SLUG/members/" "${AUTH[@]}" | jq .
```

### Step 2: Identify Patterns for Criteria-Based Recordings

Look for:

- Work items with no assignee (need assignment).
- Work items in state 'Backlog' with high priority (need triage).
- Work items with a due date in the past that aren't done (need reschedule or close).
- Modules with no work items (need population).
- Cycles in the past with open work items (need migration).

### Step 3: Write the Recording Plan

For each recording, document:

```markdown
### Recording N: "Name"

**Description (prompt the agent will see):**
"Exact text of the criteria-based instruction..."

**Expected REST calls:**

1. PATCH .../work-items/<id>/ body: {state: ...}
2. PATCH .../work-items/<id>/ body: {labels: [...]}
   ...

**Evaluable criteria:** what to query and compare to verify correctness.
```

### Step 4: Review Before Executing

- Is each prompt deterministic?
- Can the expected outcome be verified programmatically?
- Do the recordings cover different entity types (issues, modules, cycles, labels, states)?
- Good mix of criteria-based and specific-manipulation?

### Step 5: Execute in Parallel

Spawn one subagent per recording. Each receives:

- The recording name and prompt.
- The expected REST calls with exact IDs and bodies.
- Instructions to tag the recording.

---

## REST Reference

Minimal surface for Plane recordings. Every write takes the three COW headers (`x-agent-session-id`, `x-operation-id`, optionally `x-visible-operations`); reads take none.

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

### Recording / Agent-session management (never take COW headers)

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

## COW Headers Deep Dive

### Required Headers

| Header                 | When                                     | Purpose                                                                                       |
| ---------------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------- |
| `x-agent-session-id`   | Every COW write                          | Identifies the COW session — all writes are scoped to it.                                     |
| `x-operation-id`       | Every COW write                          | Unique UUID for this specific call — used for dependency tracking and partial commit/discard. |
| `x-visible-operations` | When call B needs rows created by call A | Comma-separated UUIDs. Reads only see changes from these operations (plus base data).         |

### When is `x-visible-operations` Needed?

**Needed:** when a call references an entity created in a previous COW call within the same session.

```
Op1: POST .../cycles/ -> returns cycle id "abc"
Op2: POST .../cycles/abc/cycle-issues/ body: {issues: [...]}
     -> NEEDS x-visible-operations: <Op1-op-id>
     -> Otherwise, the COW layer doesn't see cycle "abc"
```

**Not needed** when referencing entities that already exist in base data:

```
Op1: PATCH .../work-items/existing-id/ body: {state: ...}
     -> No x-visible-operations needed
```

**Not needed** between independent writes:

```
Op1: PATCH .../work-items/A/ body: {priority: "high"}
Op2: PATCH .../work-items/B/ body: {priority: "high"}
     -> Independent, no dep
```

### Generating UUIDs

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

---

## Replaying a Recording

Replay is done with a standalone script — the `apps/agent` FastAPI app is unchanged:

```bash
python scripts/replay_recording.py \
  --recording-session-id <uuid> \
  --model gpt-4o
```

See [scripts/replay_recording.py](../scripts/replay_recording.py). The flow is:

1. `GET /api/cow/recordings/<session_id>/` — pull the recording's `prompt`.
2. `POST /api/cow/agent-sessions/start/` with `{recording_id, starting_prompt, model}` — mints a **fresh** `session_id` distinct from the recording's.
3. `POST http://localhost:8001/chat` with `{model, session_id: <agent_session_id>, messages: [{role: "user", content: prompt}]}` — the agent's existing [plane_client.py](../apps/agent/plane_client.py) stamps `x-agent-session-id` on every Plane call.
4. `GET /api/cow/sessions/<agent_session_id>/operations/` — print the operation ids + dirty tables the agent staged.
5. Optional `--commit` / `--discard` forwards to `/api/cow/commit/` or `/api/cow/operations/discard/`.

The recording's staged ops and the agent's staged ops live in the same `*_changes` tables but under different `session_id`s, so comparing them is a straightforward query (future work — this guide doesn't cover scoring).

---

## Examples

### Example 1: Criteria-Based (Best Practice)

**Name:** "Sprint Q3 Setup: move Ready issues into Q3 cycle"

**Description (agent prompt):**

> "Create a cycle named 'Q3-2026' on project Demo (start_date 2026-07-01, end_date 2026-09-30). Then find every issue in project Demo currently in the state named 'Ready' that has priority 'high' or 'urgent', and move them into the new cycle."

**Why this is good:**

- Agent must query to discover which issues match ('Ready' state id + priority filter).
- Criteria are unambiguous.
- Verifiable: query cycle-issues after and check the set.
- Uses both CREATE (cycle) and UPDATE (cycle-issues) — exercises `x-visible-operations`.

**Expected flow:**

1. POST `.../cycles/` — create "Q3-2026" -> cycle_id
2. POST `.../cycles/<cycle_id>/cycle-issues/` body `{issues: [id1, id2, ...]}` with `x-visible-operations: <op1>`

### Example 2: Specific Manipulation

**Name:** "Triage: assign security bugs to @alice"

**Description:**

> "Find every work item in project Demo labeled 'security' and currently unassigned. Add @alice as an assignee and move them to state 'In Progress'."

**Why this is good:**

- Manipulates existing objects (no creation).
- Every selector is a filter (label + assignees empty).
- Multi-write across two fields per issue.

### Example 3: Mixed Create + Update

**Name:** "Release 1.2 cleanup"

**Description:**

> "On project Demo, create a label 'released-1.2' (color #22c55e). Then find every work item in module 'v1.2' currently in state 'Done' and add the new label. Finally, create a new module 'v1.3' and move any work item in state 'In Progress' from 'v1.2' into 'v1.3'."

**Why this is good:**

- Creates new entities that reference existing ones.
- Uses module-issues endpoints.
- Multi-step with dependencies between the created label/module and the existing issues.

---

## Gotchas

1. **Reads never need COW headers** — only writes. Don't add `x-agent-session-id` on GETs or you'll confuse the middleware's bypass logic.
2. **`/api/cow/*` bypasses COW entirely.** See `bypass_prefixes = ("/api/cow/",)` in [plane-cow/apps/api/plane/cow/middleware.py](../apps/api/plane/cow/middleware.py). Sending `x-agent-session-id` to `start_recording` does nothing useful.
3. **`ENABLE_COW=1` must be set** on the API process; otherwise writes land in the real tables regardless of headers.
4. **Always generate a fresh UUID per operation.** Reusing `x-operation-id` within a session corrupts the dependency graph.
5. **`x-visible-operations` is only needed for entities staged in the current COW session.** Base-data references don't need it.
6. **Workspace slug vs. id.** Plane URLs use the slug (`PLANE_WORKSPACE_SLUG`); the recording row stores the workspace UUID for join-friendliness. They're different values — don't confuse them.
7. **Content-Type: application/json is required** for every POST/PATCH; DRF will otherwise return 415.
8. **Don't forget to stop the recording.** Unfinished recordings stay with `ended_at = NULL` — list them with `GET /api/cow/recordings/?active=1`.
9. **There is no operation log table.** If you need to inspect a recording, query `GET /api/cow/recordings/<session_id>/` — the detail response includes `operation_ids` and `dirty_tables` derived from `*_changes` on the fly.
10. **Recordings are never staged in COW.** `cow_recording_session` and `cow_agent_session` are listed in `COW_EXCLUDED_TABLES` so their rows always hit the real table.
11. **`api_tokens` in `dirty_tables` is expected noise.** Every authenticated API-key request updates `api_tokens.last_used_at`, and with `ENABLE_COW=1` that update lands in `api_tokens_changes` under the current session. You will see `api_tokens` listed next to the tables you actually meant to touch (e.g. `issues`, `issue_sequences`). It is harmless — commit/discard handles it like any other dirty table — but ignore it when auditing what the recording "did".
