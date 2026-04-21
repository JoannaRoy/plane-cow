# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
COW Session Scoring — Plane-flavored wrapper around ``agentcow.scoring``.

This package re-exports the generic scoring API from ``agentcow.scoring``
and layers on Plane-specific pieces:

* :data:`PLANE_EXCLUDED_TABLES` / :data:`PLANE_IGNORED_FIELDS` — Plane
  defaults for what to skip during scoring (control-plane tables, audit
  timestamps, etc.)
* :func:`build_plane_config` — assembles a :class:`ScoringConfig` with the
  above bundled in, plus the standard ``overall`` / ``precision`` /
  ``recall`` / ``f1`` reducers registered
* :func:`score_plane_sessions` — convenience DB-backed entry point using
  Plane's :class:`DjangoAsyncExecutor`

Example::

    from asgiref.sync import async_to_sync
    from plane.cow.scoring import score_plane_sessions

    result = async_to_sync(score_plane_sessions)(
        ground_truth_session_id=recording.session_id,
        agent_session_id=agent.session_id,
    )
    result.scores["overall"]
    result.feedback_report
"""

from __future__ import annotations

from agentcow.scoring import (
    CompositeComparator,
    CowGraph,
    CowNode,
    CowWrite,
    DatatypeComparator,
    EfficiencyResult,
    EntityComparison,
    EntityStateResult,
    Executor,
    ExtraWrite,
    FeedbackFn,
    FieldCategory,
    FieldComparisonResult,
    FieldConfig,
    MatchedWrite,
    MatchResult,
    MissingWrite,
    OpUtility,
    ScoredGraph,
    ScoredNode,
    ScoreFn,
    ScoringConfig,
    ScoringResult,
    SessionScoringTerms,
    WastefulPair,
    WriteComparator,
    WriteComparisonResult,
    build_field_config,
    collapse_to_final_state,
    compute_efficiency,
    compute_entity_state_score,
    compute_op_utilities,
    compute_operation_count_ratio,
    default_feedback_fn,
    default_score_fn,
    detect_wasteful_pairs,
    extract_session_graph,
    extract_session_writes,
    f1,
    find_best_match,
    flatten_graph,
    get_created_uuids,
    get_table_column_types,
    get_table_fk_columns,
    get_table_pk_columns,
    match_writes,
    precision,
    recall,
    score_cow_sessions,
    score_sessions,
    topological_sort_writes,
)

from .plane_config import (
    PLANE_EXCLUDED_TABLES,
    PLANE_IGNORED_FIELDS,
    build_plane_comparator,
    build_plane_config,
    score_plane_sessions,
)

__all__ = [
    "score_sessions",
    "score_cow_sessions",
    "score_plane_sessions",
    "ScoringResult",
    "build_field_config",
    "Executor",
    "extract_session_graph",
    "extract_session_writes",
    "get_table_pk_columns",
    "get_table_fk_columns",
    "get_table_column_types",
    "CowWrite",
    "CowNode",
    "CowGraph",
    "ScoredNode",
    "ScoredGraph",
    "OpUtility",
    "MatchedWrite",
    "MissingWrite",
    "ExtraWrite",
    "EntityComparison",
    "EntityStateResult",
    "EfficiencyResult",
    "WastefulPair",
    "SessionScoringTerms",
    "ScoringConfig",
    "ScoreFn",
    "FeedbackFn",
    "default_score_fn",
    "default_feedback_fn",
    "f1",
    "precision",
    "recall",
    "FieldCategory",
    "FieldConfig",
    "FieldComparisonResult",
    "WriteComparisonResult",
    "WriteComparator",
    "CompositeComparator",
    "DatatypeComparator",
    "MatchResult",
    "collapse_to_final_state",
    "get_created_uuids",
    "topological_sort_writes",
    "find_best_match",
    "match_writes",
    "compute_entity_state_score",
    "flatten_graph",
    "compute_op_utilities",
    "compute_efficiency",
    "compute_operation_count_ratio",
    "detect_wasteful_pairs",
    "PLANE_EXCLUDED_TABLES",
    "PLANE_IGNORED_FIELDS",
    "build_plane_comparator",
    "build_plane_config",
]
