# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.cow.views import (
    AgentSessionDetailView,
    AgentSessionListView,
    CommitCowOperationsView,
    CommitCowSessionView,
    CowStatusView,
    DiscardCowOperationsView,
    FinishAgentSessionView,
    RecordingDetailView,
    RecordingListView,
    SessionGraphView,
    SessionOperationsView,
    StartAgentSessionView,
    StartRecordingView,
    StopRecordingView,
)

urlpatterns = [
    path("status/", CowStatusView.as_view(), name="cow-status"),
    path("commit/", CommitCowSessionView.as_view(), name="cow-commit-session"),
    path(
        "operations/commit/",
        CommitCowOperationsView.as_view(),
        name="cow-commit-operations",
    ),
    path(
        "operations/discard/",
        DiscardCowOperationsView.as_view(),
        name="cow-discard-operations",
    ),
    path(
        "sessions/<str:session_id>/operations/",
        SessionOperationsView.as_view(),
        name="cow-session-operations",
    ),
    path(
        "sessions/<str:session_id>/graph/",
        SessionGraphView.as_view(),
        name="cow-session-graph",
    ),
    path("recordings/start/", StartRecordingView.as_view(), name="cow-recording-start"),
    path("recordings/stop/", StopRecordingView.as_view(), name="cow-recording-stop"),
    path("recordings/", RecordingListView.as_view(), name="cow-recording-list"),
    path(
        "recordings/<str:session_id>/",
        RecordingDetailView.as_view(),
        name="cow-recording-detail",
    ),
    path(
        "agent-sessions/start/",
        StartAgentSessionView.as_view(),
        name="cow-agent-session-start",
    ),
    path(
        "agent-sessions/finish/",
        FinishAgentSessionView.as_view(),
        name="cow-agent-session-finish",
    ),
    path(
        "agent-sessions/",
        AgentSessionListView.as_view(),
        name="cow-agent-session-list",
    ),
    path(
        "agent-sessions/<str:session_id>/",
        AgentSessionDetailView.as_view(),
        name="cow-agent-session-detail",
    ),
]
