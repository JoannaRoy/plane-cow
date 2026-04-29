# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Score every (recording, agent-session) pair that already exists in the DB.

Usage::

    python manage.py eval_recordings \
        [--workspace-id <uuid>] \
        [--recording-session-id <uuid>] \
        [--agent-session-id <uuid>] \
        [--limit N] \
        [--output-dir ./eval_output] \
        [--name eval-2026-04-20]
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError

from plane.cow.models import CowAgentSession
from plane.cow.scoring import score_plane_sessions
from plane.cow.scoring.eval_io import (
    PairResult,
    jsonl_entry,
    metrics_row,
    write_csv,
    write_jsonl,
)

logger = logging.getLogger("plane.cow.eval")


def _collect_pairs(
    *,
    workspace_id: Optional[uuid.UUID],
    recording_session_id: Optional[uuid.UUID],
    agent_session_id: Optional[uuid.UUID],
    limit: Optional[int],
) -> list[CowAgentSession]:
    qs = CowAgentSession.objects.select_related("recording").filter(
        recording__isnull=False
    )
    if workspace_id is not None:
        qs = qs.filter(workspace_id=workspace_id)
    if recording_session_id is not None:
        qs = qs.filter(recording__session_id=recording_session_id)
    if agent_session_id is not None:
        qs = qs.filter(session_id=agent_session_id)
    qs = qs.order_by("-started_at")
    if limit is not None and limit > 0:
        qs = qs[:limit]
    return list(qs)


def _score_agent(agent: CowAgentSession) -> PairResult:
    rec = agent.recording
    result = async_to_sync(score_plane_sessions)(
        ground_truth_session_id=rec.session_id,
        agent_session_id=agent.session_id,
    )
    return PairResult(
        recording_id=rec.id,
        recording_session_id=rec.session_id,
        recording_name=rec.name,
        recording_prompt=rec.prompt,
        agent_id=agent.id,
        agent_session_id=agent.session_id,
        agent_model=agent.model,
        agent_status=agent.status,
        workspace_id=agent.workspace_id,
        result=result,
    )


class Command(BaseCommand):
    help = "Score every (recording, agent-session) pair and dump results to CSV + JSONL."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default", help="Django DB alias")
        parser.add_argument("--workspace-id", help="Filter by workspace UUID")
        parser.add_argument("--recording-session-id", help="Score only pairs under this recording session_id")
        parser.add_argument("--agent-session-id", help="Score only this single agent session")
        parser.add_argument("--limit", type=int, help="Cap the number of pairs scored")
        parser.add_argument("--output-dir", default="./eval_output", help="Directory for CSV/JSONL output")
        parser.add_argument("--name", help="Output file name prefix (default: timestamp)")

    def handle(self, *args, **options):
        workspace_id = _parse_uuid(options.get("workspace_id"))
        recording_session_id = _parse_uuid(options.get("recording_session_id"))
        agent_session_id = _parse_uuid(options.get("agent_session_id"))

        agents = _collect_pairs(
            workspace_id=workspace_id,
            recording_session_id=recording_session_id,
            agent_session_id=agent_session_id,
            limit=options.get("limit"),
        )
        if not agents:
            raise CommandError(
                "No (recording, agent-session) pairs matched the given filters."
            )

        self.stdout.write(f"Scoring {len(agents)} pair(s)...")

        pairs: list[PairResult] = []
        for i, agent in enumerate(agents, 1):
            self.stdout.write(
                f"  [{i}/{len(agents)}] recording={agent.recording.session_id} "
                f"agent={agent.session_id}"
            )
            pairs.append(_score_agent(agent))

        output_dir = Path(options["output_dir"]).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        name = options.get("name") or f"eval-{ts}"
        csv_path = output_dir / f"{name}.csv"
        jsonl_path = output_dir / f"{name}.jsonl"

        write_csv(csv_path, (metrics_row(p) for p in pairs))
        write_jsonl(jsonl_path, (jsonl_entry(p) for p in pairs))
        self.stdout.write(self.style.SUCCESS(f"Wrote {csv_path}"))
        self.stdout.write(self.style.SUCCESS(f"Wrote {jsonl_path}"))


def _parse_uuid(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
