# `plane.cow.adapter` — extraction candidate

This subpackage contains the **framework-generic** Django + Postgres glue
for the [`agent-cow`](https://github.com/...) library. Nothing in here
references plane models, plane settings, plane URL patterns, or plane
business logic — it's the same boilerplate any Django project would write
to adopt `agent-cow`.

It is isolated here so it can be lifted out verbatim (or nearly so) into
an upstream `agentcow.django` package when/if the library maintainer
decides to ship first-party framework adapters.

## What's inside

| Module           | Purpose                                                                                                                                                |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `context.py`     | `ContextVar` + HTTP-header parser for `x-agent-session-id` and friends.                                                                                |
| `executor.py`    | `DjangoAsyncExecutor` — adapts a Django DB connection to agent-cow's protocol.                                                                         |
| `cow_lib.py`     | Django-ORM-aware wrappers over `agentcow.postgres.core` (enable/disable/commit/...). Handles FK topo sort and PK discovery via `_meta`.                |
| `cow_session.py` | `apply_cow_variables_sync` — runs the `SET LOCAL` statements on a connection.                                                                          |
| `middleware.py`  | `BaseCowSessionMiddleware` + `CowExecuteWrapper` — request → COW session plumbing, with all app-specific bits exposed as overridable class attributes. |

## What's intentionally NOT in here

These live one directory up in `plane.cow` because they're plane-specific
(or Django forces them to live at that path):

- `apps.py` — `CowConfig(AppConfig)` with `name = "plane.cow"`.
- `middleware.py` — `CowSessionMiddleware` subclass that reads plane's
  `settings.ENABLE_COW` flag and skips `/api/cow/` URLs.
- `urls.py` / `views.py` — DRF commit/discard/status endpoints mounted at
  `/api/cow/`.
- `management/commands/cow_*.py` — thin `BaseCommand` subclasses that
  wrap the functions in `adapter/cow_lib.py`. Django's management-command
  loader only discovers commands at `<app>/management/commands/`, so
  they can't live inside this adapter subpackage. They're trivial argparse
  shims; when extracted upstream they'd be re-created inside
  `agentcow/django/management/commands/`.
- `README.md` — plane operator docs.

## How it would be extracted

1. Move `plane/cow/adapter/` → `agent-cow-python/agentcow/django/`.
2. Rewrite the intra-package imports (`plane.cow.adapter.*` →
   `agentcow.django.*`).
3. Re-create the `BaseCommand` subclasses inside
   `agentcow/django/management/commands/` (~80 lines of argparse
   boilerplate that calls `agentcow.django.cow_lib`).
4. Add `agentcow.django` to plane's `INSTALLED_APPS`; delete
   `plane/cow/management/commands/*.py` — Django will now discover the
   commands from the library.
5. Update `plane/cow/__init__.py` to re-export from `agentcow.django`
   (or drop the re-exports entirely).
6. Plane's `CowSessionMiddleware` subclass keeps subclassing
   `BaseCowSessionMiddleware` — just change the import.

Nothing inside this subpackage should need changes during that move.
