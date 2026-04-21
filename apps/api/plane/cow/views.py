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

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from plane.api.middleware.api_authentication import APIKeyAuthentication
from plane.cow.adapter import cow_lib
from plane.cow.models import CowAgentSession, CowRecordingSession


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


def _serialize_recording(rec: CowRecordingSession, include_trace: bool = False) -> dict:
    payload = {
        "id": str(rec.id),
        "session_id": str(rec.session_id),
        "workspace_id": str(rec.workspace_id) if rec.workspace_id else None,
        "name": rec.name,
        "prompt": rec.prompt,
        "tags": list(rec.tags or []),
        "started_at": rec.started_at.isoformat() if rec.started_at else None,
        "ended_at": rec.ended_at.isoformat() if rec.ended_at else None,
    }
    if include_trace:
        payload["operation_ids"] = [
            str(op) for op in cow_lib.get_session_operations(rec.session_id)
        ]
        payload["dirty_tables"] = cow_lib.get_dirty_tables(rec.session_id)
    return payload


def _serialize_agent_session(agent: CowAgentSession, include_trace: bool = False) -> dict:
    payload = {
        "id": str(agent.id),
        "session_id": str(agent.session_id),
        "workspace_id": str(agent.workspace_id) if agent.workspace_id else None,
        "recording_id": str(agent.recording_id) if agent.recording_id else None,
        "starting_prompt": agent.starting_prompt,
        "model": agent.model,
        "status": agent.status,
        "started_at": agent.started_at.isoformat() if agent.started_at else None,
        "ended_at": agent.ended_at.isoformat() if agent.ended_at else None,
    }
    if include_trace:
        payload["operation_ids"] = [
            str(op) for op in cow_lib.get_session_operations(agent.session_id)
        ]
        payload["dirty_tables"] = cow_lib.get_dirty_tables(agent.session_id)
    return payload


class StartRecordingView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        data = request.data or {}
        workspace_id = data.get("workspace_id")
        try:
            workspace_uuid = (
                _parse_uuid(workspace_id, "workspace_id") if workspace_id else None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        recording = CowRecordingSession.objects.create(
            workspace_id=workspace_uuid,
            name=data.get("name"),
            prompt=data.get("prompt"),
            tags=list(data.get("tags") or []),
        )
        logger.info("Started recording %s (session %s)", recording.id, recording.session_id)
        return Response(_serialize_recording(recording), status=status.HTTP_201_CREATED)


class StopRecordingView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        try:
            session_id = _parse_uuid(request.data.get("session_id"), "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        recording = CowRecordingSession.objects.filter(session_id=session_id).first()
        if recording is None:
            return Response(
                {"error": f"recording with session_id {session_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if recording.ended_at is None:
            recording.ended_at = timezone.now()
            recording.save(update_fields=["ended_at", "updated_at"])
        return Response(_serialize_recording(recording))


class RecordingListView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = CowRecordingSession.objects.all()

        workspace_id = request.query_params.get("workspace_id")
        if workspace_id:
            try:
                qs = qs.filter(workspace_id=_parse_uuid(workspace_id, "workspace_id"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        tag = request.query_params.get("tag")
        if tag:
            qs = qs.filter(tags__contains=[tag])

        active_only = request.query_params.get("active") in ("1", "true", "True")
        if active_only:
            qs = qs.filter(ended_at__isnull=True)

        return Response([_serialize_recording(rec) for rec in qs])


class RecordingDetailView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def _get(self, session_id: str) -> CowRecordingSession:
        session_uuid = _parse_uuid(session_id, "session_id")
        return get_object_or_404(CowRecordingSession, session_id=session_uuid)

    def get(self, request: Request, session_id: str) -> Response:
        try:
            recording = self._get(session_id)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize_recording(recording, include_trace=True))

    def patch(self, request: Request, session_id: str) -> Response:
        try:
            recording = self._get(session_id)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data or {}
        update_fields: list[str] = []
        for field in ("name", "prompt"):
            if field in data:
                setattr(recording, field, data[field])
                update_fields.append(field)
        if "tags" in data:
            recording.tags = list(data["tags"] or [])
            update_fields.append("tags")

        if update_fields:
            update_fields.append("updated_at")
            recording.save(update_fields=update_fields)
        return Response(_serialize_recording(recording))

    def delete(self, request: Request, session_id: str) -> Response:
        try:
            recording = self._get(session_id)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        recording.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StartAgentSessionView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        data = request.data or {}
        try:
            workspace_id = (
                _parse_uuid(data["workspace_id"], "workspace_id")
                if data.get("workspace_id")
                else None
            )
            recording_id = (
                _parse_uuid(data["recording_id"], "recording_id")
                if data.get("recording_id")
                else None
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        agent = CowAgentSession.objects.create(
            workspace_id=workspace_id,
            recording_id=recording_id,
            starting_prompt=data.get("starting_prompt"),
            model=data.get("model"),
            status=CowAgentSession.RUNNING,
        )
        logger.info("Started agent session %s (session %s)", agent.id, agent.session_id)
        return Response(_serialize_agent_session(agent), status=status.HTTP_201_CREATED)


class FinishAgentSessionView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        try:
            session_id = _parse_uuid(request.data.get("session_id"), "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        new_status = (request.data.get("status") or "").upper() or CowAgentSession.COMMITTED
        valid = {s for s, _ in CowAgentSession.STATUS_CHOICES}
        if new_status not in valid:
            return Response(
                {"error": f"status must be one of {sorted(valid)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        agent = CowAgentSession.objects.filter(session_id=session_id).first()
        if agent is None:
            return Response(
                {"error": f"agent session with session_id {session_id} not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        agent.status = new_status
        if agent.ended_at is None:
            agent.ended_at = timezone.now()
        agent.save(update_fields=["status", "ended_at", "updated_at"])
        return Response(_serialize_agent_session(agent))


class AgentSessionListView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = CowAgentSession.objects.all()

        workspace_id = request.query_params.get("workspace_id")
        if workspace_id:
            try:
                qs = qs.filter(workspace_id=_parse_uuid(workspace_id, "workspace_id"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        recording_id = request.query_params.get("recording_id")
        if recording_id:
            try:
                qs = qs.filter(recording_id=_parse_uuid(recording_id, "recording_id"))
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        return Response([_serialize_agent_session(agent) for agent in qs])


class AgentSessionDetailView(APIView):
    authentication_classes = COW_AUTH
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, session_id: str) -> Response:
        try:
            session_uuid = _parse_uuid(session_id, "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        agent = get_object_or_404(CowAgentSession, session_id=session_uuid)
        return Response(_serialize_agent_session(agent, include_trace=True))

    def delete(self, request: Request, session_id: str) -> Response:
        try:
            session_uuid = _parse_uuid(session_id, "session_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        agent = get_object_or_404(CowAgentSession, session_id=session_uuid)
        agent.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
