# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Plane-specific scoring configuration.

Holds the list of tables we never want to score (control-plane /
recording-infra tables) and the Plane-specific ignored fields (audit
timestamps, user FKs, soft-delete columns).

Also provides :func:`score_plane_sessions` — a convenience wrapper that
wires a :class:`DjangoAsyncExecutor` to :func:`score_cow_sessions`.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from agentcow.scoring import (
    ScoreFn,
    ScoringResult,
    default_score_fn,
    f1,
    precision as precision_fn,
    recall as recall_fn,
    score_cow_sessions,
)
from agentcow.scoring.types import CHANGE_TABLE_RESERVED_FIELDS

from agentcow.postgres.adapters.django.executor import DjangoAsyncExecutor


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

_DEFAULT_SCORE_FNS: dict[str, ScoreFn] = {
    "overall": default_score_fn,
    "precision": precision_fn,
    "recall": recall_fn,
    "f1": f1,
}


async def score_plane_sessions(
    ground_truth_session_id: UUID,
    agent_session_id: UUID,
    *,
    schema: str = "public",
    using: str = "default",
    score_fns: Optional[dict[str, ScoreFn]] = None,
    extra_ignored_fields: Optional[set[str]] = None,
    extra_excluded_tables: Optional[set[str]] = None,
) -> ScoringResult:
    """Score an agent session against a ground-truth recording."""
    excluded = set(PLANE_EXCLUDED_TABLES)
    if extra_excluded_tables:
        excluded.update(extra_excluded_tables)

    ignored = set(PLANE_IGNORED_FIELDS)
    if extra_ignored_fields:
        ignored.update(extra_ignored_fields)

    executor = DjangoAsyncExecutor(using=using)
    return await score_cow_sessions(
        executor=executor,
        ground_truth_session_id=ground_truth_session_id,
        agent_session_id=agent_session_id,
        schema=schema,
        score_fns=score_fns if score_fns is not None else _DEFAULT_SCORE_FNS,
        ignored_fields=ignored,
        excluded_tables=excluded,
    )
