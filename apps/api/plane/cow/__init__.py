# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Copy-On-Write (COW) support for plane.

This package integrates the ``agent-cow`` library into the plane Django app.
See ``plane/cow/README.md`` for the full walkthrough. The architecture
mirrors monotrail's ``terra.cow`` module.

Layout
------

* ``plane.cow.adapter``: framework-generic Django + Postgres glue. Candidate
  for upstream extraction into an ``agentcow.django`` package.
* ``plane.cow`` (this module): plane-specific configuration — DRF views,
  URL wiring, AppConfig, and the concrete ``CowSessionMiddleware`` subclass
  that reads ``settings.ENABLE_COW`` and skips the ``/api/cow/`` endpoints.

Public names are re-exported from ``plane.cow.adapter`` so existing import
sites keep working.
"""

from plane.cow.adapter import (
    COW_EXCLUDED_APPS,
    COW_EXCLUDED_TABLES,
    COW_OPERATION_HEADER,
    COW_SESSION_HEADER,
    COW_VISIBLE_OPERATIONS_HEADER,
    DjangoAsyncExecutor,
    apply_cow_variables_sync,
    commit_cow_operations,
    commit_cow_session,
    cow_target_models,
    deploy_cow_functions,
    disable_cow_for_all_models,
    disable_cow_for_model,
    discard_cow_operations,
    enable_cow_for_all_models,
    enable_cow_for_model,
    get_cow_status,
    get_dirty_tables,
    get_session_operations,
    parse_cow_headers_from_request,
    trail_cow_context,
    trail_cow_ctx,
)

__all__ = [
    "COW_EXCLUDED_APPS",
    "COW_EXCLUDED_TABLES",
    "COW_OPERATION_HEADER",
    "COW_SESSION_HEADER",
    "COW_VISIBLE_OPERATIONS_HEADER",
    "DjangoAsyncExecutor",
    "apply_cow_variables_sync",
    "commit_cow_operations",
    "commit_cow_session",
    "cow_target_models",
    "deploy_cow_functions",
    "disable_cow_for_all_models",
    "disable_cow_for_model",
    "discard_cow_operations",
    "enable_cow_for_all_models",
    "enable_cow_for_model",
    "get_cow_status",
    "get_dirty_tables",
    "get_session_operations",
    "parse_cow_headers_from_request",
    "trail_cow_context",
    "trail_cow_ctx",
]
