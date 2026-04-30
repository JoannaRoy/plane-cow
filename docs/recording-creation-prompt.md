# Recording Creation Prompt (plane-cow)

Self-contained guide for subagents creating COW (Copy-on-Write) recordings on **plane-cow**, a project management tool. Recordings capture multi-step PM workflows as replayable traces used to evaluate AI agent performance against ground-truth.

For background and the operator-oriented version of this guide, see [recording-creation-guide.md](./recording-creation-guide.md). This file is meant to be handed to a subagent verbatim.

## Table of Contents

1. [Concepts](#concepts)
2. [Environment Setup](#environment-setup)
3. [Recording Lifecycle](#recording-lifecycle)
4. [Designing Good Recordings](#designing-good-recordings)
5. [Planning Workflow](#planning-workflow)
6. [REST Endpoint Reference](#rest-endpoint-reference)
7. [COW Headers Deep Dive](#cow-headers-deep-dive)
8. [Enum / Field Reference](#enum--field-reference)
9. [Existing Data Reference](#existing-data-reference)
10. [Examples](#examples)
11. [Gotchas and Common Mistakes](#gotchas-and-common-mistakes)

---

## Concepts

### What is a Recording?

A captured sequence of REST writes against Plane's `/api/v1/...` executed inside a COW session. Every staged row lands in `<table>_changes` shadow tables keyed by `(session_id, operation_id)` — base tables are never touched until a reviewer commits. That gives you:

- **Reproducible evaluation**: ground-truth recording and agent-under-test both run against the same base data.
- **Safe experimentation**: rollback is a discard, not a restore.
- **Dependency tracking**: each call gets a unique `x-operation-id` so the system knows which ops touched which rows.

### What Makes a Good Recording?

Recordings serve as **golden traces** — the captured REST writes are the deterministic ground truth; the **prompt** is what an agent receives and must interpret to arrive at that outcome.

### `name` vs `prompt` vs `tags`

A recording has three text-ish fields. Don't conflate them.

| Field    | Set via                                                           | What it's for                                                                                                                                                                                                                                                                             |
| -------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`   | `POST /api/cow/recordings/start/` or `PATCH .../recordings/<id>/` | Short human title for the recordings list (e.g. "Sprint Q3: move ready issues into cycle").                                                                                                                                                                                               |
| `prompt` | same                                                              | The exact request the agent-under-test will receive. **Write it the way a real PM / EM / dev lead would ask** — not a REST-shaped spec. The captured REST writes remain the ground truth; the prompt tests whether the agent can interpret a realistic PM ask and arrive at that outcome. |
| `tags`   | same (array)                                                      | Grouping key for batches (`revision2`, `sprint-setup`, `triage`, etc.).                                                                                                                                                                                                                   |

Unlike some other COW hosts, plane-cow's `start_recording` accepts `prompt` and `tags` directly — you do **not** need a separate update call. Still, populate `prompt` before stopping the recording so it's runnable end-to-end.

**Good recordings:**

- Manipulate **existing** entities (state transitions, label edits, cycle moves, assignee changes) — not just create from scratch.
- Use **criteria-based** instructions ("every issue labelled `bug` still in `In Review` after 7 days") that force discovery.
- Have **specific, verifiable outcomes** you can query and diff field-by-field.
- Contain **4–8 writes** across multiple entity types.
- Represent realistic PM workflows (sprint setup, triage, release prep, backlog grooming).

**Bad recordings:**

- Create new objects from scratch with arbitrary names — agent could "pass" by hallucinating.
- Use vague phrasing ("clean up the backlog") with no verifiable result.
- Single trivial PATCH on one work item.
- Read like REST signatures ("PATCH work-items.state=<uuid>") — that tests JSON-shape generation, not PM judgement.

### Recording Categories

| Category                  | Description                                                | Example                                                                        |
| ------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Criteria-based**        | Query, filter by criteria, then act                        | "Close every Backlog issue older than 90 days."                                |
| **Specific manipulation** | Update a filtered set of existing entities to exact values | "Add label 'bug' to every issue assigned to @alice and move them to 'Triage'." |
| **Mixed create + update** | Create new entities that reference existing ones           | "Create cycle 'Q3-2026' and move all Ready issues into it."                    |
| **State transition**      | Move a set of entities through lifecycle stages            | "Transition every issue in module 'Launch' from 'In Review' to 'Done'."        |

---

## Environment Setup

### Loading Config from `.env`

All scripts read config from `apps/agent/.env`, never hardcoded. At the top of any shell:

```bash
set -a; . apps/agent/.env; set +a
API="$PLANE_BASE_URL"                       # http://localhost:8000
SLUG="$PLANE_WORKSPACE_SLUG"                # workspace slug, e.g. something-nice
AUTH=(-H "X-Api-Key: $PLANE_API_TOKEN")     # auth on every call
```

This gives you:

- **`$API`** — base URL of the Plane API (default `http://localhost:8000`).
- **`$SLUG`** — the workspace slug (used in REST paths, e.g. `/api/v1/workspaces/$SLUG/...`).
- **`$AUTH`** — Personal Access Token header.

The workspace **UUID** (different from the slug) is sometimes needed in COW endpoints — query it with:

```bash
docker compose -f docker-compose-local.yml exec -T api python manage.py shell -c \
  "from plane.db.models import Workspace; print(Workspace.objects.get(slug='$SLUG').id)"
```

Save it as `WORKSPACE_ID`.

### Local Dev Stack

- **REST API**: `http://localhost:8000/api/v1/...`
- **COW API**: `http://localhost:8000/api/cow/...`
- **OpenAPI schema**: `http://localhost:8000/api/schema/` (drf-spectacular, gated by `ENABLE_DRF_SPECTACULAR=1`)
- **Web app**: `http://localhost:3000`
- **Auth**: `X-Api-Key` header on every call.

### Prerequisites

- API container is running with `ENABLE_COW=1` in its **process env** (verify: `docker compose -f docker-compose-local.yml exec api printenv ENABLE_COW`).
- A valid `PLANE_API_TOKEN` for a workspace member with **ADMIN or MEMBER** role on the target workspace (POST endpoints reject GUEST).
- `jq`, `python3`, `curl`.

If `GET /api/cow/status/` shows `enabled: true` but recordings still come back with `operation_ids: []`, the middleware isn't active — that means `ENABLE_COW` is in the file but not in the process env. Fix with `docker compose up -d api worker` (NOT `restart` — it doesn't re-read `env_file`).

---

## Recording Lifecycle

### Step 1: Start a Recording (with prompt + tags inline)

```bash
RESULT=$(curl -s -X POST "$API/api/cow/recordings/start/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "$(jq -n --arg n "Sprint Q3 Setup" \
                --arg p "It's Q3 planning. Find every issue currently in 'Ready' with priority high or urgent, and move them into a new cycle called 'Q3-2026' (Jul 1 – Sep 30). Anything in 'Ready' that's only medium priority can stay where it is." \
                --argjson t '["sprint-setup","q3-2026"]' \
                --arg w "$WORKSPACE_ID" \
                '{name:$n, prompt:$p, tags:$t, workspace_id:$w}')")
SESSION_ID=$(echo "$RESULT" | jq -r .session_id)
RECORDING_ID=$(echo "$RESULT" | jq -r .id)
```

`session_id` is the COW session — pass it as `x-agent-session-id` on every subsequent write.

### Step 2 (optional): Update name/prompt/tags later

```bash
curl -s -X PATCH "$API/api/cow/recordings/$SESSION_ID/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d '{"prompt":"...refined wording...","tags":["revision2"]}'
```

Patchable fields: `name`, `prompt`, `tags`. Use this if you ran the writes first and want to refine the prompt afterwards.

### Step 3: Execute REST Writes with COW Headers

Every write **must** include `x-agent-session-id` and a fresh `x-operation-id`:

```bash
OP=$(python3 -c "import uuid; print(uuid.uuid4())")
curl -s -X PATCH "$API/api/v1/workspaces/$SLUG/projects/$PID/work-items/$IID/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -H "x-agent-session-id: $SESSION_ID" \
  -H "x-operation-id: $OP" \
  -H "x-visible-operations: $PREV_OP1,$PREV_OP2" \
  -d "{\"state\":\"$TODO_STATE_ID\"}"
```

`x-visible-operations` is only needed when this call references something **created** in an earlier op of the same session — see [COW Headers Deep Dive](#cow-headers-deep-dive). Reads never take COW headers.

### Step 4: Stop the Recording

```bash
curl -s -X POST "$API/api/cow/recordings/stop/" \
  "${AUTH[@]}" -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION_ID\"}"
```

### Step 5: Verify

```bash
curl -s "$API/api/cow/recordings/$SESSION_ID/" "${AUTH[@]}" | jq '{name, prompt, tags, operation_ids, dirty_tables}'
```

Expect one `operation_id` per write. `dirty_tables` should cover every table you touched (e.g. `issues`, `cycle_issues`, `cycles`, `labels`, `issue_labels`). `api_tokens` showing up is **expected noise** — every authed call updates `api_tokens.last_used_at`. Ignore it.

If `operation_ids` is empty, the middleware didn't see your writes — check the gotchas section.

---

## Designing Good Recordings

### Principle 1: Evaluability

The captured REST writes are the ground truth — they must represent **exactly one correct set of actions** so scoring is well-defined. Ask: "Can I write a query that confirms whether the agent ended up in the same state?"

The **prompt** is the request the agent receives. It should sound like something a real PM / engineering manager / tech lead would actually send. Most users of this agent are project managers — match their vocabulary and detail level. A spec-shaped prompt isn't a useful eval: it tests REST translation, not PM judgement.

| Bad                                                                                                         | Good                                                                                                                                                              |
| ----------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vague: "Clean up the backlog"                                                                               | "We've got 90+ issues in Backlog and most are stale. Close anything older than 90 days that hasn't been touched, and add a `stale` label to anything 30–90 days." |
| Reads like a spec: "PATCH work-items SET state=<uuid> WHERE state=<uuid> AND priority IN ('high','urgent')" | "For our Q3 cycle, pull every Ready issue that's high or urgent priority into a new cycle 'Q3-2026'. Lower priority Ready stuff can stay put."                    |
| No clear target: "Improve assignment hygiene"                                                               | "Anything labelled `security` that's still unassigned — please put @alice on it and bump it to In Progress."                                                      |

### Principle 2: Manipulate Existing Data

The COW mechanism's value is that recording and agent see the **same base data**. A recording that only creates brand-new things doesn't leverage that — any random creation would "pass". Prefer:

- **Update** existing work items (state, priority, labels, assignees, target_date).
- **Move** issues between cycles or modules.
- **Transition** through lifecycle states.
- **Add/remove** labels and module/cycle memberships.
- **Create** new entities only when they reference existing ones (e.g., a new cycle that you immediately populate from existing issues).

### Principle 3: Criteria-Based Instructions

Best recordings give the agent a **rule** to interpret, not a list of IDs:

```
GOOD: "Find every issue in module 'Launch' currently in 'In Review' with no assignee.
       Assign them to @alice and move them to 'In Progress'."
       → Agent must list, filter, then PATCH each one.
       → Same data → same writes.

BAD:  "PATCH issue-A, issue-B, issue-C to In Progress with assignee Alice."
       → Trivial checklist, no discovery.
```

### Principle 4: Multi-Step, Realistic Workflows

Real PM workflows the agent should be able to handle:

- **Sprint planning**: create cycle → pull ready issues in → set targets.
- **Triage rotation**: filter by label/age → assign owners → set priorities.
- **Release prep**: find done-but-not-released → label → move to release module.
- **Backlog grooming**: bulk close, bulk relabel, bulk reprioritize by criteria.
- **Module reorg**: split / merge modules, move work items.

### Principle 5: 4–8 Writes Minimum

Single-PATCH recordings are too easy. Aim for 4–8 meaningful writes that span multiple entity types (e.g. work items + cycle membership + labels).

---

## Planning Workflow

**Before you write any recording, plan it.** This avoids wasted effort and produces evaluable specs.

### Step 1: Discover Live Data

The "Existing Data Reference" further down is just a snapshot — IDs and contents differ over time. Always query live:

```bash
# Projects
curl -s "$API/api/v1/workspaces/$SLUG/projects/" "${AUTH[@]}" | jq '.results[] | {id,name,identifier}'

# States (per project)
curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/states/" "${AUTH[@]}" | jq '.results // . | .[] | {id,name,group}'

# Labels, modules, cycles, members
curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/labels/" "${AUTH[@]}" | jq
curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/modules/" "${AUTH[@]}" | jq
curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/cycles/" "${AUTH[@]}" | jq
curl -s "$API/api/v1/workspaces/$SLUG/members/" "${AUTH[@]}" | jq

# Work items (with state, priority, assignees, labels)
curl -s "$API/api/v1/workspaces/$SLUG/projects/$PID/work-items/" "${AUTH[@]}" \
  | jq '.results[] | {id,name,state,priority,assignees,labels,module_ids,cycle_id}'
```

### Step 2: Identify Patterns

Look for:

- Issues stuck in non-terminal states without assignees.
- Stale Backlog issues (high `created_at` deltas).
- Modules / cycles that need population or rebalance.
- Labels with inconsistent state coverage.
- Mixed-priority groups in the same state.

### Step 3: Write the Plan

For each recording:

```markdown
### Recording N: "<short name>"

**Prompt** (exact text the agent will receive — realistic PM voice):
"...quoted prompt..."

**Tags:** ["...","..."]

**Expected writes:**

1. PATCH work-items/<id> body: {state: <Todo>}
2. PATCH work-items/<id> body: {assignees: [<alice>]}
3. POST cycles/<cycle>/cycle-issues body: {issues: [<id1>, <id2>]}
   ...

**Evaluable criteria:**

- Query work-items where state was Backlog at start → all should now be in Todo.
- Query cycle-issues for cycle X → should contain exactly {id1, id2, id3}.
```

### Step 4: Sanity-Check

- Is the prompt deterministic (same data → same correct writes)?
- Does it sound like a real PM? Read it aloud.
- Does it manipulate existing data?
- Mix of criteria-based vs specific-manipulation across the batch?
- Does the verifier query exist?

### Step 5: Run In Parallel

Spawn one subagent per recording. Each gets:

- The exact prompt (final wording).
- The expected writes with concrete IDs (resolved against live data).
- The verification query.
- Permission to call `start_recording → writes → stop_recording → GET recording detail` end-to-end.

---

## REST Endpoint Reference

Minimal surface for recordings. Every write takes `x-agent-session-id` + `x-operation-id` (and optionally `x-visible-operations`); reads take none.

### Workspaces (auxiliary)

```
GET /api/v1/workspaces/<slug>/                 (look up workspace UUID via Django shell instead — list is gated)
GET /api/v1/workspaces/<slug>/members/
```

### Projects

```
GET    /api/v1/workspaces/<slug>/projects/
POST   /api/v1/workspaces/<slug>/projects/         body: {name, identifier, network: 2}
GET    /api/v1/workspaces/<slug>/projects/<pid>/
PATCH  /api/v1/workspaces/<slug>/projects/<pid>/
DELETE /api/v1/workspaces/<slug>/projects/<pid>/
```

`identifier` must be 3–5 uppercase letters, unique in the workspace. `network: 2` = members-only. Modules and cycles are gated per project — set `module_view: true` and `cycle_view: true` via PATCH before creating modules or cycles.

### Work Items (issues)

```
GET    /api/v1/workspaces/<slug>/projects/<pid>/work-items/?state=<sid>&priority=<p>&assignee=<uid>&label=<lid>
POST   /api/v1/workspaces/<slug>/projects/<pid>/work-items/
GET    /api/v1/workspaces/<slug>/projects/<pid>/work-items/<iid>/
PATCH  /api/v1/workspaces/<slug>/projects/<pid>/work-items/<iid>/
DELETE /api/v1/workspaces/<slug>/projects/<pid>/work-items/<iid>/
```

PATCH body keys (only send what changes):

```
{ "name": "...",
  "description_html": "<p>...</p>",
  "state": "<state-uuid>",
  "priority": "none|low|medium|high|urgent",
  "assignees": ["<user-uuid>", ...],
  "labels": ["<label-uuid>", ...],
  "start_date": "YYYY-MM-DD",
  "target_date": "YYYY-MM-DD",
  "estimate_point": <int>,
  "parent": "<parent-uuid>" }
```

### Sub-resources on a work item

```
.../work-items/<iid>/links/
.../work-items/<iid>/comments/
.../work-items/<iid>/activities/   (read-only)
.../work-items/<iid>/attachments/
.../work-items/<iid>/relations/
```

### States

```
GET   /api/v1/workspaces/<slug>/projects/<pid>/states/
POST  /api/v1/workspaces/<slug>/projects/<pid>/states/      body: {name, color, group}
PATCH /api/v1/workspaces/<slug>/projects/<pid>/states/<sid>/
```

`group` ∈ `backlog | unstarted | started | completed | cancelled`.

### Labels

```
GET    /api/v1/workspaces/<slug>/projects/<pid>/labels/
POST   /api/v1/workspaces/<slug>/projects/<pid>/labels/     body: {name, color, parent?}
PATCH  /api/v1/workspaces/<slug>/projects/<pid>/labels/<lid>/
```

### Modules

```
GET   /api/v1/workspaces/<slug>/projects/<pid>/modules/
POST  /api/v1/workspaces/<slug>/projects/<pid>/modules/     body: {name, project, description?, lead?, members?, status?, start_date?, target_date?}
PATCH /api/v1/workspaces/<slug>/projects/<pid>/modules/<mid>/
POST  /api/v1/workspaces/<slug>/projects/<pid>/modules/<mid>/module-issues/    body: {issues: [<iid>, ...]}
DELETE /api/v1/workspaces/<slug>/projects/<pid>/modules/<mid>/module-issues/<iid>/
```

`status` ∈ `backlog | planned | in-progress | paused | completed | cancelled`. Create requires the project's `module_view` to be `true` and the body to include `project: <pid>`.

### Cycles

```
GET   /api/v1/workspaces/<slug>/projects/<pid>/cycles/
POST  /api/v1/workspaces/<slug>/projects/<pid>/cycles/      body: {name, start_date, end_date, project_id, description?}
PATCH /api/v1/workspaces/<slug>/projects/<pid>/cycles/<cid>/
POST  /api/v1/workspaces/<slug>/projects/<pid>/cycles/<cid>/cycle-issues/      body: {issues: [<iid>, ...]}
POST  /api/v1/workspaces/<slug>/projects/<pid>/cycles/<cid>/transfer-issues/   body: {new_cycle_id: "<cid2>"}
```

Create requires `project_id` (note the underscore — different from modules, which use `project`) and the project's `cycle_view` to be `true`.

### Recording / agent-session management (no COW headers)

```
POST   /api/cow/recordings/start/                 body: {name?, prompt?, tags?, workspace_id?}
POST   /api/cow/recordings/stop/                  body: {session_id}
GET    /api/cow/recordings/                       ?workspace_id=&tag=&active=1
GET    /api/cow/recordings/<session_id>/
PATCH  /api/cow/recordings/<session_id>/          body: {name?, prompt?, tags?}
DELETE /api/cow/recordings/<session_id>/

POST   /api/cow/agent-sessions/start/             body: {recording_id?, starting_prompt?, model?, workspace_id?}
POST   /api/cow/agent-sessions/finish/            body: {session_id, status: RUNNING|COMMITTED|DISCARDED|FAILED}
GET    /api/cow/agent-sessions/                   ?recording_id=&workspace_id=&status=
GET    /api/cow/agent-sessions/<session_id>/
DELETE /api/cow/agent-sessions/<session_id>/
```

### COW session management (no COW headers)

```
GET    /api/cow/status/
POST   /api/cow/commit/                           body: {session_id}
POST   /api/cow/operations/commit/                body: {session_id, operation_ids: [...]}
POST   /api/cow/operations/discard/               body: {session_id, operation_ids: [...]}
GET    /api/cow/sessions/<session_id>/operations/
```

The full schema is at `GET /api/schema/` (OpenAPI 3 YAML, ~500KB) when `ENABLE_DRF_SPECTACULAR=1`.

---

## COW Headers Deep Dive

### Required Headers

| Header                 | When                                                                   | Purpose                                                              |
| ---------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `x-agent-session-id`   | Every COW write                                                        | Scopes the write to a session — every staging row carries this id.   |
| `x-operation-id`       | Every COW write                                                        | Unique UUID per call. Enables dependency tracking + partial discard. |
| `x-visible-operations` | When the call references an entity created earlier in the same session | Comma-separated op-ids whose staged changes should be visible.       |

### When `x-visible-operations` is needed

**Needed** — the target entity was created by an earlier COW call in the same session:

```
Op1: POST .../cycles/                                  -> returns cycle_id "abc"  (staged)
Op2: POST .../cycles/abc/cycle-issues/ {issues:[...]}  -> MUST set x-visible-operations: <Op1>
```

Without it, the COW layer doesn't "see" cycle `abc` and the second call fails or stages garbage.

**Not needed** — the entity exists in base data:

```
Op1: PATCH .../work-items/<existing-id>/ {state: ...}
```

**Not needed** — independent writes:

```
Op1: PATCH .../work-items/A/ ...
Op2: PATCH .../work-items/B/ ...
```

### Generating UUIDs

```bash
python3 -c "import uuid; print(uuid.uuid4())"
```

---

## Enum / Field Reference

| Field                  | Values                                                                  |
| ---------------------- | ----------------------------------------------------------------------- |
| **work-item.priority** | `none`, `low`, `medium`, `high`, `urgent`                               |
| **state.group**        | `backlog`, `unstarted`, `started`, `completed`, `cancelled`             |
| **module.status**      | `backlog`, `planned`, `in-progress`, `paused`, `completed`, `cancelled` |
| **project.network**    | `0` (secret), `2` (members)                                             |
| **role**               | `5` (Guest), `15` (Member), `20` (Admin)                                |

`state.id` is a UUID — always look it up via `GET .../states/` rather than hardcoding by name. State _names_ (`Backlog`, `Todo`, `In Progress`, `Done`, `Cancelled`) are the default seed but customisable.

---

## Existing Data Reference

**Theme: Aperture Science Enrichment Center** — a fictional research facility. Use it like a real workspace, but lean into the theme when designing prompts (test chambers, neurotoxin systems, GLaDOS firmware, Companion Cube QA, etc.).

**Important:** This is a snapshot. UUIDs change if the project is re-seeded. Always verify with the live-discovery queries in [Step 1](#step-1-discover-live-data) before wiring concrete IDs into a recording plan.

### Workspace

| Field      | Value                                                             |
| ---------- | ----------------------------------------------------------------- |
| Slug       | `something-nice`                                                  |
| UUID       | `fba0c668-0016-4f86-93cd-b1754af1a6b9`                            |
| Admin user | `blub@trail-ml.com` (UUID `0971a50d-ad46-46f2-9859-4a8d10a8a778`) |

### Project

| Field                    | Value                                  |
| ------------------------ | -------------------------------------- |
| Name                     | Aperture Science Enrichment Center     |
| Identifier               | `APS`                                  |
| ID                       | `ef49b439-8f6d-4cb5-bbd8-7d34f30ef0c9` |
| Modules / cycles enabled | yes                                    |

### States (project: APS)

| ID                                     | Name        | Group     |
| -------------------------------------- | ----------- | --------- |
| `3f8243d1-c7be-4e4c-adbb-5617209200c7` | Backlog     | backlog   |
| `0e7088b5-fe57-4b6b-a4fe-5633527ab802` | Todo        | unstarted |
| `f0673d55-db22-485d-bb1e-da4ff9732559` | In Progress | started   |
| `d1988c09-4358-464d-9f1a-7f4c7020db65` | Done        | completed |
| `f0646802-5b69-428e-83c2-1ab09cb22f40` | Cancelled   | cancelled |

### Labels

| ID                                     | Name           | Color     |
| -------------------------------------- | -------------- | --------- |
| `227ad81b-3a3f-4de2-a73e-d10c65d9208f` | neurotoxin     | `#dc2626` |
| `e8465304-9e12-4f38-be9c-9072d4c691ba` | companion-cube | `#f97316` |
| `bc5c75c2-e24d-4d55-b2ed-f03a75ecf67e` | test-chamber   | `#2563eb` |
| `ffab1670-ad79-4720-b024-e61384b8afd4` | cake           | `#ec4899` |
| `eb37a9f3-a2e0-4979-940b-76e5d466ad8c` | security       | `#b91c1c` |
| `88b5327a-7d60-4855-aeb3-05fabf91bd56` | bug            | `#ef4444` |
| `cbfd6562-4df8-4950-8617-2f05fb4d1f74` | feature        | `#16a34a` |
| `e6a2ec91-b89e-49c0-a4c5-940be8c54c04` | science        | `#7c3aed` |
| `f8c2ff84-c9c6-4d41-9e0c-0a7248adb157` | blocker        | `#991b1b` |
| `64c9063b-9de0-4d48-8397-29ab2594d987` | stale          | `#9ca3af` |

### Modules

| ID                                     | Name                                  |
| -------------------------------------- | ------------------------------------- |
| `6ceb1d35-3132-4047-bdc1-20b055bc2b50` | Neurotoxin Generator v3               |
| `c89527bd-d0f4-4ece-859c-3576a9deb0cb` | Test Chamber 17 — Aerial Faith Plates |
| `41d790a3-b080-4eb0-94a0-f22519c0f8aa` | Portal Gun Calibration                |
| `771e0704-2e3a-4f66-94e7-0978aa37e571` | GLaDOS Voice Synthesis                |
| `5f705b78-bb01-4967-aa3b-e706e49339d3` | Companion Cube QA Pipeline            |

### Cycles

| ID                                     | Name                              | Range                   |
| -------------------------------------- | --------------------------------- | ----------------------- |
| `a17cf5dc-90c5-4364-a532-a43ef31fdab2` | Pre-Activation Sprint             | 2026-04-01 → 2026-06-30 |
| `f5711861-f13e-4bee-8469-354e2f54e9d2` | Post-GLaDOS Reactivation Recovery | 2026-07-01 → 2026-09-30 |

### Work Items (20 total)

**Backlog** (7):

| ID                                     | Name                                                           | Priority | Labels            |
| -------------------------------------- | -------------------------------------------------------------- | -------- | ----------------- |
| `84715c11-646e-45e3-920d-55cf4a5c2f8e` | Investigate why Test Chamber 17 keeps deleting itself          | medium   | bug, test-chamber |
| `7ad3e3ce-6edf-478f-ab36-c3ce14bcaffc` | Document procedure for handling escaped test subjects          | low      | security          |
| `5bf44348-4eca-4609-afe9-78639099e50e` | Add confetti to successful test completions                    | none     | feature, cake     |
| `beb9ee30-237a-481f-b325-dda773ecc3b1` | Refurbish damaged Companion Cubes from Test Chamber 14         | low      | companion-cube    |
| `245bd8ce-5944-4cf8-bdad-d002d01a7927` | Plan GLaDOS firmware v2.0 rollout                              | medium   | feature, science  |
| `5887a48b-eba7-4034-af84-76239c5671bd` | Fix turret targeting recalibration drift                       | high     | bug, security     |
| `5cd3c9cd-53b9-40da-9bfc-9c9af254f03c` | Replace 'The cake is a lie' graffiti with motivational posters | low      | cake              |

**Todo** (4):

| ID                                     | Name                                                       | Priority | Labels                  | Assignee |
| -------------------------------------- | ---------------------------------------------------------- | -------- | ----------------------- | -------- |
| `22969717-228b-4bf3-a85d-4a55d009bdbb` | Replace neurotoxin filters in main vents                   | high     | neurotoxin, blocker     | admin    |
| `135357ae-bafd-4a52-b735-336c9d3ac0c9` | Standardize portal placement signage in test chambers      | low      | test-chamber            | —        |
| `4c382958-4e5e-47a4-bfde-d1b2fe6d0f15` | Order more Aperture-branded coffee mugs for break room     | none     | —                       | —        |
| `3df5b22b-fcf5-486d-824b-9ae774b7534a` | Audit Companion Cube emotional-attachment incident reports | medium   | companion-cube, science | —        |

**In Progress** (4):

| ID                                     | Name                                                       | Priority | Labels       | Assignee |
| -------------------------------------- | ---------------------------------------------------------- | -------- | ------------ | -------- |
| `7cec15fb-eee8-42f8-b3bf-14f05854f524` | Neurotoxin Generator v3 pressure test                      | high     | neurotoxin   | admin    |
| `52b23e1a-feea-4141-8f3c-81063e42c9a4` | Calibrate Portal Gun aim assist for new test chambers      | medium   | feature      | —        |
| `c86fc635-b9ea-4137-bf03-77e5002abc14` | Investigate potato battery feasibility for emergency power | low      | science      | —        |
| `b84ca1e4-3e6d-49b1-867d-b0913a691b14` | Patch GLaDOS voice synthesis stutter at higher volumes     | urgent   | bug, blocker | admin    |

**Done** (3):

| ID                                     | Name                                                | Priority | Labels                  |
| -------------------------------------- | --------------------------------------------------- | -------- | ----------------------- |
| `769360fe-2c38-4d3d-aeed-52bfee1257ac` | Aerial Faith Plate prototype — initial deployment   | high     | test-chamber, feature   |
| `d4c21724-55e6-4e39-a5e1-dc7b898e80b5` | Companion Cube emotional attachment study (phase 1) | medium   | companion-cube, science |
| `624a5878-d47f-4fff-90ef-d3abd5012882` | Test Chamber 1-3 build-out and signage              | high     | test-chamber            |

**Cancelled** (2):

| ID                                     | Name                                       | Priority | Labels            |
| -------------------------------------- | ------------------------------------------ | -------- | ----------------- |
| `066dacd8-392b-4f71-97d0-f0c1a15d40fe` | Replace GLaDOS with friendlier AI          | urgent   | feature           |
| `b0979615-253e-4b63-a937-74490c49432d` | Promote 'Wheatley' to core-operations role | high     | security, blocker |

### Module / Cycle membership

| Module                                | Issues                                                                                      |
| ------------------------------------- | ------------------------------------------------------------------------------------------- |
| Neurotoxin Generator v3               | Neurotoxin pressure test (IP), Replace neurotoxin filters (TD)                              |
| Test Chamber 17 — Aerial Faith Plates | Investigate self-deletion (BL), Aerial Faith Plate prototype (DN), Standardize signage (TD) |
| Portal Gun Calibration                | Calibrate aim assist (IP)                                                                   |
| GLaDOS Voice Synthesis                | Patch stutter (IP), Plan firmware v2.0 (BL)                                                 |
| Companion Cube QA Pipeline            | Refurbish cubes (BL), Phase 1 study (DN), Audit incident reports (TD)                       |

| Cycle                             | Issues                                                                                                               |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Pre-Activation Sprint             | Neurotoxin pressure test (IP), Calibrate aim assist (IP), Patch GLaDOS stutter (IP), Potato battery feasibility (IP) |
| Post-GLaDOS Reactivation Recovery | Replace neurotoxin filters (TD), Plan firmware v2.0 (BL)                                                             |

### Suggested recording themes (work especially well with this dataset)

- **Triage**: "Anything labelled `bug` that's still in Backlog without an assignee — put @blub on it and bump it to Todo."
- **Sprint pull-in**: "Pull every high-priority Backlog issue into the Pre-Activation Sprint cycle."
- **Module hygiene**: "Move Done items out of every active module — they don't belong there anymore."
- **Mass relabel**: "Anything mentioning 'neurotoxin' in the title that doesn't already have the `neurotoxin` label — add it."
- **Stale cleanup**: "Add the `stale` label to every Backlog issue with priority `none` or `low` that nobody's touched."
- **Cycle reorg**: "Take everything still In Progress in the Pre-Activation Sprint cycle that's also in the GLaDOS Voice Synthesis module, and move it into the Post-GLaDOS cycle — voice work is slipping."

---

## Examples

### Example 1: Criteria-Based (Best Practice)

**Name:** "Sprint Q3 Setup: pull Ready high-priority into Q3-2026 cycle"

**Prompt** (set inline at start; realistic PM voice):

> "Q3 planning time. Spin up a new cycle called 'Q3-2026' running Jul 1 to Sep 30. Then pull every Ready issue with high or urgent priority into it. Lower priority Ready stuff stays where it is for now."

**Tags:** `["sprint-setup", "q3-2026"]`

**Why it's good:**

- Forces discovery (filter Ready × priority).
- Mixes CREATE (cycle) and UPDATE (cycle-issues membership) → exercises `x-visible-operations`.
- Verifiable: query cycle-issues for the new cycle, compare set membership.

**Expected flow:**

1. `POST .../cycles/` body `{name: "Q3-2026", start_date: "2026-07-01", end_date: "2026-09-30", project_id: <pid>}` → cycle_id `Op1`.
2. `POST .../cycles/<cycle_id>/cycle-issues/` body `{issues: [id_1, id_2, ...]}` with `x-visible-operations: <Op1>`.

**Evaluable criteria:**

- Query `cycles` for cycle named `Q3-2026` → must exist with the right dates.
- Query `cycle-issues` for that cycle → set must equal {issues that were Ready × (high|urgent) at session start}.

### Example 2: Specific Manipulation

**Name:** "Triage: assign security bugs to @alice"

**Prompt:**

> "Anything labelled `security` that's still unassigned — please throw @alice on it and bump it to In Progress."

**Tags:** `["triage", "security"]`

**Why it's good:**

- All targets are existing work items.
- Two-field update (assignees + state) per match.
- Filter is unambiguous.

**Expected flow** (per matching issue):

1. `PATCH .../work-items/<iid>/` body `{assignees: ["<alice-uuid>"]}` (no `x-visible-operations`).
2. `PATCH .../work-items/<iid>/` body `{state: "<in-progress-uuid>"}`.

(Or one PATCH with both fields — agent's choice as long as the final state is the same. The scorer compares end-state.)

### Example 3: Mixed Create + Update

**Name:** "Release 1.2 cleanup"

**Prompt:**

> "Create a label `released-1.2` (use a green colour). Anything in module `v1.2` currently Done should get that label. Then spin up a new module `v1.3` and move everything in `v1.2` that's still In Progress into it — they're slipping to next release."

**Tags:** `["release", "v1.2"]`

**Why it's good:**

- Creates new entities (label, module) that get referenced by subsequent ops → exercises `x-visible-operations` twice.
- Mixed updates on existing work items.
- Verifiable per-issue end-state.

**Expected flow:**

1. `POST .../labels/` body `{name: "released-1.2", color: "#22c55e"}` → label_id `Op1`.
2. `POST .../modules/` body `{name: "v1.3", project: <pid>}` → module_id `Op2`.
3. For each Done issue in v1.2: `PATCH .../work-items/<iid>/` body `{labels: [<existing_labels..>, <Op1_label_id>]}` with `x-visible-operations: <Op1>`.
4. For each In Progress issue in v1.2: `POST .../modules/<Op2_module_id>/module-issues/` body `{issues: [<iid>]}` with `x-visible-operations: <Op2>`, plus `DELETE .../modules/<v1.2-module-id>/module-issues/<iid>/` to remove from old module.

### Example 4: State Transition (Backlog Cleanup)

**Name:** "Backlog hygiene: stale-tag and close very old"

**Prompt:**

> "Our Backlog is bloated. Anything sitting there older than 90 days, just cancel it — we're never going to do it. Anything 30 to 90 days old, slap a `stale` label on so we can review next week."

**Tags:** `["grooming"]`

**Expected flow:**

1. List Backlog issues, partition by `created_at` age.
2. For each >90d issue: `PATCH .../work-items/<iid>/` body `{state: "<cancelled-uuid>"}`.
3. (If `stale` label doesn't exist) `POST .../labels/` body `{name: "stale", color: "#9ca3af"}` → `Op1`.
4. For each 30–90d issue: `PATCH .../work-items/<iid>/` body `{labels: [<existing_labels..>, <stale_label_id>]}` (with `x-visible-operations: <Op1>` only if the label was created in this session).

---

## Gotchas and Common Mistakes

1. **`docker compose restart` does NOT re-read `env_file`.** If you set `ENABLE_COW=1` or change the `.env`, recreate with `docker compose up -d api worker` or your writes go to real tables.
2. **`GET /api/cow/status/` lying.** It only reflects DB state, not whether the middleware is loaded in the API process. The only true test is: do a write with COW headers, then check `operation_ids` on the recording is non-empty.
3. **Header name typos.** Must be exactly `x-agent-session-id` and `x-operation-id` (case-insensitive but spelling matters). A typo silently falls through and writes hit real tables.
4. **Reusing `x-operation-id` within a session.** Always generate a fresh UUID per call. Reuse corrupts the dependency graph.
5. **`x-visible-operations` for base-data references.** Don't add it for entities that already exist — it's only for things created inside the current session.
6. **Reads with COW headers.** Don't put `x-agent-session-id` on GETs. The bypass logic gets confused and you can hit a 500.
7. **`/api/cow/*` paths bypass COW entirely.** Sending `x-agent-session-id` to `start_recording` does nothing useful.
8. **`workspace_slug` vs `workspace_id`.** Plane URLs use the slug (`PLANE_WORKSPACE_SLUG`). The recording row stores the workspace UUID. Pass the UUID as `workspace_id` to `start_recording`; pass the slug everywhere else. Don't put a URL in either.
9. **`Content-Type: application/json` is required** on every POST/PATCH. DRF returns 415 otherwise.
10. **Forgetting to stop the recording.** Active recordings have `ended_at = NULL`; list them with `GET /api/cow/recordings/?active=1`. Stop them or they linger.
11. **`api_tokens` in `dirty_tables`.** Every authed call updates `api_tokens.last_used_at` → ends up in `api_tokens_changes`. Harmless. Ignore it when auditing what the recording "did".
12. **State / label / module / cycle UUIDs are per-project**, not workspace-global. Always query inside the right project.
13. **Don't conflate `name` and `prompt`.** `name` is a short title for the operator-facing list; `prompt` is what the agent receives. Only `prompt` drives the agent run. Empty prompt = no useful agent run.
14. **Prompts should sound like a real PM, not a REST spec.** The agent's users are PMs / EMs / dev leads. Write prompts the way they'd actually ask ("pull the Ready high-priority stuff into a Q3 cycle"), not like a function signature ("PATCH state=<uuid> WHERE priority IN..."). Spec-shaped prompts test JSON generation, not realistic agent use.
15. **zsh quirk.** `zsh` doesn't word-split unquoted variables the way `bash` does. When iterating space-separated UUID lists in zsh, use explicit lists or `${=VAR}` to force split.
16. **Modules and cycles are project-gated.** A new project has them disabled by default — PATCH `module_view: true` and `cycle_view: true` first, or POSTs return `"<X> are not enabled for this project"`.
17. **Module create uses `project`; cycle create uses `project_id`.** Different field names for the same thing on adjacent endpoints. Easy to miss.
18. **POST creating a project requires ADMIN or MEMBER role on the workspace.** GUEST tokens get 403. Verify with: `docker compose exec api python manage.py shell -c "from plane.db.models import APIToken; print(APIToken.objects.get(token='<your-token>').user.workspacemember_set.values('role','workspace__slug'))"`.
