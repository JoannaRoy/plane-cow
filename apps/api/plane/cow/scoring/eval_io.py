# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Shared eval harness output helpers — CSV / JSONL writers, pydantic-evals
Dataset construction, logfire setup.

Used by :mod:`plane.cow.management.commands.eval_recordings` for scoring
output, and by :mod:`plane.cow.management.commands.run_recordings` for
generic CSV / JSONL run logs.

Everything here is framework-agnostic Python; no Django ORM imports, no
HTTP. Callers hand in already-scored :class:`ScoringResult` objects wrapped
in :class:`PairResult` and this module produces output files / eval
reports from them.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

from agentcow.scoring import ScoringResult, SessionScoringTerms

logger = logging.getLogger("plane.cow.eval")


@dataclass(frozen=True)
class PairResult:
    """Identity of a scored (recording, agent-session) pair plus its result.

    The same shape is produced by both eval commands, so they share all
    output formatting below.
    """

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
    """Flatten a scored pair into a single CSV-friendly row."""
    terms: SessionScoringTerms = pair.result.terms
    row: dict[str, Any] = {
        "recording_id": str(pair.recording_id),
        "recording_session_id": str(pair.recording_session_id),
        "recording_name": pair.recording_name or "",
        "agent_id": str(pair.agent_id),
        "agent_session_id": str(pair.agent_session_id),
        "agent_model": pair.agent_model or "",
        "agent_status": pair.agent_status,
        "workspace_id": str(pair.workspace_id) if pair.workspace_id else "",
        "structural_score": terms.structural_score,
        "content_score": terms.content_score,
        "relationship_score": terms.relationship_score,
        "efficiency": terms.efficiency,
        "gt_operation_count": terms.gt_operation_count,
        "agent_operation_count": terms.agent_operation_count,
        "matched_row_count": terms.matched_row_count,
        "missing_row_count": terms.missing_row_count,
        "extra_row_count": terms.extra_row_count,
    }
    for name, value in pair.result.scores.items():
        row[f"score_{name}"] = value
    return row


def jsonl_entry(pair: PairResult) -> dict[str, Any]:
    """Full per-pair record: flat metrics + feedback + per-op utilities."""
    return {
        **metrics_row(pair),
        "recording_prompt": pair.recording_prompt,
        "feedback_report": pair.result.feedback_report,
        "op_utilities": [
            {
                "op_id": str(util.op_id),
                "structural_utility": util.structural_utility,
                "content_utility": util.content_utility,
                "structural_score_before": util.structural_score_before,
                "structural_score_after": util.structural_score_after,
            }
            for util in pair.result.terms.op_utilities
        ],
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


def setup_logfire() -> bool:
    """Configure logfire if installed; no-op when ``LOGFIRE_TOKEN`` is unset."""
    try:
        import logfire
    except ImportError:
        logger.info("logfire not installed; skipping logfire setup")
        return False
    logfire.configure(
        service_name="plane-cow-eval",
        send_to_logfire="if-token-present",
        scrubbing=False,
    )
    return True


def flush_logfire() -> None:
    try:
        import logfire
    except ImportError:
        return
    logfire.force_flush()


def run_pydantic_evals_dataset(
    pairs: list[PairResult], *, name: str
) -> Optional[Any]:
    """Build + run a pydantic-evals Dataset over ``pairs``.

    Returns the :class:`EvaluationReport` (or ``None`` if pydantic-evals
    isn't installed). When ``LOGFIRE_TOKEN`` is set, the dataset run is
    pushed to Logfire Evals automatically.
    """
    try:
        from dataclasses import dataclass as _dc

        from pydantic import BaseModel
        from pydantic_evals import Case, Dataset
        from pydantic_evals.evaluators import Evaluator, EvaluatorContext
    except ImportError:
        logger.warning(
            "pydantic-evals not installed; skipping logfire eval dataset. "
            "Install with `pip install pydantic-evals logfire` to enable."
        )
        return None

    class _Input(BaseModel):
        recording_session_id: str
        agent_session_id: str
        model: Optional[str] = None
        prompt: Optional[str] = None

    class _Output(BaseModel):
        overall: float
        precision: float
        recall: float
        f1: float
        structural: float
        content: float
        relationship: float
        efficiency: float
        matched_rows: int
        missing_rows: int
        extra_rows: int

    @_dc
    class _MetricEvaluator(Evaluator[_Input, _Output, None]):
        metric: str

        def evaluate(
            self, ctx: EvaluatorContext[_Input, _Output, None]
        ) -> float:
            return float(getattr(ctx.output, self.metric))

    by_agent = {pair.agent_session_id: pair for pair in pairs}

    cases = [
        Case(
            name=_case_name(pair),
            inputs=_Input(
                recording_session_id=str(pair.recording_session_id),
                agent_session_id=str(pair.agent_session_id),
                model=pair.agent_model,
                prompt=pair.recording_prompt,
            ),
        )
        for pair in pairs
    ]

    def run_pair(inputs: _Input) -> _Output:
        pair = by_agent[uuid.UUID(inputs.agent_session_id)]
        result = pair.result
        return _Output(
            overall=float(result.scores.get("overall", 0.0)),
            precision=float(result.scores.get("precision", 0.0)),
            recall=float(result.scores.get("recall", 0.0)),
            f1=float(result.scores.get("f1", 0.0)),
            structural=result.terms.structural_score,
            content=result.terms.content_score,
            relationship=result.terms.relationship_score,
            efficiency=result.terms.efficiency,
            matched_rows=result.terms.matched_row_count,
            missing_rows=result.terms.missing_row_count,
            extra_rows=result.terms.extra_row_count,
        )

    dataset = Dataset(
        cases=cases,
        evaluators=[
            _MetricEvaluator(metric=m)
            for m in (
                "overall",
                "precision",
                "recall",
                "f1",
                "structural",
                "content",
                "relationship",
                "efficiency",
            )
        ],
    )
    return dataset.evaluate_sync(run_pair, name=name)


def _case_name(pair: PairResult) -> str:
    """Compact, human-readable case name used in pydantic-evals / logfire."""
    rec = pair.recording_name or str(pair.recording_session_id)[:8]
    if pair.agent_model:
        return f"{rec} :: {pair.agent_model} :: {str(pair.agent_session_id)[:8]}"
    return f"{rec} :: {str(pair.agent_session_id)[:8]}"
