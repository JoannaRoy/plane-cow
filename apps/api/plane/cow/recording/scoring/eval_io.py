# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from agentcow.scoring import ScoringResult


@dataclass(frozen=True)
class PairResult:
    recording_id: uuid.UUID
    recording_session_id: uuid.UUID
    recording_name: Optional[str]
    recording_prompt: Optional[str]
    agent_id: uuid.UUID
    agent_session_id: uuid.UUID
    agent_model: Optional[str]
    agent_status: str
    workspace_id: Optional[uuid.UUID]
    result: ScoringResult


def metrics_row(pair: PairResult) -> dict[str, Any]:
    result = pair.result
    row: dict[str, Any] = {
        "recording_id": str(pair.recording_id),
        "recording_session_id": str(pair.recording_session_id),
        "recording_name": pair.recording_name or "",
        "agent_id": str(pair.agent_id),
        "agent_session_id": str(pair.agent_session_id),
        "agent_model": pair.agent_model or "",
        "agent_status": pair.agent_status,
        "workspace_id": str(pair.workspace_id) if pair.workspace_id else "",
        "structural_score": result.struct_score,
        "content_score": result.content_score,
        "efficiency": result.efficiency,
        "gt_operation_count": result.counts["gt_ops"],
        "agent_operation_count": result.counts["agent_ops"],
        "matched_row_count": result.counts["matched"],
        "missing_row_count": result.counts["missing"],
        "extra_row_count": result.counts["extra"],
    }
    for name, value in result.scores.items():
        row[f"score_{name}"] = value
    return row


def jsonl_entry(pair: PairResult) -> dict[str, Any]:
    result = pair.result
    running = 0.0
    op_utilities = []
    for op_id, delta in result.op_struct_scores.items():
        op_utilities.append({
            "op_id": str(op_id),
            "structural_utility": delta,
            "content_utility": result.op_content_scores.get(op_id, 0.0),
            "structural_score_before": running,
            "structural_score_after": running + delta,
        })
        running += delta

    return {
        **metrics_row(pair),
        "recording_prompt": pair.recording_prompt,
        "op_utilities": op_utilities,
    }


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    rows = list(rows)
    if not rows:
        path.write_text("")
        return
    fieldnames = list(rows[0].keys())
    for row in rows[1:]:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_jsonl(path: Path, entries: Iterable[dict[str, Any]]) -> None:
    with path.open("w") as fp:
        for entry in entries:
            fp.write(json.dumps(entry, default=str))
            fp.write("\n")
