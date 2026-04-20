# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

from __future__ import annotations

import json
from typing import Any

import litellm

from plane_client import PlaneClient
from tools import ENDPOINT_CATALOG, TOOL_SCHEMAS, dispatch


SYSTEM_PROMPT_TEMPLATE = """You are an agent operating on a Plane workspace.

You have ONE primary tool, `plane_request`, which makes raw HTTP calls to
Plane's REST API. Every call automatically carries the user's API token and a
Copy-On-Write session header, so writes stage in shadow tables until the user
explicitly commits. Mistakes are cheap; nothing is destructive unless committed.

The current workspace slug is: `{slug}`

Endpoint catalog:
{catalog}

Guidelines:
- Use `plane_request` for everything. The method + path combination determines
  what happens; pick them from the catalog above.
- Discover ids before acting: e.g. list projects before creating a work item in
  one, list states before changing a work item's state.
- Prefer PATCH with only the fields that need to change.
- If a tool returns {{"error": true, "status": ..., "body": ...}}, surface the
  error; do not retry blindly.
- Keep responses concise. Name what you did and include any ids the user may
  want to reference.
- If the catalog isn't enough, call `get_api_schema` to inspect the OpenAPI
  spec.
"""


def build_system_prompt(workspace_slug: str) -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(slug=workspace_slug, catalog=ENDPOINT_CATALOG)


MAX_TOOL_ROUNDS = 12


def run_turn(
    model: str,
    messages: list[dict[str, Any]],
    client: PlaneClient,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Run one chat turn.

    `messages` is the conversation history (user/assistant/tool). We prepend the
    system prompt if it's not already present. Returns the final assistant text,
    the updated history, and a list of tool-call records for UI display.
    """
    history = list(messages)
    system_prompt = build_system_prompt(client.workspace_slug)
    if not history or history[0].get("role") != "system":
        history = [{"role": "system", "content": system_prompt}] + history
    else:
        history[0] = {"role": "system", "content": system_prompt}

    tool_trace: list[dict[str, Any]] = []

    for _ in range(MAX_TOOL_ROUNDS):
        resp = litellm.completion(
            model=model,
            messages=history,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        choice = resp.choices[0]
        msg = choice.message

        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
        }
        tool_calls = getattr(msg, "tool_calls", None) or []
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ]
        history.append(assistant_msg)

        if not tool_calls:
            return msg.content or "", history, tool_trace

        for tc in tool_calls:
            raw_args = tc.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {}
            result = dispatch(tc.function.name, args, client)
            tool_trace.append(
                {"name": tc.function.name, "args": args, "result": result}
            )
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.function.name,
                    "content": json.dumps(result, default=str),
                }
            )

    return (
        "Stopped after reaching the tool-call round limit.",
        history,
        tool_trace,
    )
