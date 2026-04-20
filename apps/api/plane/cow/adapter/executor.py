# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Django ``Executor`` adapter for agent-cow.

agent-cow's core API is async and driver-agnostic — it only requires an
object with ``async execute(sql: str) -> list[tuple]``. Django is sync, so
we wrap a Django cursor with ``asgiref.sync.sync_to_async``.
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import sync_to_async
from django.db import connections


class DjangoAsyncExecutor:
    """Adapts a Django DB connection to the ``agentcow.postgres.Executor`` protocol."""

    def __init__(self, using: str = "default") -> None:
        self._using = using

    async def execute(self, sql: str) -> list[tuple[Any, ...]]:
        return await sync_to_async(self._execute_sync, thread_sensitive=True)(sql)

    def _execute_sync(self, sql: str) -> list[tuple[Any, ...]]:
        connection = connections[self._using]
        with connection.cursor() as cursor:
            cursor.execute(sql)
            if cursor.description is None:
                return []
            return [tuple(row) for row in cursor.fetchall()]
