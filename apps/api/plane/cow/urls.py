# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from django.urls import include, path

urlpatterns = [
    path("", include("plane.cow.core.urls")),
    path("", include("plane.cow.recording.urls")),
]
