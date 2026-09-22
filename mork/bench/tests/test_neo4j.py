"""Contract and fixture-safety tests; these do not need a Neo4j server."""
from types import SimpleNamespace
import unittest

from mork.bench.backends.neo4j import Neo4jBackend


def operation(name, **args):
    return SimpleNamespace(name=name, args={"proof": "target", **args})


class Result:
    def __init__(self, rows):
        self.rows = rows

    def single(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.values = {}
        self.changed = 1
        self.closed = False

    def _read_value(self, name, query, params, key, default=None):
        self.calls.append((name, query, params))
        return self.values.get(name, default)

    def _write_all(self, name, statements):
        self.calls.extend((name, query, params) for query, params in statements)

    def _write(self, name, work):
        adapter = self

        class Transaction:
            def run(self, query, **params):
                adapter.calls.append((name, query, params))
                return Result([{"changed": adapter.changed}])

        return work(Transaction())

    def close(self):
        self.closed = True


class Neo4jCommonTests(unittest.TestCase):
    def setUp(self):
        self.adapter = FakeAdapter()
        self.backend = Neo4jBackend(self.adapter, verify_schema=False)

    def test_cleanup_requires_exact_namespaces_and_owner(self):
        self.backend._proof("target")
        self.backend._proof("background")
        self.backend.close()
        cleanup = [call for call in self.adapter.calls if call[0] == "benchmark_cleanup"]
        self.assertEqual(len(cleanup), 1)
        _, query, params = cleanup[0]
        self.assertIn("n.proof_id IN $pids", query)
        self.assertIn("n.benchmark_run=$token", query)
        self.assertEqual(params["token"], self.backend.token)
        self.assertEqual(set(params["pids"]), set(self.backend.proofs.values()))
        self.assertNotIn("target", params["pids"])
        self.assertTrue(self.backend.metadata["cleanup_verified"])
        self.assertFalse(self.adapter.closed)  # caller retains an injected adapter
        self.backend.close()
        self.assertEqual(len([c for c in self.adapter.calls if c[0] == "benchmark_cleanup"]), 1)

    def test_cleanup_failure_is_reported(self):
        self.backend._proof("target")
        self.adapter.values["benchmark_count_nodes"] = 1
        with self.assertRaisesRegex(RuntimeError, "cleanup incomplete"):
            self.backend.close()
        self.assertNotIn("cleanup_verified", self.backend.metadata)

    def test_owners_and_namespaces_are_unique_between_instances(self):
        other = Neo4jBackend(FakeAdapter(), verify_schema=False)
        self.assertNotEqual(self.backend._proof("target"), other._proof("target"))

    def test_node_result_has_all_fields_and_strips_only_internal_properties(self):
        self.adapter.values["benchmark_node"] = {
            "id": "n1", "labels": ["Move"], "properties": {
                "id": "n1", "proof_id": self.backend._proof("target"),
                "benchmark_run": self.backend.token, "layer": "committed",
                "status": "open", "depth": 7, "description": "all fields are included",
            }}
        actual = self.backend.execute(operation("node", id="n1"))
        self.assertEqual(actual, ["n1", "Move", [["depth", 7],
            ["description", "all fields are included"], ["status", "open"]]])
        query = self.adapter.calls[-1][1]
        for label in ("State", "Move", "Claim"):
            self.assertIn(f"(n:{label} {{proof_id: $pid, id: $id}})", query)
        self.assertIsNone(self.backend.execute(operation("missing_node", id="absent")))

    def test_snapshot_restores_logical_namespaces_and_fields(self):
        pid = self.backend._proof("target")
        self.adapter.values["benchmark_snapshot_nodes"] = [
            {"labels": ["Claim"], "properties": {"id": "n1", "proof_id": pid,
             "benchmark_run": self.backend.token, "layer": "committed", "status": "open"}},
            {"labels": ["Claim"], "properties": {"id": "n0", "proof_id": pid,
             "benchmark_run": self.backend.token, "layer": "committed", "status": "refuted"}},
        ]
        self.adapter.values["benchmark_snapshot_edges"] = [
            {"proof": pid, "id": "e1", "rel": "DEPENDS_ON", "src": "n1", "dst": "n0"}]
        result = self.backend.snapshot()
        self.assertEqual([row["id"] for row in result["nodes"]], ["n0", "n1"])
        self.assertEqual(result["nodes"][0], {"proof": "target", "id": "n0",
                                             "label": "Claim", "fields": {"status": "refuted"}})
        self.assertEqual(result["edges"][0]["proof"], "target")

    def test_all_mutations_use_namespaced_proof_and_ownership(self):
        operations = [
            operation("create_node", id="new", label="Move", fields={"status": "open"}),
            operation("insert_field", id="n1", field="depth", value=1),
            operation("overwrite_field", id="n1", field="depth", value=2),
            operation("delete_field", id="n1", field="depth"),
            operation("add_edge", id="e-new", rel="PROPOSES", src="n0", dst="n1"),
            operation("remove_edge", id="e-new"),
            operation("delete_node", id="new"),
        ]
        for op in operations:
            with self.subTest(op=op.name):
                self.assertTrue(self.backend.execute(op))
                _, query, params = self.adapter.calls[-1]
                self.assertEqual(params["pid"], self.backend.proofs["target"])
                self.assertEqual(params["token"], self.backend.token)
                if op.name == "create_node":
                    self.assertEqual(params["properties"]["proof_id"], params["pid"])
                    self.assertEqual(params["properties"]["benchmark_run"], params["token"])
                else:
                    self.assertIn("proof_id", query)
                    self.assertIn("benchmark_run", query)

    def test_failed_mutation_raises_inside_transaction(self):
        self.adapter.changed = 0
        with self.assertRaisesRegex(RuntimeError, "expected exactly one"):
            self.backend.execute(operation("remove_edge", id="missing"))

    def test_ownership_cannot_be_overwritten_or_injected(self):
        for op in [
            operation("create_node", id="bad", label="Move", fields={"proof_id": "production"}),
            operation("create_node", id="bad", label="Move`) DETACH DELETE n //", fields={}),
            operation("overwrite_field", id="n1", field="benchmark_run", value="foreign"),
            operation("delete_field", id="n1", field="layer"),
            operation("add_edge", id="e", rel="X] DELETE n //", src="a", dst="b"),
        ]:
            with self.subTest(op=op.name), self.assertRaises(ValueError):
                self.backend.execute(op)
        self.assertEqual(self.adapter.calls, [])

    def test_unknown_or_cross_proof_endpoints_rejected_before_writes(self):
        graph = {"nodes": [{"proof": "a", "id": "n0", "label": "State", "fields": {}},
                            {"proof": "b", "id": "n1", "label": "Move", "fields": {}}],
                 "edges": [{"proof": "a", "id": "e1", "rel": "PROPOSES", "src": "n0", "dst": "n1"}]}
        with self.assertRaisesRegex(ValueError, "cross-proof"):
            self.backend.load(graph)
        self.assertEqual(self.adapter.calls, [])

    def test_rule_queries_include_shared_semantics(self):
        self.backend.execute(operation("frontier", id="state"))
        frontier = self.adapter.calls[-1][1]
        self.assertIn("id:$id", frontier)
        self.assertIn("['open','reopened']", frontier)
        self.assertIn("['tainted','formally-closed']", frontier)
        self.assertIn("collect(DISTINCT m.id)", frontier)
        self.backend.execute(operation("taint", id="root"))
        taint = self.adapter.calls[-1][1]
        self.assertIn("root.status='refuted'", taint)
        self.assertIn("c <> root", taint)
        self.assertIn("collect(DISTINCT c.id)", taint)

    def test_schema_inspection_handles_token_lookup_indexes(self):
        class SchemaAdapter(FakeAdapter):
            def _read(self, name, work):
                if name == "benchmark_server":
                    return [{"name": "Neo4j Kernel", "versions": ["5.20.0"], "edition": "community"}]
                if name == "benchmark_indexes":
                    return [{"name": "lookup", "type": "LOOKUP", "entityType": "NODE",
                             "labelsOrTypes": None, "properties": None, "state": "ONLINE"}] + [
                        {"name": label.lower() + "_key", "type": "RANGE", "entityType": "NODE",
                         "labelsOrTypes": [label], "properties": ["proof_id", "id"], "state": "ONLINE"}
                        for label in ("State", "Move", "Claim")]
                return []
        backend = Neo4jBackend(SchemaAdapter())
        self.assertEqual(len(backend.metadata["indexes"]), 4)
        self.assertEqual(backend.metadata["server"][0]["versions"], ["5.20.0"])

    def test_schema_inspection_rejects_missing_identity_indexes(self):
        class SchemaAdapter(FakeAdapter):
            def _read(self, name, work):
                return []
        with self.assertRaisesRegex(RuntimeError, "requires online native indexes"):
            Neo4jBackend(SchemaAdapter())


if __name__ == "__main__":
    unittest.main()
