# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from llm import run_turn
from plane_client import (
    PlaneClient,
    commit_session,
    discard_session,
    fetch_pending_operations,
)


load_dotenv()

PLANE_BASE_URL = os.environ.get("PLANE_BASE_URL", "http://localhost:8000")
PLANE_API_TOKEN = os.environ.get("PLANE_API_TOKEN", "")
PLANE_WORKSPACE_SLUG = os.environ.get("PLANE_WORKSPACE_SLUG", "")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="plane-cow chat agent")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    model: str
    session_id: str
    messages: list[dict[str, Any]]


class ChatResponse(BaseModel):
    assistant: str
    messages: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    pending_ops: dict[str, Any]


class SessionRequest(BaseModel):
    session_id: str


def _require_config() -> None:
    missing = []
    if not PLANE_API_TOKEN:
        missing.append("PLANE_API_TOKEN")
    if not PLANE_WORKSPACE_SLUG:
        missing.append("PLANE_WORKSPACE_SLUG")
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Missing env vars: {', '.join(missing)}",
        )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config")
def config() -> dict[str, Any]:
    return {
        "plane_base_url": PLANE_BASE_URL,
        "workspace_slug": PLANE_WORKSPACE_SLUG,
        "has_token": bool(PLANE_API_TOKEN),
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    _require_config()
    with PlaneClient(
        PLANE_BASE_URL, PLANE_API_TOKEN, PLANE_WORKSPACE_SLUG, req.session_id
    ) as client:
        assistant, history, trace = run_turn(req.model, req.messages, client)

    pending = fetch_pending_operations(PLANE_BASE_URL, PLANE_API_TOKEN, req.session_id)
    return ChatResponse(
        assistant=assistant,
        messages=history,
        tool_trace=trace,
        pending_ops=pending if isinstance(pending, dict) else {"raw": pending},
    )


@app.post("/commit")
def commit(req: SessionRequest) -> dict[str, Any]:
    _require_config()
    return commit_session(PLANE_BASE_URL, PLANE_API_TOKEN, req.session_id)


@app.post("/discard")
def discard(req: SessionRequest) -> dict[str, Any]:
    _require_config()
    return discard_session(PLANE_BASE_URL, PLANE_API_TOKEN, req.session_id)


@app.get("/pending")
def pending(session_id: str) -> dict[str, Any]:
    _require_config()
    result = fetch_pending_operations(PLANE_BASE_URL, PLANE_API_TOKEN, session_id)
    return result if isinstance(result, dict) else {"raw": result}
