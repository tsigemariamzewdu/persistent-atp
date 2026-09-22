"""Canonical PTPS benchmark operations through the production Neo4j transactions.

The public adapter's frontier returns full, sorted, proof-wide records. The
benchmark contract is state-scoped IDs, so this module deliberately uses native
Cypher through the same managed-transaction layer. Every fixture has both an
unpredictable owner token and remapped proof namespaces. No global delete/reset
is used. Native Neo4j transaction commit and Bolt transport are part of execute.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import uuid4


LABELS = ("State", "Move", "Claim")
RELATIONS = ("PROPOSES", "DEPENDS_ON", "SUPPORTS")
INTERNAL_PROPERTIES = {"id", "proof_id", "benchmark_run", "layer"}


def _label(value):
    if value not in LABELS:
        raise ValueError(f"Unsupported benchmark label: {value!r}")
    return value


def _relation(value):
    if value not in RELATIONS:
        raise ValueError(f"Unsupported benchmark relationship: {value!r}")
    return value


def _fields(fields):
    if INTERNAL_PROPERTIES.intersection(fields):
        raise ValueError("Canonical fields may not overwrite fixture identity or ownership")
    if any(value is None or not isinstance(value, (str, int, float, bool))
           for value in fields.values()):
        raise ValueError("Benchmark fields must be non-null scalar values")
    return dict(fields)


def _lookup(alias="n", parameter="id"):
    """Three native composite-index seeks; do not assume the requested label."""
    clauses = [
        f"MATCH ({alias}:{label} {{proof_id: $pid, id: ${parameter}}}) "
        f"WHERE {alias}.benchmark_run = $token RETURN {alias}"
        for label in LABELS
    ]
    return "CALL { " + " UNION ALL ".join(clauses) + " } "


class Neo4jBackend:
    name = "neo4j"

    def __init__(self, adapter=None, *, verify_schema=True):
        self._owns_adapter = adapter is None
        if adapter is None:
            from neo4j_adapter.adapter import Neo4jAdapter
            adapter = Neo4jAdapter()
        self.adapter = adapter
        self.token = uuid4().hex
        self.proofs = {}
        self._closed = False
        self.metadata = {
            "backend": self.name,
            "fixture_owner": self.token,
            "transactions": "production adapter managed read/write transaction per operation",
            "mutation_acknowledgement": "native Neo4j transaction committed",
            "representation": "native nodes/properties/relationships; committed layer property",
            "lookup_indexes": "State/Move/Claim composite (proof_id,id) unique indexes",
        }
        if verify_schema:
            try:
                self._inspect_schema()
            except BaseException:
                if self._owns_adapter:
                    self.adapter.close()
                raise

    def _inspect_schema(self):
        self.metadata["server"] = self.adapter._read(
            "benchmark_server", lambda tx: [dict(record) for record in tx.run(
                "CALL dbms.components() YIELD name, versions, edition "
                "RETURN name, versions, edition")])
        self.adapter._read("benchmark_await_indexes", lambda tx: list(tx.run(
            "CALL db.awaitIndexes(60)")))
        indexes = self.adapter._read("benchmark_indexes", lambda tx: [
            dict(record) for record in tx.run(
                "SHOW INDEXES YIELD name, type, entityType, labelsOrTypes, properties, state "
                "RETURN name, type, entityType, labelsOrTypes, properties, state")])
        required = {(label, ("proof_id", "id")) for label in LABELS}
        online = {(label, tuple(row["properties"])) for row in indexes
                  if row["entityType"] == "NODE" and row["state"] == "ONLINE"
                  and row.get("properties") and row.get("labelsOrTypes")
                  for label in row["labelsOrTypes"]}
        missing = required - online
        if missing:
            raise RuntimeError(f"Neo4j benchmark requires online native indexes: {sorted(missing)}")
        self.metadata["indexes"] = indexes

    def _proof(self, proof):
        if not isinstance(proof, str) or not proof:
            raise ValueError("A nonempty proof namespace is required")
        if proof not in self.proofs:
            self.proofs[proof] = f"ptps-bench-{self.token}-{proof}"
            self.metadata["proof_namespaces"] = dict(self.proofs)
        return self.proofs[proof]

    def _params(self, args):
        if self._closed:
            raise RuntimeError("Neo4j benchmark backend is closed")
        return {**args, "pid": self._proof(args["proof"]), "token": self.token}

    def _read(self, name, query, params, default=None):
        return self.adapter._read_value(
            f"benchmark_{name}", query, params, "value", default=default)

    def _mutate(self, name, query, params):
        def work(tx):
            record = tx.run(query, **params).single()
            changed = record["changed"] if record else 0
            if changed != 1:
                # Raised inside the managed transaction: abort a malformed write.
                raise RuntimeError(f"{name} changed {changed} entities; expected exactly one")
            return True
        return self.adapter._write(f"benchmark_{name}", work)

    def load(self, graph):
        """Replace this backend's fixture; graph creation is outside query timing."""
        if self._closed:
            raise RuntimeError("Neo4j benchmark backend is closed")
        # Validate before clearing an existing fixture or issuing any writes.
        nodes = defaultdict(list)
        seen_nodes = set()
        node_labels = {}
        seen_edges = set()
        for row in graph["nodes"]:
            key = row["proof"], row["id"]
            if key in seen_nodes:
                raise ValueError(f"Duplicate canonical node: {key}")
            seen_nodes.add(key)
            label = _label(row["label"])
            node_labels[key] = label
            nodes[label].append({**_fields(row["fields"]), "id": row["id"],
                                 "proof_id": self._proof(row["proof"]),
                                 "benchmark_run": self.token, "layer": "committed"})
        edges = defaultdict(list)
        for row in graph["edges"]:
            key = row["proof"], row["id"]
            if key in seen_edges:
                raise ValueError(f"Duplicate canonical edge: {key}")
            seen_edges.add(key)
            if any((row["proof"], row[endpoint]) not in seen_nodes for endpoint in ("src", "dst")):
                raise ValueError(f"Edge has an absent or cross-proof endpoint: {key}")
            group = (_relation(row["rel"]), node_labels[row["proof"], row["src"]],
                     node_labels[row["proof"], row["dst"]])
            edges[group].append({**row, "pid": self._proof(row["proof"])})
        self.clear()
        statements = []
        for label, rows in nodes.items():
            statements.append((f"UNWIND $rows AS row CREATE (n:{label}) SET n = row", {"rows": rows}))
        for (relation, source_label, destination_label), rows in edges.items():
            # Known endpoint labels make bulk fixture creation use identity indexes.
            statements.append((
                "UNWIND $rows AS row "
                f"MATCH (s:{source_label} {{proof_id:row.pid,id:row.src}}), "
                f"(d:{destination_label} {{proof_id:row.pid,id:row.dst}}) "
                "WHERE s.benchmark_run = $token AND d.benchmark_run = $token "
                f"CREATE (s)-[:{relation} {{edge_id: row.id, proof_id: row.pid, "
                "benchmark_run: $token}]->(d)", {"rows": rows, "token": self.token}))
        if statements:
            self.adapter._write_all("benchmark_load", statements)
        actual = self.counts()
        expected = {"nodes": len(seen_nodes), "edges": len(seen_edges)}
        if actual != expected:
            raise RuntimeError(f"Neo4j fixture counts differ: {actual} != {expected}")
        self.metadata["physical_counts"] = actual
        self.metadata["proof_namespaces"] = dict(self.proofs)

    def execute(self, operation):
        name, args = operation.name, operation.args
        params = self._params(args)
        if name in ("node", "missing_node"):
            record = self._read(name, _lookup() +
                "RETURN {id:n.id, labels:labels(n), properties:properties(n)} AS value", params)
            if record is None:
                return None
            labels = [label for label in record["labels"] if label in LABELS]
            if len(labels) != 1:
                raise RuntimeError(f"Expected one canonical node label: {labels}")
            fields = [[key, value] for key, value in sorted(record["properties"].items())
                      if key not in INTERNAL_PROPERTIES]
            return [record["id"], labels[0], fields]
        if name in ("incoming", "outgoing"):
            relation = _relation(args["rel"])
            match = (f"MATCH (s)-[r:{relation}]->(n) " if name == "incoming"
                     else f"MATCH (n)-[r:{relation}]->(d) ")
            other = "s" if name == "incoming" else "d"
            result = "[r.edge_id,type(r),s.id,n.id]" if name == "incoming" else "[r.edge_id,type(r),n.id,d.id]"
            return self._read(name, _lookup() + match +
                f"WHERE {other}.proof_id = $pid AND {other}.benchmark_run = $token "
                "AND r.proof_id = $pid AND r.benchmark_run = $token "
                f"RETURN collect({result}) AS value", params, [])
        if name == "frontier":
            return self._read(name,
                "MATCH (st:State {proof_id:$pid,id:$id})-[r:PROPOSES]->(m:Move {proof_id:$pid}) "
                "WHERE st.benchmark_run=$token AND m.benchmark_run=$token "
                "AND r.benchmark_run=$token AND r.proof_id=$pid "
                "AND st.layer='committed' AND m.layer='committed' "
                "AND NOT st.status IN ['tainted','formally-closed'] "
                "AND m.status IN ['open','reopened'] RETURN collect(DISTINCT m.id) AS value", params, [])
        if name == "taint":
            return self._read(name,
                "MATCH (root:Claim {proof_id:$pid,id:$id}) "
                "WHERE root.benchmark_run=$token AND root.layer='committed' AND root.status='refuted' "
                "MATCH (root)<-[:DEPENDS_ON*1.. {benchmark_run:$token,proof_id:$pid}]-(c:Claim {proof_id:$pid}) "
                "WHERE c.benchmark_run=$token AND c.layer='committed' AND c <> root "
                "RETURN collect(DISTINCT c.id) AS value", params, [])
        if name == "create_node":
            label = _label(args["label"])
            properties = {**_fields(args["fields"]), "proof_id": params["pid"], "id": args["id"],
                          "benchmark_run": self.token, "layer": "committed"}
            return self._mutate(name, f"CREATE (n:{label}) SET n=$properties RETURN count(n) AS changed",
                                {**params, "properties": properties})
        if name in ("insert_field", "overwrite_field", "delete_field"):
            field = args["field"]
            if field in INTERNAL_PROPERTIES:
                raise ValueError("Cannot mutate fixture identity or ownership")
            value = None if name == "delete_field" else _fields({field: args["value"]})[field]
            return self._mutate(name, _lookup() + "SET n += $patch RETURN count(n) AS changed",
                                {**params, "patch": {field: value}})
        if name == "add_edge":
            relation = _relation(args["rel"])
            return self._mutate(name, _lookup("s", "src") + _lookup("d", "dst") +
                f"CREATE (s)-[r:{relation} {{edge_id:$id,proof_id:$pid,benchmark_run:$token}}]->(d) "
                "RETURN count(r) AS changed", params)
        if name == "remove_edge":
            return self._mutate(name,
                "MATCH (s)-[r]->(d) WHERE s.proof_id=$pid AND d.proof_id=$pid "
                "AND s.benchmark_run=$token AND d.benchmark_run=$token "
                "AND r.proof_id=$pid AND r.benchmark_run=$token AND r.edge_id=$id "
                "DELETE r RETURN count(r) AS changed", params)
        if name == "delete_node":
            return self._mutate(name, _lookup() + "DETACH DELETE n RETURN count(n) AS changed", params)
        raise ValueError(f"Unsupported canonical operation: {name}")

    def snapshot(self):
        params = {"pids": list(self.proofs.values()), "token": self.token}
        inverse = {value: key for key, value in self.proofs.items()}
        records = self._read("snapshot_nodes",
            "MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run=$token "
            "RETURN collect({properties:properties(n),labels:labels(n)}) AS value", params, [])
        nodes = []
        for row in records:
            properties = row["properties"]
            labels = [label for label in row["labels"] if label in LABELS]
            if len(labels) != 1:
                raise RuntimeError(f"Unexpected fixture node labels: {row['labels']}")
            nodes.append({"proof": inverse[properties["proof_id"]], "id": properties["id"],
                          "label": labels[0], "fields": {key: value for key, value in properties.items()
                          if key not in INTERNAL_PROPERTIES}})
        records = self._read("snapshot_edges",
            "MATCH (s)-[r]->(d) WHERE s.proof_id IN $pids AND d.proof_id=s.proof_id "
            "AND s.benchmark_run=$token AND d.benchmark_run=$token "
            "AND r.benchmark_run=$token AND r.proof_id=s.proof_id "
            "RETURN collect({proof:s.proof_id,id:r.edge_id,rel:type(r),src:s.id,dst:d.id}) AS value", params, [])
        edges = [{**row, "proof": inverse[row["proof"]]} for row in records]
        key = lambda row: (row["proof"], row["id"])
        return {"nodes": sorted(nodes, key=key), "edges": sorted(edges, key=key)}

    def counts(self):
        params = {"pids": list(self.proofs.values()), "token": self.token}
        nodes = self._read("count_nodes", "MATCH (n) WHERE n.proof_id IN $pids "
                           "AND n.benchmark_run=$token RETURN count(n) AS value", params, 0)
        edges = self._read("count_edges", "MATCH (s)-[r]->(d) WHERE s.proof_id IN $pids "
                          "AND d.proof_id=s.proof_id AND s.benchmark_run=$token "
                          "AND d.benchmark_run=$token AND r.benchmark_run=$token "
                          "AND r.proof_id=s.proof_id RETURN count(r) AS value", params, 0)
        return {"nodes": nodes, "edges": edges}

    def clear(self):
        """Remove only owned, exactly namespaced fixture nodes; verify cleanup."""
        if self.proofs:
            self.adapter._write_all("benchmark_cleanup", [(
                "MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run=$token DETACH DELETE n",
                {"pids": list(self.proofs.values()), "token": self.token})])
            counts = self.counts()
            if counts != {"nodes": 0, "edges": 0}:
                raise RuntimeError(f"Neo4j fixture cleanup incomplete: {counts}")

    def close(self):
        if self._closed:
            return
        try:
            self.clear()
            self.metadata["cleanup_verified"] = True
        finally:
            self._closed = True
            if self._owns_adapter:
                self.adapter.close()
