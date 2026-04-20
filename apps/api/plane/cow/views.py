# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""DRF endpoints for COW session management.

Mirrors the GraphQL mutations defined in
``terra.strawberry_gql.gql_models.cow.cow_mutations`` but exposed as
plain HTTP endpoints because plane has no GraphQL layer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.cow.adapter import cow_lib


COW_AUTH = (APIKeyAuthentication, SessionAuthentication)

logger = logging.getLogger("plane.cow")


def _parse_uuid(value, field_name: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if not value:
        raise ValueError(f"{field_name} is required")
    return uuid.UUID(str(value))


def _parse_uuid_list(values, field_name: str) -> list[uuid.UUID]:
    if not values:
        return []
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    return [_parse_uuid(v, f"{field_name}[]") for v in values]


class CowStatusView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        return Response(cow_lib.get_cow_status())


class CommitCowSessionView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        try:
            session_id = _parse_uuid(request.data.get("session_id"), "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        logger.info("Committing COW session %s", session_id)
        committed = cow_lib.commit_cow_session(session_id)
        return Response({"session_id": str(session_id), "committed_tables": committed})


class CommitCowOperationsView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        try:
            session_id = _parse_uuid(request.data.get("session_id"), "session_id")
            operation_ids = _parse_uuid_list(
                request.data.get("operation_ids"), "operation_ids"
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not operation_ids:
            operation_ids = cow_lib.get_session_operations(session_id)

        logger.info(
            "Committing %d operations from COW session %s",
            len(operation_ids),
            session_id,
        )
        committed = cow_lib.commit_cow_operations(session_id, operation_ids)
        return Response(
            {
                "session_id": str(session_id),
                "operation_ids": [str(op) for op in operation_ids],
                "committed_tables": committed,
            }
        )


class DiscardCowOperationsView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        try:
            session_id = _parse_uuid(request.data.get("session_id"), "session_id")
            operation_ids = _parse_uuid_list(
                request.data.get("operation_ids"), "operation_ids"
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if not operation_ids:
            return Response(
                {"error": "operation_ids is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "Discarding %d operations from COW session %s",
            len(operation_ids),
            session_id,
        )
        discarded = cow_lib.discard_cow_operations(session_id, operation_ids)
        return Response(
            {
                "session_id": str(session_id),
                "operation_ids": [str(op) for op in operation_ids],
                "discarded_tables": discarded,
            }
        )


class SessionOperationsView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, session_id: str) -> Response:
        try:
            session_uuid = _parse_uuid(session_id, "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        operations = cow_lib.get_session_operations(session_uuid)
        dirty_tables = cow_lib.get_dirty_tables(session_uuid)
        return Response(
            {
                "session_id": str(session_uuid),
                "operation_ids": [str(op) for op in operations],
                "dirty_tables": dirty_tables,
            }
        )
