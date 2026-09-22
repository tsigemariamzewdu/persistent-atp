"""Deterministic journals projected with this branch's production projector."""
from __future__ import annotations

from mork.projector.core import project_event_journal


def journal(proof: str, nodes: int, *, claims: bool = False) -> dict:
    """A star: one state proposes moves, or claims depend on a refuted root.

    Fixed-degree leaf probes distinguish lookup cost from growing result size.
    The star also avoids exponential path enumeration in recursive rule queries.
    """
    ops = []
    for i in range(nodes):
        label = "Claim" if claims else ("State" if i == 0 else "Move")
        status = "refuted" if claims and i == 0 else "open"
        ops.append({"op": "upsert_node", "id": f"{proof}/n{i}",
                    "label": label, "fields": {"status": status}})
        if i:
            src, dst = (i, 0) if claims else (0, i)
            ops.append({"op": "add_edge", "edge_id": f"{proof}/e{i}",
                        "rel": "DEPENDS_ON" if claims else "PROPOSES",
                        "src": f"{proof}/n{src}", "dst": f"{proof}/n{dst}"})
    return {"proof_id": proof, "events": [{"revision": 1, "payload": {"ops": ops}}]}


def commands(nodes: int, background: int = 0, *, claims: bool = False) -> list[str]:
    result = project_event_journal(journal("target", nodes, claims=claims))
    # Many unrelated small proofs, with globally distinct proof names.
    for index, start in enumerate(range(0, background, 25)):
        result.extend(project_event_journal(journal(f"bg{index}", min(25, background - start))))
    return result
