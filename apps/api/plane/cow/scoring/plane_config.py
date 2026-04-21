# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Plane-specific scoring configuration.

Holds the list of tables we never want to score (control-plane /
recording-infra tables) and the Plane-specific ignored fields (audit
timestamps, user FKs, soft-delete columns).

Also provides :func:`score_plane_sessions` — a convenience wrapper that
wires a :class:`DjangoAsyncExecutor` to :func:`score_cow_sessions` so
callers don't have to hand-build an executor every time.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from agentcow.scoring import (
    CompositeComparator,
    ScoringConfig,
    ScoringResult,
    default_score_fn,
    f1,
    precision as precision_fn,
    recall as recall_fn,
    score_cow_sessions,
)
from agentcow.scoring.types import CHANGE_TABLE_RESERVED_FIELDS

from ..adapter.executor import DjangoAsyncExecutor


PLANE_EXCLUDED_TABLES: set[str] = {
    "cow_operation_log",
    "cow_recording_session",
    "cow_agent_session",
    "django_migrations",
    "django_content_type",
    "django_session",
    "django_site",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "django_celery_beat_periodictask",
    "django_celery_beat_periodictasks",
    "django_celery_beat_crontabschedule",
    "django_celery_beat_intervalschedule",
    "django_celery_beat_solarschedule",
    "django_celery_beat_clockedschedule",
    "django_celery_results_taskresult",
    "django_celery_results_chordcounter",
    "django_celery_results_groupresult",
}


PLANE_IGNORED_FIELDS: set[str] = {
    *CHANGE_TABLE_RESERVED_FIELDS,
    "created_at",
    "updated_at",
    "deleted_at",
    "created_by_id",
    "updated_by_id",
}


def build_plane_comparator() -> CompositeComparator:
    """Default Plane comparator.

    No per-table overrides today — the default :class:`DatatypeComparator`
    handles Plane's fuzzy-text (issue names/descriptions, module/cycle
    names) and exact-match (UUIDs, enums, dates) fields out of the box.
    Add per-table overrides here as scoring blind spots surface.
    """
    return CompositeComparator()


def build_plane_config(
    extra_excluded_tables: Optional[set[str]] = None,
    extra_ignored_fields: Optional[set[str]] = None,
) -> ScoringConfig:
    """Plane-flavored :class:`ScoringConfig`.

    Registers ``overall`` / ``precision`` / ``recall`` / ``f1`` as default
    ``score_fns`` so every eval caller gets them on ``result.scores``
    without having to opt in.
    """
    ignored = set(PLANE_IGNORED_FIELDS)
    if extra_ignored_fields:
        ignored.update(extra_ignored_fields)

    return ScoringConfig(
        comparator=build_plane_comparator(),
        ignored_fields=ignored,
        score_fns={
            "overall": default_score_fn,
            "precision": precision_fn,
            "recall": recall_fn,
            "f1": f1,
        },
    )


async def score_plane_sessions(
    ground_truth_session_id: UUID,
    agent_session_id: UUID,
    *,
    schema: str = "public",
    using: str = "default",
    config: Optional[ScoringConfig] = None,
    extra_excluded_tables: Optional[set[str]] = None,
) -> ScoringResult:
    """Score an agent session against a ground-truth recording.

    Thin wrapper over :func:`score_cow_sessions` that builds a
    :class:`DjangoAsyncExecutor` and injects Plane's default config +
    excluded tables.
    """
    excluded = set(PLANE_EXCLUDED_TABLES)
    if extra_excluded_tables:
        excluded.update(extra_excluded_tables)

    executor = DjangoAsyncExecutor(using=using)
    return await score_cow_sessions(
        executor=executor,
        ground_truth_session_id=ground_truth_session_id,
        agent_session_id=agent_session_id,
        schema=schema,
        config=config or build_plane_config(),
        excluded_tables=excluded,
    )
