# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Framework-generic Django adapter for ``agent-cow``.

Everything in this subpackage is Django + Postgres boilerplate with no
plane-specific references. It is a candidate for upstream extraction into
an ``agentcow.django`` module once (and if) the library maintainer decides
to ship first-party framework adapters. See ``adapter/README.md``.

Plane-specific glue (the ``ENABLE_COW`` feature flag, URL bypass list,
DRF views, AppConfig, etc.) intentionally lives one level up in
``plane.cow``.
"""

from plane.cow.adapter.context import (
    COW_OPERATION_HEADER,
    COW_SESSION_HEADER,
    COW_VISIBLE_OPERATIONS_HEADER,
    parse_cow_headers_from_request,
    trail_cow_context,
    trail_cow_ctx,
)
from plane.cow.adapter.cow_lib import (
    COW_EXCLUDED_APPS,
    COW_EXCLUDED_TABLES,
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
)
from plane.cow.adapter.cow_session import apply_cow_variables_sync
from plane.cow.adapter.executor import DjangoAsyncExecutor
from plane.cow.adapter.middleware import BaseCowSessionMiddleware, CowExecuteWrapper

__all__ = [
    "BaseCowSessionMiddleware",
    "COW_EXCLUDED_APPS",
    "COW_EXCLUDED_TABLES",
    "COW_OPERATION_HEADER",
    "COW_SESSION_HEADER",
    "COW_VISIBLE_OPERATIONS_HEADER",
    "CowExecuteWrapper",
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
