# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Control-plane models for COW recordings and agent sessions.

Both tables are excluded from COW enablement (see
``plane.cow.adapter.cow_lib.COW_EXCLUDED_TABLES``) so their rows are never
shadowed — they describe recordings/runs that live *alongside* the COW
machinery, not data that should itself be staged.

Recording / agent session traces are reconstructed by joining ``session_id``
against the ``*_changes`` tables via ``cow_lib.get_session_operations`` and
``cow_lib.get_dirty_tables`` — there is no separate operation log.
"""

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models

from plane.db.models.base import BaseModel


class CowRecordingSession(BaseModel):
    """A user-demonstrated workflow captured against the COW layer.

    The ``session_id`` is the value sent in the ``x-agent-session-id``
    header for every ``/api/v1/...`` call that should be part of this
    recording. Replay pulls the recording's ``prompt`` and feeds it to an
    agent under a *fresh* session id.
    """

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="cow_recordings",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, null=True, blank=True)
    prompt = models.TextField(null=True, blank=True)
    tags = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cow_recording_session"
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"{self.name or self.id} [{self.session_id}]"


class CowAgentSession(BaseModel):
    """One execution of an agent against a COW session.

    Optionally tied to a ``CowRecordingSession`` (the ground-truth trace we
    tried to reproduce). When ``recording`` is null the row describes an
    ad-hoc agent run — still useful for future scoring against a reference.
    """

    RUNNING = "RUNNING"
    COMMITTED = "COMMITTED"
    DISCARDED = "DISCARDED"
    FAILED = "FAILED"
    STATUS_CHOICES = (
        (RUNNING, RUNNING),
        (COMMITTED, COMMITTED),
        (DISCARDED, DISCARDED),
        (FAILED, FAILED),
    )

    session_id = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    workspace = models.ForeignKey(
        "db.Workspace",
        on_delete=models.CASCADE,
        related_name="cow_agent_sessions",
        null=True,
        blank=True,
    )
    recording = models.ForeignKey(
        CowRecordingSession,
        on_delete=models.SET_NULL,
        related_name="agent_sessions",
        null=True,
        blank=True,
    )
    starting_prompt = models.TextField(null=True, blank=True)
    model = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=RUNNING)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cow_agent_session"
        ordering = ("-started_at",)

    def __str__(self) -> str:
        return f"agent-session {self.session_id} (recording={self.recording_id})"
