# plane.cow — Copy-On-Write integration

This Django app integrates [`agent-cow`](https://pypi.org/project/agent-cow/)
into Plane so that HTTP requests made on behalf of an AI agent write to
isolated `*_changes` shadow tables instead of the primary data. A reviewer
can later commit or discard those changes via the `/api/cow/` endpoints.

The framework-generic adapter layer (executor bridge, middleware base,
ORM-aware enable/disable/commit helpers) lives in
`agentcow.postgres.adapters.django` inside the library. Everything in this
package is Plane-specific configuration or domain logic built on top of it.

---

## What was added and why

The implementation is split into three categories by necessity.

### (a) `core/` — ~230 lines — required for any COW deployment

Everything needed for COW to function at runtime. Any Django + PostgreSQL
project adopting COW would need to replicate roughly this surface.

| File            | Purpose                                                                                                                                                                                                                                                                                                     | Required?              |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- |
| `middleware.py` | Subclasses `BaseCowSessionMiddleware`; reads `ENABLE_COW` env flag and sets `/api/cow/` as a bypass prefix so management endpoints are never themselves staged as COW changes                                                                                                                               | Yes                    |
| `excludes.py`   | Plane-specific table exclusion list (`device_sessions`) passed to the library's enable/disable helpers                                                                                                                                                                                                      | Yes                    |
| `core/views.py` | Five endpoints: `GET /status/`, `POST /commit/`, `POST /operations/commit/`, `POST /operations/discard/`, `GET /sessions/<id>/operations/`. The last one is the only endpoint a scoring harness strictly needs — it returns the operation UUIDs for a session so they can be passed to `score_cow_sessions` | Yes                    |
| `core/urls.py`  | URL patterns for the above                                                                                                                                                                                                                                                                                  | Yes                    |
| `models.py`     | `CowRecordingSession` and `CowAgentSession` Django models. Excluded from COW enablement so they are never shadowed. Traces (operation IDs, dirty tables) are reconstructed on demand by querying `*_changes` — there is no separate operation log                                                           | If using recording API |

### (b) `recording/` — ~400 lines — portable to the harness

Ground-truth and agent session tracking. These endpoints exist so Plane can
store recordings and agent runs in its own database. In a different deployment
the entire sub-package could be replaced by equivalent storage in the eval
harness — the only hard dependency on `core/` is the session-operations
endpoint used for scoring.

| File                                | Purpose                                                                                                                                                                                                                 | Required?                                  |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| `recording/views.py`                | CRUD for `CowRecordingSession` (start, stop, list, detail, patch, delete) and `CowAgentSession` (start, finish, list, detail, delete). Also serializes operation IDs and dirty tables into detail responses             | No — harness can track sessions externally |
| `recording/urls.py`                 | URL patterns for recordings and agent sessions                                                                                                                                                                          | No                                         |
| `recording/scoring/plane_config.py` | Plane-specific `PLANE_EXCLUDED_TABLES` and `PLANE_IGNORED_FIELDS` sets, and `score_plane_sessions` — a thin async wrapper that wires `DjangoAsyncExecutor` to `agentcow.scoring.score_cow_sessions` with those defaults | No — can live in harness                   |
| `recording/scoring/eval_io.py`      | `PairResult` dataclass bundling a recording and agent session with their `ScoringResult`; helpers for writing results to CSV and JSONL; per-operation structural and content utility deltas                             | No — can live in harness                   |

### (c) `management/commands/` — ~180 lines — deployment ops

Django management commands for standing up and maintaining COW in the
environment.

| Command                | Purpose                                                                                                                  | Required?           |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------- |
| `cow_deploy_functions` | Installs the agent-cow PL/pgSQL helpers into the database (one-time per DB)                                              | Yes, once           |
| `cow_enable`           | Enables COW on every eligible Plane table in FK-topological order                                                        | Yes, at deploy      |
| `cow_disable`          | Disables COW (reverse FK order). Used before schema migrations                                                           | Yes, at deploy      |
| `cow_migrate`          | Runs `cow_disable` → `manage.py migrate` → `cow_enable` so Django's schema editor sees plain tables instead of COW views | Yes, for migrations |
| `cow_status`           | Prints the schema-wide COW status (which tables are enabled)                                                             | No, diagnostic      |

---

## Line count summary

| Category                                        | Lines     | Portable to harness?      |
| ----------------------------------------------- | --------- | ------------------------- |
| (a) Core — runtime COW machinery                | ~250      | No — must live in the app |
| (b) Recording API — GT + agent session tracking | ~680      | Yes                       |
| (c) Deployment commands                         | ~180      | No                        |
| **Total**                                       | **~1110** |                           |

The library (`agentcow.postgres.adapters.django`) absorbs the remaining
~870 lines of framework-generic adapter code that any Django project would
otherwise have to write themselves.

---

## Setup

```bash
# 1. Install deps
pip install -r requirements/base.txt

# 2. Deploy PL/pgSQL helpers (once per DB)
python manage.py cow_deploy_functions

# 3. Enable COW on all Plane tables
python manage.py cow_enable

# 4. Verify
python manage.py cow_status

# 5. Activate the middleware
export ENABLE_COW=1
```

## Running migrations under COW

```bash
python manage.py cow_migrate
python manage.py cow_migrate -- app_label 0003  # forwards args to migrate
python manage.py cow_migrate --skip-enable      # leave COW off afterwards
```

## Header contract

| Header                 | Purpose                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| `x-agent-session-id`   | UUID identifying the COW session — required to activate COW          |
| `x-operation-id`       | UUID for the current operation (auto-generated if omitted)           |
| `x-visible-operations` | Comma-separated UUIDs — reads only see changes from these operations |

When `x-agent-session-id` is absent the middleware is a no-op.
