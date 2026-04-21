from __future__ import annotations

import os
import uuid
from typing import Any, Optional

import httpx
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from plane.cow.adapter import cow_lib
from plane.cow.models import CowAgentSession, CowRecordingSession


DEFAULT_MODELS: list[str] = [
    "gemini/gemini-2.5-pro",
]


def _collect_recordings(
    *,
    workspace_id: Optional[uuid.UUID],
    recording_session_id: Optional[uuid.UUID],
    tag: Optional[str],
    limit: Optional[int],
    require_prompt: bool,
) -> list[CowRecordingSession]:
    qs = CowRecordingSession.objects.all()
    if workspace_id is not None:
        qs = qs.filter(workspace_id=workspace_id)
    if recording_session_id is not None:
        qs = qs.filter(session_id=recording_session_id)
    if tag:
        qs = qs.filter(tags__contains=[tag])
    qs = qs.order_by("-started_at")
    if limit is not None and limit > 0:
        qs = qs[:limit]

    recordings = list(qs)
    if require_prompt:
        recordings = [r for r in recordings if r.prompt]
    return recordings


def _run_agent_turn(
    agent_url: str, model: str, session_id: uuid.UUID, prompt: str, timeout: float
) -> tuple[bool, Optional[str]]:
    url = f"{agent_url.rstrip('/')}/chat"
    body = {
        "model": model,
        "session_id": str(session_id),
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        resp = httpx.post(url, json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        return False, f"chat request failed: {exc}"
    if resp.status_code >= 400:
        return False, f"chat returned {resp.status_code}: {resp.text[:500]}"
    return True, None


def _finalize(agent: CowAgentSession, status: str, discard: bool) -> None:
    if discard and status == CowAgentSession.DISCARDED:
        op_ids = cow_lib.get_session_operations(agent.session_id)
        if op_ids:
            cow_lib.discard_cow_operations(agent.session_id, op_ids)

    agent.status = status
    if agent.ended_at is None:
        agent.ended_at = timezone.now()
    agent.save(update_fields=["status", "ended_at", "updated_at"])


def _run_one(
    *,
    recording: CowRecordingSession,
    model: str,
    prompt: str,
    agent_url: str,
    timeout: float,
    commit: bool,
    discard: bool,
    stdout_writer,
) -> tuple[uuid.UUID, str]:
    agent = CowAgentSession.objects.create(
        recording=recording,
        workspace_id=recording.workspace_id,
        starting_prompt=prompt,
        model=model,
        status=CowAgentSession.RUNNING,
    )
    stdout_writer(f"      agent_session={agent.session_id} (id={agent.id})")

    ok, err = _run_agent_turn(agent_url, model, agent.session_id, prompt, timeout)
    if not ok:
        stdout_writer(f"      FAILED: {err}")
        _finalize(agent, CowAgentSession.FAILED, discard=False)
    else:
        if commit:
            cow_lib.commit_cow_session(agent.session_id)
            _finalize(agent, CowAgentSession.COMMITTED, discard=False)
        elif discard:
            _finalize(agent, CowAgentSession.DISCARDED, discard=True)
        else:
            _finalize(agent, CowAgentSession.RUNNING, discard=False)

    agent.refresh_from_db()
    return agent.session_id, agent.status


class Command(BaseCommand):
    help = (
        "Run each recording's prompt through a list of models to create "
        "agent sessions. Score them afterwards with eval_recordings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--models",
            nargs="+",
            help=f"List of model names (default: {DEFAULT_MODELS})",
        )
        parser.add_argument("--database", default="default", help="Django DB alias")
        parser.add_argument("--workspace-id", help="Only recordings in this workspace")
        parser.add_argument(
            "--recording-session-id",
            help="Run only this single recording against every model",
        )
        parser.add_argument("--tag", help="Only recordings with this tag")
        parser.add_argument(
            "--limit-recordings",
            type=int,
            help="Cap the number of recordings (newest first)",
        )
        parser.add_argument(
            "--agent-url",
            default=os.environ.get("AGENT_URL", "http://localhost:8001"),
            help="FastAPI chat agent base URL",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=300.0,
            help="Per-chat-turn HTTP timeout (seconds)",
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--commit",
            action="store_true",
            help="Commit each agent's staged ops to base tables after the turn",
        )
        group.add_argument(
            "--discard",
            action="store_true",
            help="Discard each agent's staged ops after the turn. Do NOT use this if you plan to score with eval_recordings — scoring reads the staged ops.",
        )
        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            default=True,
            help="Keep going when one (recording, model) run fails (default: true)",
        )

    def handle(self, *args, **options):
        models: list[str] = options.get("models") or DEFAULT_MODELS
        workspace_id = _parse_uuid(options.get("workspace_id"))
        recording_session_id = _parse_uuid(options.get("recording_session_id"))

        recordings = _collect_recordings(
            workspace_id=workspace_id,
            recording_session_id=recording_session_id,
            tag=options.get("tag"),
            limit=options.get("limit_recordings"),
            require_prompt=True,
        )
        if not recordings:
            raise CommandError(
                "No recordings matched the given filters (or all had empty "
                "prompt). Create one via POST /api/cow/recordings/start/."
            )

        total = len(recordings) * len(models)
        self.stdout.write(
            f"Running {len(recordings)} recording(s) × {len(models)} model(s) "
            f"= {total} agent turns"
        )
        self.stdout.write(f"Models: {models}")

        succeeded = 0
        failures: list[str] = []
        agent_url: str = options["agent_url"]
        timeout: float = options["timeout"]
        commit: bool = options["commit"]
        discard: bool = options["discard"]
        continue_on_error: bool = options["continue_on_error"]

        run_idx = 0
        for rec in recordings:
            prompt = rec.prompt or ""
            rec_label = rec.name or str(rec.session_id)[:8]
            self.stdout.write(
                f"\n[recording {rec_label}] session={rec.session_id} "
                f"prompt={_truncate(prompt)}"
            )
            for model in models:
                run_idx += 1
                self.stdout.write(f"  [{run_idx}/{total}] model={model}")
                try:
                    session_id, status = _run_one(
                        recording=rec,
                        model=model,
                        prompt=prompt,
                        agent_url=agent_url,
                        timeout=timeout,
                        commit=commit,
                        discard=discard,
                        stdout_writer=self.stdout.write,
                    )
                except Exception as exc:
                    msg = f"{rec_label}/{model}: {exc}"
                    failures.append(msg)
                    self.stderr.write(self.style.ERROR(f"      FAILED: {msg}"))
                    if not continue_on_error:
                        raise
                    continue

                self.stdout.write(f"      status={status}")
                if status == CowAgentSession.FAILED:
                    failures.append(f"{rec_label}/{model}: agent status FAILED")
                else:
                    succeeded += 1

        if succeeded == 0:
            raise CommandError(
                "Every (recording, model) run failed. Check the agent URL, "
                "model names, and API keys. Failures:\n  - " + "\n  - ".join(failures)
            )

        self.stdout.write(self.style.SUCCESS(f"\n{succeeded}/{total} run(s) succeeded."))
        if failures:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(failures)} run(s) failed:\n  - " + "\n  - ".join(failures)
                )
            )
        self.stdout.write("Run eval_recordings to score the resulting pairs.")


def _truncate(text: str, n: int = 100) -> str:
    text = (text or "").replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _parse_uuid(value: Any) -> Optional[uuid.UUID]:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
