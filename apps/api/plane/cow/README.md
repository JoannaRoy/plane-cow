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

| Method | Path                                         | Body                                                     | Description                                                                             |
| ------ | -------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `GET`  | `/api/cow/status/`                           | —                                                        | Returns schema-wide COW status                                                          |
| `POST` | `/api/cow/commit/`                           | `{"session_id": "uuid"}`                                 | Commit every dirty table for the session                                                |
| `POST` | `/api/cow/operations/commit/`                | `{"session_id": "uuid", "operation_ids": ["uuid", ...]}` | Partial commit. If `operation_ids` is empty all operations in the session are committed |
| `POST` | `/api/cow/operations/discard/`               | `{"session_id": "uuid", "operation_ids": ["uuid", ...]}` | Discard specific operations                                                             |
| `GET`  | `/api/cow/sessions/<session_id>/operations/` | —                                                        | List operations and dirty tables for a session                                          |

The middleware bypasses these routes — committing must not itself be
staged as COW changes.

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

- Library: [`agent-cow-python/agentcow/postgres/core.py`](../../../agent-cow-python/agentcow/postgres/core.py)
- monotrail reference integration: [`monotrail/terra/terra/cow/`](../../../../monotrail/terra/terra/cow/)
