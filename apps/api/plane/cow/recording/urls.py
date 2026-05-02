# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.cow.recording.views import (
    AgentSessionDetailView,
    AgentSessionListView,
    FinishAgentSessionView,
    RecordingDetailView,
    RecordingListView,
    StartAgentSessionView,
    StartRecordingView,
    StopRecordingView,
)

urlpatterns = [
    path("recordings/start/", StartRecordingView.as_view(), name="cow-recording-start"),
    path("recordings/stop/", StopRecordingView.as_view(), name="cow-recording-stop"),
    path("recordings/", RecordingListView.as_view(), name="cow-recording-list"),
    path("recordings/<str:session_id>/", RecordingDetailView.as_view(), name="cow-recording-detail"),
    path("agent-sessions/start/", StartAgentSessionView.as_view(), name="cow-agent-session-start"),
    path("agent-sessions/finish/", FinishAgentSessionView.as_view(), name="cow-agent-session-finish"),
    path("agent-sessions/", AgentSessionListView.as_view(), name="cow-agent-session-list"),
    path("agent-sessions/<str:session_id>/", AgentSessionDetailView.as_view(), name="cow-agent-session-detail"),
]
