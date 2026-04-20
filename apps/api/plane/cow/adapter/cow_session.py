# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""COW session variable management for sync Django transactions.

``SET LOCAL`` only lives until ``COMMIT``, so we re-issue the statements
every time a new transaction starts on the connection. This mirrors the
SQLAlchemy ``after_begin`` listener used by monotrail.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from agentcow.postgres.context import build_cow_variable_statements

logger = logging.getLogger(__name__)


def apply_cow_variables_sync(
    connection,
    agent_session_id: uuid.UUID,
    operation_id: Optional[uuid.UUID] = None,
    visible_operations: Optional[list[uuid.UUID]] = None,
) -> None:
    """Run the ``SET LOCAL`` statements for a COW session on *connection*.

    Accepts anything with a ``.cursor()`` method (Django ``BaseDatabaseWrapper``
    or a raw DB-API connection).
    """
    statements = build_cow_variable_statements(
        agent_session_id, operation_id, visible_operations
    )
    with connection.cursor() as cursor:
        for stmt in statements:
            cursor.execute(stmt)
