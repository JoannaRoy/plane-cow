# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from __future__ import annotations

from typing import Any

from plane_client import PlaneClient


ENDPOINT_CATALOG = """\
All paths are relative to `/api/v1/`. `{slug}` is the current workspace slug
(already known to you; you do not need to ask). UUIDs must be discovered by
listing first unless the user supplies them.

Projects
  GET    /workspaces/{slug}/projects/
  POST   /workspaces/{slug}/projects/
  GET    /workspaces/{slug}/projects/{project_id}/
  PATCH  /workspaces/{slug}/projects/{project_id}/
  DELETE /workspaces/{slug}/projects/{project_id}/
  POST   /workspaces/{slug}/projects/{project_id}/archive/
  DELETE /workspaces/{slug}/projects/{project_id}/archive/
  GET    /workspaces/{slug}/projects/{project_id}/summary/

Work items (aka issues)
  GET    /workspaces/{slug}/projects/{project_id}/work-items/
  POST   /workspaces/{slug}/projects/{project_id}/work-items/
  GET    /workspaces/{slug}/projects/{project_id}/work-items/{work_item_id}/
  PATCH  /workspaces/{slug}/projects/{project_id}/work-items/{work_item_id}/
  DELETE /workspaces/{slug}/projects/{project_id}/work-items/{work_item_id}/
  GET    /workspaces/{slug}/work-items/search/?search=...
  GET    /workspaces/{slug}/work-items/{project_identifier}-{issue_identifier}/

Work item sub-resources (links, comments, activities, attachments, relations)
  .../work-items/{work_item_id}/links/
  .../work-items/{work_item_id}/comments/
  .../work-items/{work_item_id}/activities/      (read-only)
  .../work-items/{work_item_id}/attachments/
  .../work-items/{work_item_id}/relations/

States, labels, members
  /workspaces/{slug}/projects/{project_id}/states/[<state_id>/]
  /workspaces/{slug}/projects/{project_id}/labels/[<pk>/]
  /workspaces/{slug}/projects/{project_id}/members/[<pk>/]
  /workspaces/{slug}/members/                   (workspace members, GET)

Cycles and modules (each has a list, detail, issue-assignment, archive)
  /workspaces/{slug}/projects/{project_id}/cycles/[<pk>/]
  /workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/cycle-issues/[<issue_id>/]
  /workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/transfer-issues/
  /workspaces/{slug}/projects/{project_id}/cycles/{cycle_id}/archive/
  /workspaces/{slug}/projects/{project_id}/modules/[<pk>/]
  /workspaces/{slug}/projects/{project_id}/modules/{module_id}/module-issues/[<issue_id>/]
  /workspaces/{slug}/projects/{project_id}/modules/{pk}/archive/

Intake, estimates, invites, stickies, assets
  /workspaces/{slug}/projects/{project_id}/intake-issues/[<issue_id>/]
  /workspaces/{slug}/projects/{project_id}/estimates/[<estimate_id>/estimate-points/[<id>/]]
  /workspaces/{slug}/invitations/   (invites)
  /workspaces/{slug}/stickies/
  /workspaces/{slug}/assets/[<asset_id>/]

User
  /users/me/

Full machine-readable schema is available via the `get_api_schema` tool.
"""


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS: list[dict] = [
    _fn(
        "plane_request",
        (
            "Make an arbitrary HTTP call to Plane's REST API. Use this for every "
            "action: listing, creating, updating, deleting anything. The request "
            "automatically carries the workspace's API token and the COW session "
            "header, so writes stay in shadow tables until the user commits."
        ),
        {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PATCH", "PUT", "DELETE"],
            },
            "path": {
                "type": "string",
                "description": (
                    "Path starting with '/api/v1/' (e.g. "
                    "'/api/v1/workspaces/acme/projects/'). You can use either "
                    "absolute form ('/api/v1/...') or just the bit after "
                    "'/api/v1/' ('workspaces/acme/...'); both are accepted."
                ),
            },
            "body": {
                "type": "object",
                "description": "JSON body for POST/PATCH/PUT. Omit for GET/DELETE.",
            },
            "params": {
                "type": "object",
                "description": "Query-string params, as a flat object.",
            },
        },
        ["method", "path"],
    ),
    _fn(
        "get_api_schema",
        (
            "Fetch Plane's OpenAPI schema (drf-spectacular) so you can look up "
            "exact request/response shapes. Expensive; only call when the "
            "endpoint catalog in the system prompt isn't enough."
        ),
        {
            "tag": {
                "type": "string",
                "description": (
                    "Optional filter: if given, only paths whose tags include "
                    "this string are returned. Otherwise the full schema comes "
                    "back (can be large)."
                ),
            }
        },
        [],
    ),
]


def _normalize_path(path: str) -> str:
    if path.startswith("/api/v1/"):
        return path
    if path.startswith("api/v1/"):
        return "/" + path
    if path.startswith("/"):
        return "/api/v1" + path
    return "/api/v1/" + path


def _plane_request(
    c: PlaneClient,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    **_: Any,
) -> Any:
    return c.request(
        method.upper(),
        _normalize_path(path),
        params=params,
        json=body,
    )


def _get_api_schema(c: PlaneClient, tag: str | None = None, **_: Any) -> Any:
    schema = c.request("GET", "/api/schema/")
    if not isinstance(schema, dict) or "paths" not in schema:
        return schema
    if tag is None:
        return {
            "info": schema.get("info", {}),
            "paths": list(schema.get("paths", {}).keys()),
            "note": (
                "This is the path list only. Call get_api_schema with no tag to "
                "get everything, but the endpoint catalog in the system prompt "
                "is usually enough."
            ),
        }
    tag_lower = tag.lower()
    matching: dict[str, Any] = {}
    for path, ops in schema.get("paths", {}).items():
        for method, op in ops.items():
            tags = [t.lower() for t in op.get("tags", [])]
            if any(tag_lower in t for t in tags):
                matching.setdefault(path, {})[method] = op
    return {"filter": tag, "paths": matching}


DISPATCH = {
    "plane_request": _plane_request,
    "get_api_schema": _get_api_schema,
}


def dispatch(name: str, args: dict[str, Any], client: PlaneClient) -> Any:
    fn = DISPATCH.get(name)
    if fn is None:
        return {"error": True, "message": f"unknown tool: {name}"}
    return fn(client, **args)
