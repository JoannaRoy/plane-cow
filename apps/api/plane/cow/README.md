# plane.cow — Copy-On-Write for agent sessions

This Django app integrates [`agent-cow`](https://pypi.org/project/agent-cow/)
into plane so that HTTP requests made on behalf of an AI agent can write to
isolated `*_changes` tables instead of the primary data. Reviewers commit
or discard those changes later via the `/api/cow/*` endpoints.

The architecture mirrors monotrail's `terra.cow` module. Plane is sync
Django + psycopg 3, so the adapter wraps a Django cursor via
`asgiref.sync.sync_to_async` and admin calls use `async_to_sync`.

## Feature flag

Nothing activates until `ENABLE_COW=1` is exported in the process
environment. With the flag unset, the middleware is a no-op and the
endpoints are still mounted but operate on the live schema (so
`cow_status` returns `enabled=False`).

## Header contract

The middleware reads three headers from every inbound request:

| Header                 | Purpose                                                                       |
| ---------------------- | ----------------------------------------------------------------------------- |
| `x-agent-session-id`   | UUID that identifies the agent's COW session (required to activate COW)       |
| `x-operation-id`       | UUID for the current operation. Auto-generated if omitted                     |
| `x-visible-operations` | Comma-separated UUIDs. When set, reads only see changes from these operations |

When `x-agent-session-id` is absent, the middleware passes the request
through unchanged.

## Endpoints

All endpoints require authentication. They live under `/api/cow/`.

### Session management

| Method | Path                                         | Body                                                     | Description                                                                             |
| ------ | -------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `GET`  | `/api/cow/status/`                           | —                                                        | Returns schema-wide COW status                                                          |
| `POST` | `/api/cow/commit/`                           | `{"session_id": "uuid"}`                                 | Commit every dirty table for the session                                                |
| `POST` | `/api/cow/operations/commit/`                | `{"session_id": "uuid", "operation_ids": ["uuid", ...]}` | Partial commit. If `operation_ids` is empty all operations in the session are committed |
| `POST` | `/api/cow/operations/discard/`               | `{"session_id": "uuid", "operation_ids": ["uuid", ...]}` | Discard specific operations                                                             |
| `GET`  | `/api/cow/sessions/<session_id>/operations/` | —                                                        | List operations and dirty tables for a session                                          |

### Recordings (user-demonstrated workflows)

| Method   | Path                                | Body                                     | Description                                                            |
| -------- | ----------------------------------- | ---------------------------------------- | ---------------------------------------------------------------------- |
| `POST`   | `/api/cow/recordings/start/`        | `{name?, prompt?, tags?, workspace_id?}` | Create a recording and mint a `session_id` for the COW headers         |
| `POST`   | `/api/cow/recordings/stop/`         | `{session_id}`                           | Set `ended_at`                                                         |
| `GET`    | `/api/cow/recordings/`              | — (query `?workspace_id=&tag=&active=1`) | List                                                                   |
| `GET`    | `/api/cow/recordings/<session_id>/` | —                                        | Detail + derived `operation_ids` / `dirty_tables` from the `*_changes` |
| `PATCH`  | `/api/cow/recordings/<session_id>/` | `{name?, prompt?, tags?}`                | Update metadata                                                        |
| `DELETE` | `/api/cow/recordings/<session_id>/` | —                                        | Soft-delete the recording row (staged changes are untouched)           |

### Agent sessions (one row per agent run)

| Method   | Path                                    | Body                                                          | Description                                       |
| -------- | --------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------- |
| `POST`   | `/api/cow/agent-sessions/start/`        | `{recording_id?, starting_prompt?, model?, workspace_id?}`    | Mint a fresh `session_id` for an agent replay     |
| `POST`   | `/api/cow/agent-sessions/finish/`       | `{session_id, status: RUNNING\|COMMITTED\|DISCARDED\|FAILED}` | Mark the run done and set `ended_at`              |
| `GET`    | `/api/cow/agent-sessions/`              | — (query `?recording_id=&workspace_id=&status=`)              | List                                              |
| `GET`    | `/api/cow/agent-sessions/<session_id>/` | —                                                             | Detail + derived `operation_ids` / `dirty_tables` |
| `DELETE` | `/api/cow/agent-sessions/<session_id>/` | —                                                             | Soft-delete the agent-session row                 |

The middleware bypasses all `/api/cow/*` routes — committing and recording
management must not themselves be staged as COW changes.

Recording / agent-session rows live in the `cow_recording_session` and
`cow_agent_session` tables, which are in `COW_EXCLUDED_TABLES` so they are
never shadowed. Traces are reconstructed on demand by joining `session_id`
against the `*_changes` tables via `cow_lib.get_session_operations` and
`cow_lib.get_dirty_tables` — there is deliberately no separate
`cow_operation_log` (unlike monotrail). See
[../../../../docs/recording-creation-guide.md](../../../../docs/recording-creation-guide.md)
for the full workflow.

## Initial setup

1. Install the new dep:

   ```bash
   pip install -r requirements/base.txt
   ```

2. Deploy the COW PL/pgSQL helpers (one-time per DB):

   ```bash
   python manage.py cow_deploy_functions
   ```

3. Enable COW on every plane app table:

   ```bash
   python manage.py cow_enable
   ```

4. Verify:

   ```bash
   python manage.py cow_status
   ```

5. Flip the feature flag for the app process:

   ```bash
   export ENABLE_COW=1
   ```

## Running migrations under COW

Django's schema editor cannot operate on COW views. Use the bundled
wrapper so migrations target the underlying `*_base` tables:

```bash
python manage.py cow_migrate                   # equivalent of `migrate`
python manage.py cow_migrate -- app_label 0003 # forwards args to migrate
python manage.py cow_migrate --skip-enable     # leave COW off afterwards
```

The wrapper runs `cow_disable` → `migrate` → `cow_enable`. Because
`cow_enable` is idempotent, it is safe to re-run after the migration.

For deeper migration safety (DDL rewriting per statement) see the
monotrail RFC at
`monotrail/documentation/plans_rfcs/cow_migration_rewriter.md`.

## Excluded tables

`plane.cow.cow_lib.cow_target_models` walks the Django app registry and
returns every concrete, managed model whose app is not in:

- `auth`, `contenttypes`, `sessions`, `admin`
- `django_celery_beat`, `django_celery_results`

and whose `db_table` is not one of the COW bookkeeping tables
(`cow_operation_log`, `cow_recording_session`). Extend either set via
`--exclude-app` / `--exclude-table` on the management commands.

## How it works (per-request)

1. `CowSessionMiddleware.__call__` parses the three COW headers into a
   `CowPostgresConfig`.
2. It binds the config to the `trail_cow_ctx` ContextVar so any server
   code (background helpers, serializers, etc.) can see it.
3. It opens `transaction.atomic(using="default")` and registers a
   `connection.execute_wrapper` that emits `SET LOCAL app.session_id =
...` (and the related vars) at the start of every new transaction.
   Django reuses connections across requests, so per-transaction
   re-emit is necessary — same reason monotrail re-issues them in an
   SQLAlchemy `after_begin` listener.
4. The view runs; all writes land in `*_changes` and reads go through
   the COW view that merges base + changes.
5. If the view raises, `transaction.atomic` rolls back — the pending
   change rows disappear with it.

## Related code

- Library: [`agent-cow` on PyPI](https://pypi.org/project/agent-cow/) (`agentcow.postgres.core`)
- monotrail reference integration: [`monotrail/terra/terra/cow/`](../../../../monotrail/terra/terra/cow/)
