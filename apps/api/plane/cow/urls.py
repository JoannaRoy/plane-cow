# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import path

from plane.cow.views import (
    CommitCowOperationsView,
    CommitCowSessionView,
    CowStatusView,
    DiscardCowOperationsView,
    SessionOperationsView,
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
]
