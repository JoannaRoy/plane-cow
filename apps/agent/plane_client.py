# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from __future__ import annotations

import uuid
from typing import Any

import httpx


class PlaneClient:
    """Thin HTTP client for Plane's /api/v1/ that injects the COW session header.

    Every call adds ``x-agent-session-id: <session_id>``, which makes plane-cow
    stage writes in shadow tables until explicitly committed.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        workspace_slug: str,
        session_id: uuid.UUID | str,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.workspace_slug = workspace_slug
        self.session_id = str(session_id)
        self._token = token
        self._client = httpx.Client(
            timeout=30.0,
            headers={
                "X-Api-Key": token,
                "x-agent-session-id": self.session_id,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "PlaneClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        operation_id = str(uuid.uuid4())
        resp = self._client.request(
            method,
            url,
            params=params,
            json=json,
            headers={"x-operation-id": operation_id},
        )
        if resp.status_code >= 400:
            return {
                "error": True,
                "status": resp.status_code,
                "body": _safe_json(resp),
            }
        if not resp.content:
            return {"ok": True}
        return _safe_json(resp)

    def ws_path(self, suffix: str) -> str:
        return f"/api/v1/workspaces/{self.workspace_slug}{suffix}"


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"text": resp.text}


def fetch_pending_operations(
    base_url: str, token: str, session_id: str
) -> dict[str, Any]:
    """Hit /api/cow/sessions/<id>/operations/ to see what's staged.

    Returns the raw JSON so the UI can display a count and (optionally) table names.
    """
    url = f"{base_url.rstrip('/')}/api/cow/sessions/{session_id}/operations/"
    resp = httpx.get(
        url,
        headers={"X-Api-Key": token},
        timeout=15.0,
    )
    if resp.status_code >= 400:
        return {
            "error": True,
            "status": resp.status_code,
            "body": _safe_json(resp),
        }
    return _safe_json(resp)


def commit_session(base_url: str, token: str, session_id: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/cow/commit/"
    resp = httpx.post(
        url,
        headers={"X-Api-Key": token, "Content-Type": "application/json"},
        json={"session_id": session_id},
        timeout=60.0,
    )
    if resp.status_code >= 400:
        return {
            "error": True,
            "status": resp.status_code,
            "body": _safe_json(resp),
        }
    return _safe_json(resp)


def discard_session(base_url: str, token: str, session_id: str) -> dict[str, Any]:
    ops = fetch_pending_operations(base_url, token, session_id)
    operation_ids = ops.get("operation_ids", []) if isinstance(ops, dict) else []
    if not operation_ids:
        return {"session_id": session_id, "operation_ids": [], "discarded_tables": []}

    url = f"{base_url.rstrip('/')}/api/cow/operations/discard/"
    resp = httpx.post(
        url,
        headers={"X-Api-Key": token, "Content-Type": "application/json"},
        json={"session_id": session_id, "operation_ids": operation_ids},
        timeout=60.0,
    )
    if resp.status_code >= 400:
        return {
            "error": True,
            "status": resp.status_code,
            "body": _safe_json(resp),
        }
    return _safe_json(resp)
