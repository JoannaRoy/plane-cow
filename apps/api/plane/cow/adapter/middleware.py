# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Base Django middleware that activates a COW session for a request.

Generic pieces (execute_wrapper that re-emits ``SET LOCAL`` per transaction,
atomic-block wrapping, ContextVar binding, recursion guard) live here.
App-specific configuration (feature flag source, URL bypass list, DB alias)
is exposed as class attributes so consumers subclass and override.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from django.db import connections, transaction
from django.http import HttpRequest, HttpResponse

from agentcow.postgres.context import (
    CowPostgresConfig,
    build_cow_variable_statements,
)

from plane.cow.adapter.context import (
    parse_cow_headers_from_request,
    trail_cow_ctx,
)

logger = logging.getLogger(__name__)


class CowExecuteWrapper:
    """Prepend ``SET LOCAL ...`` to the first statement of every transaction.

    Django reuses connections across requests, so we cannot rely on
    ``connection_created``. Instead, we track whether the current
    ``transaction.atomic`` block has already applied the COW variables and
    re-emit them whenever a new savepoint/transaction is entered.
    """

    def __init__(self, config: CowPostgresConfig, using: str) -> None:
        self._statements = build_cow_variable_statements(
            config.session_id,
            config.operation_id,
            config.visible_operations,
        )
        self._using = using
        self._applied_for_savepoint: Optional[str] = None
        self._applying = False

    def __call__(self, execute: Callable, sql: str, params, many: bool, context):
        conn = context["connection"]
        if conn.alias != self._using:
            return execute(sql, params, many, context)

        if self._applying:
            return execute(sql, params, many, context)

        current_sid = getattr(conn, "savepoint_ids", None)
        marker = (
            ",".join("__none__" if s is None else str(s) for s in current_sid)
            if current_sid
            else "__root__"
        )
        in_atomic = conn.in_atomic_block

        if in_atomic and self._applied_for_savepoint != marker:
            self._applied_for_savepoint = marker
            self._applying = True
            try:
                with conn.cursor() as cursor:
                    for stmt in self._statements:
                        cursor.execute(stmt)
            finally:
                self._applying = False

        return execute(sql, params, many, context)

    def reset(self) -> None:
        self._applied_for_savepoint = None


class BaseCowSessionMiddleware:
    """Activate the COW ContextVar and DB session variables for a request.

    Subclass and override ``enabled`` / ``bypass_prefixes`` / ``using`` to
    plug in app-specific configuration. By default COW is ``enabled=True``
    with no URL bypasses on the ``default`` database.
    """

    enabled: bool = True
    bypass_prefixes: tuple[str, ...] = ()
    using: str = "default"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if not self.enabled:
            return self.get_response(request)

        if self._should_bypass(request.path):
            return self.get_response(request)

        config = parse_cow_headers_from_request(request)
        if not config.session_id:
            return self.get_response(request)

        connection = connections[self.using]
        wrapper = CowExecuteWrapper(config, self.using)

        token = trail_cow_ctx.set(config)
        try:
            with connection.execute_wrapper(wrapper):
                with transaction.atomic(using=self.using):
                    wrapper.reset()
                    return self.get_response(request)
        finally:
            trail_cow_ctx.reset(token)

    def _should_bypass(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.bypass_prefixes)
