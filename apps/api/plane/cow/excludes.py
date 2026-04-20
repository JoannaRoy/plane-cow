# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Plane-specific COW exclusion lists.

Anything listed here is skipped by ``cow_enable`` / ``cow_disable`` /
``cow_migrate`` in addition to the generic defaults defined in
``plane.cow.adapter.cow_lib``. Keep plane-specific knowledge here
rather than polluting the generic adapter module.
"""

from __future__ import annotations


PLANE_EXCLUDED_APPS: set[str] = set()


PLANE_EXCLUDED_TABLES: set[str] = {
    "device_sessions",
}
