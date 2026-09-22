"""Shared, backend-independent contract for the PTPS E1--E6 comparison.

The dictionary implementation in this module is a correctness oracle, not a
fourth measured backend. Every backend sees the same logical graph and returns
the same information. Nodes are implicitly in the committed layer. Identifiers
are local to a proof, and all fixture fields have scalar string/integer values.

E6 is special: ``Case.graph`` is the expected *final* graph, ``journal`` is a
sequence applied to an empty graph, and ``operations`` is empty. For E1--E5,
``graph`` is the initial fixture and each case has one measured operation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Iterable


EXPERIMENTS = {
    "E1": "Individual graph reads and genuine mutations",
    "E2": "Growth within the target proof, with fixed-size answers",
    "E3": "Growth of unrelated proofs, with an unchanged target proof",
    "E4": "Eligible frontier queries, varying candidates and selectivity",
    "E5": "Dependency impact on stars, chains, and reconvergent DAGs",
    "E6": "Rebuild a queryable graph from a common operation journal",
}
MUTATIONS = frozenset({
    "create_node", "insert_field", "overwrite_field", "add_edge", "remove_edge",
})
INTERNAL_OPERATIONS = frozenset({"delete_node", "delete_field"})


@dataclass(frozen=True)
class Operation:
    name: str
    args: dict

    def as_dict(self) -> dict:
        return {"name": self.name, "args": deepcopy(self.args)}


@dataclass
class Case:
    experiment: str
    key: str
    scale: int
    graph: dict
    operations: list[Operation]
    journal: list[dict] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.graph["nodes"])

    @property
    def edge_count(self) -> int:
        return len(self.graph["edges"])


def canonical_graph(graph: dict) -> dict:
    """Deep-copy a graph into a stable, JSON-serializable representation."""
    return {
        "nodes": [
            {"proof": n["proof"], "id": n["id"], "label": n["label"],
             "fields": dict(sorted(n["fields"].items()))}
            for n in sorted(graph["nodes"], key=lambda n: (n["proof"], n["id"]))
        ],
        "edges": [dict(e) for e in sorted(
            graph["edges"], key=lambda e: (e["proof"], e["id"]))],
    }


def normalize_result(operation: Operation | str, result: Any) -> Any:
    """Ignore answer ordering while retaining the exact returned information."""
    name = operation if isinstance(operation, str) else operation.name
    if name in {"frontier", "taint"}:
        # Do not silently deduplicate: duplicate answers are a correctness error.
        return sorted(result)
    if name in {"incoming", "outgoing"}:
        return sorted([list(row) for row in result])
    if name in {"node", "missing_node"} and result is not None:
        return [result[0], result[1], sorted([list(row) for row in result[2]])]
    return result


class Oracle:
    """Small deterministic model of the agreed operations and their effects."""

    def __init__(self, graph: dict | None = None):
        self.load(graph or {"nodes": [], "edges": []})

    def load(self, graph: dict) -> None:
        self.nodes: dict[tuple[str, str], dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}
        for node in graph["nodes"]:
            key = node["proof"], node["id"]
            if key in self.nodes:
                raise ValueError(f"Duplicate node: {key}")
            self.nodes[key] = deepcopy(node)
        for edge in graph["edges"]:
            key = edge["proof"], edge["id"]
            if key in self.edges:
                raise ValueError(f"Duplicate edge: {key}")
            self._require_endpoints(edge)
            self.edges[key] = deepcopy(edge)

    def _require_endpoints(self, edge: dict) -> None:
        for endpoint in (edge["src"], edge["dst"]):
            if (edge["proof"], endpoint) not in self.nodes:
                raise ValueError(f"Missing endpoint: {(edge['proof'], endpoint)}")

    def snapshot(self) -> dict:
        return canonical_graph({"nodes": list(self.nodes.values()),
                                "edges": list(self.edges.values())})

    def execute(self, operation: Operation | dict) -> Any:
        if isinstance(operation, dict):
            operation = Operation(**operation)
        name, args = operation.name, operation.args
        proof, entity = args["proof"], args["id"]
        key = proof, entity
        if name in {"node", "missing_node"}:
            node = self.nodes.get(key)
            return None if node is None else [
                node["id"], node["label"],
                [[k, v] for k, v in sorted(node["fields"].items())],
            ]
        if name in {"incoming", "outgoing"}:
            endpoint = "dst" if name == "incoming" else "src"
            return sorted([
                [e["id"], e["rel"], e["src"], e["dst"]]
                for e in self.edges.values()
                if e["proof"] == proof and e[endpoint] == entity
                and e["rel"] == args["rel"]
            ])
        if name == "frontier":
            state = self.nodes.get(key)
            if state is None or state["fields"].get("status") in {
                "tainted", "formally-closed",
            }:
                return []
            answer = set()
            for edge in self.edges.values():
                if (edge["proof"] != proof or edge["src"] != entity
                        or edge["rel"] != "PROPOSES"):
                    continue
                node = self.nodes[proof, edge["dst"]]
                if node["label"] == "Move" and node["fields"].get("status") in {
                    "open", "reopened",
                }:
                    answer.add(node["id"])
            return sorted(answer)
        if name == "taint":
            root = self.nodes.get(key)
            if root is None or root["fields"].get("status") != "refuted":
                return []
            reverse = defaultdict(list)
            for edge in self.edges.values():
                if edge["proof"] == proof and edge["rel"] == "DEPENDS_ON":
                    reverse[edge["dst"]].append(edge["src"])
            pending, visited = deque([entity]), {entity}
            while pending:
                for dependent in reverse[pending.popleft()]:
                    if dependent not in visited:
                        visited.add(dependent)
                        pending.append(dependent)
            return sorted(n for n in visited if n != entity
                          and self.nodes[proof, n]["label"] == "Claim")
        if name == "create_node":
            if key in self.nodes:
                raise ValueError(f"Creation would be a no-op: {key}")
            self.nodes[key] = {"proof": proof, "id": entity, "label": args["label"],
                               "fields": deepcopy(args["fields"])}
        elif name in {"insert_field", "overwrite_field"}:
            fields = self.nodes[key]["fields"]
            name_exists = args["field"] in fields
            if name == "insert_field" and name_exists:
                raise ValueError(f"Field insertion would overwrite: {key}")
            if name == "overwrite_field" and not name_exists:
                raise ValueError(f"Field overwrite would insert: {key}")
            if name_exists and fields[args["field"]] == args["value"]:
                raise ValueError(f"Field update would be a no-op: {key}")
            fields[args["field"]] = deepcopy(args["value"])
        elif name == "add_edge":
            if key in self.edges:
                raise ValueError(f"Edge insertion would be a no-op: {key}")
            edge = {k: args[k] for k in ("proof", "id", "rel", "src", "dst")}
            self._require_endpoints(edge)
            self.edges[key] = edge
        elif name == "remove_edge":
            del self.edges[key]
        elif name == "delete_node":
            if any(e["proof"] == proof and entity in (e["src"], e["dst"])
                   for e in self.edges.values()):
                raise ValueError("Fixture reset must remove incident edges first")
            del self.nodes[key]
        elif name == "delete_field":
            del self.nodes[key]["fields"][args["field"]]
        else:
            raise ValueError(f"Unknown shared operation: {name}")
        return True

    def apply_journal(self, journal: Iterable[dict]) -> dict:
        for operation in journal:
            self.execute(operation)
        return self.snapshot()


def expected_result(operation: Operation, graph: dict) -> Any:
    """Evaluate independently on a fresh copy, leaving the fixture untouched."""
    return Oracle(graph).execute(operation)


def inverse_operations(operation: Operation, graph: dict) -> list[Operation]:
    """Unmeasured restoration after one genuine mutation of the base graph.

    These resets are not benchmark operations. The runner must wait for the
    reset to finish before the next timed call and validate the restored graph.
    """
    name, args = operation.name, operation.args
    proof, entity = args["proof"], args["id"]
    basic = {"proof": proof, "id": entity}
    if name == "create_node":
        return [Operation("delete_node", basic)]
    if name == "insert_field":
        return [Operation("delete_field", {**basic, "field": args["field"]})]
    if name == "overwrite_field":
        node = next(n for n in graph["nodes"]
                    if (n["proof"], n["id"]) == (proof, entity))
        return [Operation("overwrite_field", {
            **basic, "field": args["field"], "value": node["fields"][args["field"]],
        })]
    if name == "add_edge":
        return [Operation("remove_edge", basic)]
    if name == "remove_edge":
        edge = next(e for e in graph["edges"]
                    if (e["proof"], e["id"]) == (proof, entity))
        return [Operation("add_edge", deepcopy(edge))]
    return []


def mutation_check(operation, graph):
    a = operation.args
    if operation.name in ('create_node', 'insert_field', 'overwrite_field'):
        return Operation('node', {'proof': a['proof'], 'id': a['id']})
    if operation.name in ('add_edge', 'remove_edge'):
        edge = a if operation.name == 'add_edge' else next(e for e in graph['edges']
            if e['proof'] == a['proof'] and e['id'] == a['id'])
        return Operation('outgoing', {'proof': a['proof'], 'id': edge['src'], 'rel': edge['rel']})
    return None


def _node(index: int, *, proof: str = "target", label: str = "Move",
          status: str = "open", depth: int = 1) -> dict:
    return {"proof": proof, "id": f"n{index}", "label": label,
            "fields": {"status": status, "depth": depth}}


def _edge(index: int, source: int, destination: int, *, proof: str = "target",
          relation: str = "PROPOSES") -> dict:
    return {"proof": proof, "id": f"e{index}", "rel": relation,
            "src": f"n{source}", "dst": f"n{destination}"}


def basic_graph(size: int, proof: str = "target") -> dict:
    """Star plus one SUPPORTS edge: n1 always has one incoming/outgoing answer."""
    if size < 4:
        raise ValueError("Basic fixtures require at least four nodes")
    nodes = [_node(i, proof=proof, label="State" if i == 0 else "Move",
                   depth=0 if i == 0 else 1) for i in range(size)]
    edges = [_edge(i, 0, i, proof=proof) for i in range(1, size)]
    support = _edge(size, 1, 2, proof=proof, relation="SUPPORTS")
    support["id"] = "support0"
    edges.append(support)
    return {"nodes": nodes, "edges": edges}


def frontier_graph(candidates: int, eligibility_percent: int) -> dict:
    eligible = candidates * eligibility_percent // 100
    nodes = [_node(0, label="State", depth=0)]
    nodes.extend(_node(i, status=("open" if i % 2 else "reopened")
                       if i <= eligible else ("leased" if i % 2 else "exhausted"))
                 for i in range(1, candidates + 1))
    return {"nodes": nodes,
            "edges": [_edge(i, 0, i) for i in range(1, candidates + 1)]}


def dependency_graph(size: int, shape: str) -> dict:
    """Claim DAGs with exact reachable sets; reconvergence has bounded depth.

    In the diamond case n1 and n2 depend on n0, while every remaining claim
    depends on both n1 and n2. Thus each leaf has two paths to n0, without the
    exponential path explosion of repeatedly chained diamonds.
    """
    if size < 4:
        raise ValueError("Dependency fixtures require at least four claims")
    nodes = [_node(i, label="Claim", status="refuted" if i == 0 else "open",
                   depth=i if shape == "chain" else (0 if i == 0 else 1))
             for i in range(size)]
    edges = []
    for index in range(1, size):
        if shape == "star":
            targets = [0]
        elif shape == "chain":
            targets = [index - 1]
        elif shape == "diamond":
            targets = [0] if index <= 2 else [1, 2]
            nodes[index]["fields"]["depth"] = 1 if index <= 2 else 2
        else:
            raise ValueError(f"Unknown dependency shape: {shape}")
        for target in targets:
            edges.append(_edge(len(edges) + 1, index, target, relation="DEPENDS_ON"))
    return {"nodes": nodes, "edges": edges}


def _probes() -> list[Operation]:
    entity = {"proof": "target", "id": "n1"}
    return [
        Operation("node", dict(entity)),
        Operation("missing_node", {"proof": "target", "id": "missing"}),
        Operation("incoming", {**entity, "rel": "PROPOSES"}),
        Operation("outgoing", {**entity, "rel": "SUPPORTS"}),
        Operation("create_node", {"proof": "target", "id": "new-node",
                                 "label": "Move", "fields": {"status": "open", "depth": 1}}),
        Operation("insert_field", {**entity, "field": "score", "value": 7}),
        Operation("overwrite_field", {**entity, "field": "status", "value": "leased"}),
        Operation("add_edge", {"proof": "target", "id": "new-edge", "rel": "SUPPORTS",
                              "src": "n1", "dst": "n3"}),
        Operation("remove_edge", {"proof": "target", "id": "e1"}),
    ]


def rebuild_journal(size: int) -> tuple[list[dict], dict]:
    """History contains creation, field overwrites, and real edge removals."""
    graph = basic_graph(size)
    operations = [Operation("create_node", dict(node)) for node in graph["nodes"]]
    operations.extend(Operation("add_edge", dict(edge)) for edge in graph["edges"])
    operations.extend(Operation("overwrite_field", {
        "proof": "target", "id": f"n{i}", "field": "status", "value": "leased",
    }) for i in range(1, size, 10))
    operations.extend(Operation("remove_edge", {
        "proof": "target", "id": f"e{i}",
    }) for i in range(1, size, 20))
    journal = [op.as_dict() for op in operations]
    return journal, Oracle().apply_journal(journal)


def generate_cases(quick: bool = False,
                   scales: tuple[int, ...] = (100, 1000, 10000)) -> list[Case]:
    """Return 51 full cases (37 quick cases) using the documented E1--E6 contract.

    Quick mode retains all nine primitive operations, all selectivities and all
    dependency shapes, using scales 10/100 and backgrounds 0/100. ``scale`` means
    total target nodes except E3 (background nodes) and E4 (candidate moves).
    E6 scale is created nodes; journal operations and final graph size are also
    available explicitly and must be reported instead of conflating the counts.
    """
    sizes = (10, 100) if quick else scales
    if not sizes or any(size < 4 for size in sizes):
        raise ValueError("Scales must contain node counts of at least four")
    cases: list[Case] = []
    base_size = 100 if quick else 1000
    base = basic_graph(base_size)
    for operation in _probes():
        cases.append(Case("E1", f"E1_{operation.name}", base_size, base, [operation]))
    for size in sizes:
        graph = basic_graph(size)
        for operation in _probes():
            if operation.name in {"node", "incoming", "outgoing", "overwrite_field"}:
                cases.append(Case("E2", f"E2_{operation.name}_{size}", size, graph, [operation]))
    for background in ((0, 100) if quick else (0, 1000, 10000)):
        graph = basic_graph(100)
        for index, start in enumerate(range(0, background, 100)):
            part = basic_graph(min(100, background - start), proof=f"background{index}")
            graph["nodes"].extend(part["nodes"])
            graph["edges"].extend(part["edges"])
        for operation in _probes():
            if operation.name in {"node", "incoming", "outgoing"}:
                cases.append(Case("E3", f"E3_{operation.name}_{background}", background,
                                  graph, [operation]))
    for size in sizes:
        for percent in (10, 50, 90):
            cases.append(Case("E4", f"E4_frontier_{size}_{percent}pct", size,
                              frontier_graph(size, percent),
                              [Operation("frontier", {"proof": "target", "id": "n0"})]))
        for shape in ("star", "chain", "diamond"):
            cases.append(Case("E5", f"E5_taint_{shape}_{size}", size,
                              dependency_graph(size, shape),
                              [Operation("taint", {"proof": "target", "id": "n0"})]))
        journal, final_graph = rebuild_journal(size)
        cases.append(Case("E6", f"E6_rebuild_{size}", size, final_graph, [], journal))
    return cases
