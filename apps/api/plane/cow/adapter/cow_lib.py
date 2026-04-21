# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Django-ORM-aware COW helpers that wrap ``agentcow.postgres.core``.

All high-level helpers in this module are synchronous (Django is sync) and
use :func:`asgiref.sync.async_to_sync` to invoke the underlying async
``agentcow`` functions. The architecture mirrors ``terra.cow.cow_lib`` in
monotrail; the only difference is that models are introspected through
Django's app registry instead of SQLAlchemy's mapper registry.
"""

from __future__ import annotations

import collections
import logging
import uuid
from typing import Iterable, Optional, Type

from asgiref.sync import async_to_sync
from django.apps import apps
from django.db import transaction
from django.db.models import Model

import agentcow.postgres.core as cow_core

from plane.cow.adapter.executor import DjangoAsyncExecutor

logger = logging.getLogger(__name__)


COW_EXCLUDED_APPS: set[str] = {
    "auth",
    "contenttypes",
    "sessions",
    "admin",
    "django_celery_beat",
    "django_celery_results",
}

COW_EXCLUDED_TABLES: set[str] = {
    "cow_operation_log",
    "cow_recording_session",
    "cow_agent_session",
    "django_migrations",
    "django_content_type",
    "django_session",
    "django_site",
}


def cow_target_models(
    extra_excluded_apps: Optional[Iterable[str]] = None,
    extra_excluded_tables: Optional[Iterable[str]] = None,
) -> list[Type[Model]]:
    """Return the list of Django models that should have COW enabled."""
    excluded_apps = set(COW_EXCLUDED_APPS)
    if extra_excluded_apps:
        excluded_apps.update(extra_excluded_apps)

    excluded_tables = set(COW_EXCLUDED_TABLES)
    if extra_excluded_tables:
        excluded_tables.update(extra_excluded_tables)

    result: list[Type[Model]] = []
    for model in apps.get_models():
        meta = model._meta
        if meta.proxy or getattr(meta, "managed", True) is False:
            continue
        if meta.app_label in excluded_apps:
            continue
        if meta.db_table in excluded_tables:
            continue
        result.append(model)
    return result


def _get_pk_cols(model: Type[Model]) -> list[str]:
    pk_cols = [f.column for f in model._meta.get_fields() if getattr(f, "primary_key", False)]
    if not pk_cols:
        pk = model._meta.pk
        if pk is None:
            raise ValueError(f"Model {model.__name__} has no primary key defined")
        pk_cols = [pk.column]
    return pk_cols


def _topo_sort_models(models: list[Type[Model]]) -> list[Type[Model]]:
    """Topological sort of Django models by FK dependencies (parents first)."""
    dependencies: dict[Type[Model], set[Type[Model]]] = collections.defaultdict(set)
    model_set = set(models)

    for model in models:
        for field in model._meta.get_fields():
            target = getattr(field, "related_model", None)
            if target is None or target is model or target not in model_set:
                continue
            if not getattr(field, "concrete", False):
                continue
            if not (field.many_to_one or field.one_to_one):
                continue
            dependencies[model].add(target)

    sorted_models: list[Type[Model]] = []
    visited: set[Type[Model]] = set()
    temp_mark: set[Type[Model]] = set()

    def visit(n: Type[Model]) -> None:
        if n in temp_mark:
            return
        if n in visited:
            return
        temp_mark.add(n)
        for dep in dependencies[n]:
            visit(dep)
        temp_mark.remove(n)
        visited.add(n)
        sorted_models.append(n)

    for model in models:
        visit(model)
    return sorted_models


def _executor(using: str = "default") -> DjangoAsyncExecutor:
    return DjangoAsyncExecutor(using=using)


def deploy_cow_functions(using: str = "default") -> None:
    """Deploy the agent-cow PL/pgSQL helpers to the database."""
    async_to_sync(cow_core.deploy_cow_functions)(_executor(using))


def enable_cow_for_model(model: Type[Model], using: str = "default") -> None:
    """Enable COW on the table backing a single Django model."""
    table_name = model._meta.db_table
    pk_cols = _get_pk_cols(model)
    async_to_sync(cow_core.enable_cow)(_executor(using), table_name, pk_cols, "public")


def disable_cow_for_model(model: Type[Model], using: str = "default") -> None:
    """Disable COW on the table backing a single Django model."""
    table_name = model._meta.db_table
    async_to_sync(cow_core.disable_cow)(_executor(using), table_name, "public")


def enable_cow_for_all_models(
    extra_excluded_apps: Optional[Iterable[str]] = None,
    extra_excluded_tables: Optional[Iterable[str]] = None,
    using: str = "default",
) -> list[str]:
    """Enable COW on every eligible Django model in FK-topo order."""
    models = _topo_sort_models(cow_target_models(extra_excluded_apps, extra_excluded_tables))
    enabled: list[str] = []
    for model in models:
        enable_cow_for_model(model, using=using)
        enabled.append(model._meta.db_table)
        logger.info("COW enabled on %s", model._meta.db_table)
    return enabled


def disable_cow_for_all_models(
    extra_excluded_apps: Optional[Iterable[str]] = None,
    extra_excluded_tables: Optional[Iterable[str]] = None,
    using: str = "default",
) -> list[str]:
    """Disable COW on every eligible Django model (reverse FK-topo order)."""
    models = _topo_sort_models(cow_target_models(extra_excluded_apps, extra_excluded_tables))
    disabled: list[str] = []
    for model in reversed(models):
        disable_cow_for_model(model, using=using)
        disabled.append(model._meta.db_table)
        logger.info("COW disabled on %s", model._meta.db_table)
    return disabled


def get_cow_status(using: str = "default") -> dict:
    """Return the schema-wide COW status."""
    return dict(async_to_sync(cow_core.get_cow_status)(_executor(using), "public"))


def get_dirty_tables(session_id: uuid.UUID, using: str = "default") -> list[str]:
    return async_to_sync(cow_core.get_dirty_tables)(_executor(using), session_id, "public")


def get_session_operations(
    session_id: uuid.UUID, using: str = "default"
) -> list[uuid.UUID]:
    return async_to_sync(cow_core.get_session_operations)(
        _executor(using), session_id, "public"
    )


async def _commit_session_async(
    executor: DjangoAsyncExecutor,
    models: list[Type[Model]],
    session_id: uuid.UUID,
) -> list[str]:
    dirty = set(await cow_core.get_dirty_tables(executor, session_id, "public"))
    committed: list[str] = []
    async with cow_core.deferred_fk_constraints(executor):
        for model in models:
            table_name = model._meta.db_table
            if table_name not in dirty:
                continue
            await cow_core.commit_cow_session(
                executor, table_name, session_id, _get_pk_cols(model), "public"
            )
            committed.append(table_name)
    return committed


def commit_cow_session(session_id: uuid.UUID, using: str = "default") -> list[str]:
    """Commit every dirty COW-enabled table for a session in FK-topo order."""
    models = _topo_sort_models(cow_target_models())
    with transaction.atomic(using=using):
        return async_to_sync(_commit_session_async)(_executor(using), models, session_id)


async def _commit_operations_async(
    executor: DjangoAsyncExecutor,
    models: list[Type[Model]],
    session_id: uuid.UUID,
    operation_ids: list[uuid.UUID],
) -> list[str]:
    dirty = set(await cow_core.get_dirty_tables(executor, session_id, "public"))
    committed: list[str] = []
    async with cow_core.deferred_fk_constraints(executor):
        for model in models:
            table_name = model._meta.db_table
            if table_name not in dirty:
                continue
            await cow_core.commit_cow_operations(
                executor,
                table_name,
                session_id,
                operation_ids,
                _get_pk_cols(model),
                "public",
            )
            committed.append(table_name)
    return committed


def commit_cow_operations(
    session_id: uuid.UUID,
    operation_ids: list[uuid.UUID],
    using: str = "default",
) -> list[str]:
    """Commit specific operations within a COW session across all dirty tables."""
    if not operation_ids:
        return []
    models = _topo_sort_models(cow_target_models())
    with transaction.atomic(using=using):
        return async_to_sync(_commit_operations_async)(
            _executor(using), models, session_id, operation_ids
        )


async def _discard_operations_async(
    executor: DjangoAsyncExecutor,
    models: list[Type[Model]],
    session_id: uuid.UUID,
    operation_ids: list[uuid.UUID],
) -> list[str]:
    dirty = set(await cow_core.get_dirty_tables(executor, session_id, "public"))
    discarded: list[str] = []
    for model in models:
        table_name = model._meta.db_table
        if table_name not in dirty:
            continue
        await cow_core.discard_cow_operations(
            executor, table_name, session_id, operation_ids, "public"
        )
        discarded.append(table_name)
    return discarded


def discard_cow_operations(
    session_id: uuid.UUID,
    operation_ids: list[uuid.UUID],
    using: str = "default",
) -> list[str]:
    """Discard specific operations from a COW session across all dirty tables."""
    if not operation_ids:
        return []
    models = cow_target_models()
    with transaction.atomic(using=using):
        return async_to_sync(_discard_operations_async)(
            _executor(using), models, session_id, operation_ids
        )
