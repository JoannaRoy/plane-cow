# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Per-request Copy-On-Write context (generic Django adapter).

A ContextVar holds the active COW configuration for the duration of a
request; a helper parses the COW headers off any object with a ``.headers``
mapping. Mirrors monotrail's ``terra.cow.context``.
"""

from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional

from agentcow.postgres.context import CowPostgresConfig

logger = logging.getLogger(__name__)


trail_cow_ctx: ContextVar[Optional[CowPostgresConfig]] = ContextVar(
    "trail_cow_ctx", default=None
)


@contextmanager
def trail_cow_context(cow_config: CowPostgresConfig) -> Iterator[CowPostgresConfig]:
    """Activate a COW config for the duration of the block.

    If ``cow_config.session_id`` is set and no ``operation_id`` is present,
    a fresh operation id is generated (matches monotrail's behaviour in
    ``TrailCowContext.__post_init__``).
    """
    if cow_config.session_id and not cow_config.operation_id:
        cow_config.operation_id = uuid.uuid4()

    token = trail_cow_ctx.set(cow_config)
    try:
        yield cow_config
    finally:
        trail_cow_ctx.reset(token)


COW_SESSION_HEADER = "x-agent-session-id"
COW_OPERATION_HEADER = "x-operation-id"
COW_VISIBLE_OPERATIONS_HEADER = "x-visible-operations"


def parse_cow_headers_from_request(request) -> CowPostgresConfig:
    """Extract a :class:`CowPostgresConfig` from an HTTP request.

    Works with Django ``HttpRequest`` and anything else exposing a
    ``.headers`` mapping. Invalid header values are logged and treated as
    absent so the request falls through to non-COW behaviour.
    """
    if request is None:
        return CowPostgresConfig()

    session_id = _parse_uuid_header(request, COW_SESSION_HEADER)
    operation_id = _parse_uuid_header(request, COW_OPERATION_HEADER)
    visible_operations = _parse_uuid_list_header(request, COW_VISIBLE_OPERATIONS_HEADER)

    return CowPostgresConfig(
        session_id=session_id,
        operation_id=operation_id,
        visible_operations=visible_operations,
    )


def _get_header(request, name: str) -> Optional[str]:
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return headers.get(name)


def _parse_uuid_header(request, name: str) -> Optional[uuid.UUID]:
    value = _get_header(request, name)
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        logger.warning("Invalid %s header: %r", name, value)
        return None


def _parse_uuid_list_header(request, name: str) -> Optional[list[uuid.UUID]]:
    value = _get_header(request, name)
    if not value:
        return None
    try:
        return [uuid.UUID(v.strip()) for v in value.split(",") if v.strip()]
    except ValueError:
        logger.warning("Invalid %s header: %r", name, value)
        return None
