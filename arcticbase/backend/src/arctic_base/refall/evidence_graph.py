from __future__ import annotations


def graph_from_deltas(deltas: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    for delta in deltas:
        operation = delta.get("operation")
        if operation == "upsert_node":
            node_id = str(delta.get("node_id"))
            nodes[node_id] = {
                "id": node_id,
                "type": delta.get("node_type"),
                "properties": delta.get("properties") or {},
            }
        elif operation == "upsert_edge":
            edges.append(delta)
    return {"nodes": list(nodes.values()), "edges": edges}
