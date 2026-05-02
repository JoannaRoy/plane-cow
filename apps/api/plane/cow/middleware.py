# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Plane-specific configuration of the generic COW middleware.

All the heavy lifting lives in :mod:`agentcow.postgres.adapters.django.middleware`.
This module only supplies plane-local policy: honour ``settings.ENABLE_COW``
and skip the middleware for the commit/discard endpoints so they don't
accidentally stage themselves as COW changes.
"""

from __future__ import annotations

import os

from django.conf import settings

from agentcow.postgres.adapters.django.middleware import BaseCowSessionMiddleware


def _is_cow_enabled() -> bool:
    if getattr(settings, "ENABLE_COW", None) is not None:
        return bool(settings.ENABLE_COW)
    return os.environ.get("ENABLE_COW", "0") == "1"


class CowSessionMiddleware(BaseCowSessionMiddleware):
    bypass_prefixes = ("/api/cow/",)

    def __init__(self, get_response):
        super().__init__(get_response)
        self.enabled = _is_cow_enabled()
