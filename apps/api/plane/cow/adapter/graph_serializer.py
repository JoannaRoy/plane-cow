# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""Deterministic JSON serialization for ``agentcow.scoring.CowGraph``.

The output shape is intentionally plain JSON (no framework types) so that
consumers like cow_gym can rehydrate it into a :class:`CowGraph` purely from
the wire payload. Candidate for upstream extraction into
``agentcow.scoring`` once the format stabilizes.
"""

from __future__ import annotations

import base64
import datetime as _dt
import decimal
import uuid
from typing import Any

from agentcow.scoring import CowGraph, CowNode, CowWrite


__all__ = ["serialize_cow_graph", "GRAPH_FORMAT_VERSION"]


# v2 adds the ``edges`` field (transitive dep pairs from
# ``get_cow_dependencies``). v1 consumers can still read v2 payloads — they
# just ignore the new field.
GRAPH_FORMAT_VERSION = "2"


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes_b64__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(v) for v in value]
    return str(value)


def _serialize_write(write: CowWrite) -> dict:
    return {
        "table_name": write.table_name,
        "operation_id": str(write.operation_id),
        "primary_key": _to_jsonable(write.primary_key),
        "data": _to_jsonable(write.data),
        "is_delete": bool(write.is_delete),
        "updated_at": write.updated_at.isoformat() if write.updated_at else None,
    }


def _serialize_node(node: CowNode) -> dict:
    return {
        "operation_id": str(node.op_id),
        "timestamp": node.timestamp.isoformat() if node.timestamp else None,
        "rows": [_serialize_write(row) for row in node.rows],
        "metadata": _to_jsonable(node.metadata) if node.metadata else None,
    }


def _serialize_edges(
    edges: list[tuple[uuid.UUID, uuid.UUID]] | None,
    keep_op_ids: set[str],
) -> list[dict]:
    if not edges:
        return []
    out: list[dict] = []
    for depends_on, op_id in edges:
        from_id = str(depends_on)
        to_id = str(op_id)
        if from_id not in keep_op_ids or to_id not in keep_op_ids:
            continue
        out.append({"from": from_id, "to": to_id})
    out.sort(key=lambda e: (e["from"], e["to"]))
    return out


def serialize_cow_graph(
    graph: CowGraph,
    *,
    session_id: uuid.UUID,
    edges: list[tuple[uuid.UUID, uuid.UUID]] | None = None,
) -> dict:
    """Render ``graph`` as a deterministic JSON-friendly dict.

    Nodes are emitted in (timestamp, op_id) order to match
    ``CowGraph.topologically_sorted_nodes`` so consumers get a stable
    payload regardless of dict insertion order. ``edges`` (transitive
    dependency pairs from ``get_cow_dependencies``) are filtered to those
    referencing nodes in ``graph`` and sorted for stability.
    """
    sorted_nodes = graph.topologically_sorted_nodes()
    keep = {str(node.op_id) for node in sorted_nodes}
    return {
        "format_version": GRAPH_FORMAT_VERSION,
        "session_id": str(session_id),
        "node_count": len(sorted_nodes),
        "nodes": [_serialize_node(node) for node in sorted_nodes],
        "edges": _serialize_edges(edges, keep),
    }
