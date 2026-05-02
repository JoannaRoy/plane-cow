# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""COW Session Scoring — Plane-flavored wrapper around ``agentcow.scoring``.

This package re-exports the generic scoring API from ``agentcow.scoring``
and adds Plane-specific defaults via :mod:`.plane_config`.

Example::

    from asgiref.sync import async_to_sync
    from plane.cow.recording.scoring import score_plane_sessions

    result = async_to_sync(score_plane_sessions)(
        ground_truth_session_id=recording.session_id,
        agent_session_id=agent.session_id,
    )
    result.scores["overall"]
"""

from __future__ import annotations

from agentcow.scoring import (
    ScoringResult,
    score_cow_sessions,
    score_sessions,
)

from .plane_config import (
    PLANE_EXCLUDED_TABLES,
    PLANE_IGNORED_FIELDS,
    score_plane_sessions,
)

__all__ = [
    "PLANE_EXCLUDED_TABLES",
    "PLANE_IGNORED_FIELDS",
    "ScoringResult",
    "score_cow_sessions",
    "score_plane_sessions",
    "score_sessions",
]
