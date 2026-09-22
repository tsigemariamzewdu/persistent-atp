import unittest
from copy import deepcopy

from mork.bench.experiments import (
    MUTATIONS, Operation, Oracle, basic_graph, canonical_graph, dependency_graph,
    expected_result, frontier_graph, generate_cases, inverse_operations,
    normalize_result, rebuild_journal,
)


class SharedSpecificationTests(unittest.TestCase):
    def test_all_cases_have_one_probe_or_rebuild_and_unique_keys(self):
        quick = generate_cases(quick=True)
        self.assertEqual(len(quick), 37)
        self.assertEqual(len({c.key for c in quick}), len(quick))
        self.assertEqual({c.experiment for c in quick}, {f"E{i}" for i in range(1, 7)})
        for case in quick:
            with self.subTest(case=case.key):
                Oracle(case.graph)
                if case.experiment == "E6":
                    self.assertEqual(case.operations, [])
                    self.assertEqual(Oracle().apply_journal(case.journal), case.graph)
                else:
                    self.assertEqual(len(case.operations), 1)
                    self.assertFalse(case.journal)
                    expected_result(case.operations[0], case.graph)

    def test_mutations_are_genuine_and_reset_exactly_for_repeated_calls(self):
        for case in generate_cases(quick=True):
            if not case.operations or case.operations[0].name not in MUTATIONS:
                continue
            operation = case.operations[0]
            with self.subTest(case=case.key):
                oracle = Oracle(case.graph)
                original = oracle.snapshot()
                for _ in range(3):
                    self.assertIs(oracle.execute(operation), True)
                    self.assertNotEqual(oracle.snapshot(), original)
                    for reset in inverse_operations(operation, case.graph):
                        oracle.execute(reset)
                    self.assertEqual(oracle.snapshot(), original)

    def test_oracle_rejects_noop_mutations_and_dangling_edges(self):
        oracle = Oracle(basic_graph(4))
        with self.assertRaises(ValueError):
            oracle.execute(Operation("overwrite_field", {
                "proof": "target", "id": "n1", "field": "status", "value": "open",
            }))
        with self.assertRaises(ValueError):
            oracle.execute(Operation("create_node", {
                "proof": "target", "id": "n1", "label": "Move", "fields": {},
            }))
        with self.assertRaises(ValueError):
            oracle.execute(Operation("add_edge", {
                "proof": "target", "id": "bad", "rel": "SUPPORTS",
                "src": "missing", "dst": "n1",
            }))

    def test_growing_proof_preserves_probe_answers_and_field_payload(self):
        observed = {}
        for case in generate_cases(quick=True):
            if case.experiment not in {"E2", "E3"}:
                continue
            operation = case.operations[0]
            value = expected_result(operation, case.graph)
            if operation.name not in observed:
                observed[operation.name] = value
            self.assertEqual(value, observed[operation.name])
        self.assertEqual(observed["incoming"], [["e1", "PROPOSES", "n0", "n1"]])
        self.assertEqual(observed["outgoing"], [["support0", "SUPPORTS", "n1", "n2"]])

    def test_proof_namespace_scopes_reused_local_identifiers(self):
        target, background = basic_graph(4), basic_graph(4, proof="background")
        background["nodes"][1]["fields"]["status"] = "leased"
        graph = {"nodes": target["nodes"] + background["nodes"],
                 "edges": target["edges"] + background["edges"]}
        oracle = Oracle(graph)
        self.assertEqual(oracle.execute(Operation("frontier", {
            "proof": "target", "id": "n0",
        })), ["n1", "n2", "n3"])
        self.assertEqual(oracle.execute(Operation("frontier", {
            "proof": "background", "id": "n0",
        })), ["n2", "n3"])
        oracle.execute(Operation("overwrite_field", {
            "proof": "target", "id": "n1", "field": "status", "value": "exhausted",
        }))
        self.assertEqual(oracle.nodes["background", "n1"]["fields"]["status"], "leased")

    def test_frontier_selectivity_and_blocked_states(self):
        for percentage in (10, 50, 90):
            graph = frontier_graph(100, percentage)
            operation = Operation("frontier", {"proof": "target", "id": "n0"})
            expected = sorted(f"n{i}" for i in range(1, percentage + 1))
            self.assertEqual(expected_result(operation, graph), expected)
            for blocked in ("tainted", "formally-closed"):
                graph["nodes"][0]["fields"]["status"] = blocked
                self.assertEqual(expected_result(operation, graph), [])

    def test_taint_traverses_and_deduplicates_all_shapes(self):
        operation = Operation("taint", {"proof": "target", "id": "n0"})
        for shape in ("star", "chain", "diamond"):
            graph = dependency_graph(40, shape)
            expected = sorted(f"n{i}" for i in range(1, 40))
            self.assertEqual(expected_result(operation, graph), expected)
            graph["nodes"][0]["fields"]["status"] = "open"
            self.assertEqual(expected_result(operation, graph), [])

    def test_taint_excludes_unrelated_claims_and_other_relationships(self):
        graph = dependency_graph(4, "chain")
        graph["nodes"].append({"proof": "target", "id": "unrelated", "label": "Claim",
                               "fields": {"status": "open", "depth": 0}})
        graph["edges"].append({"proof": "target", "id": "other-relation", "rel": "SUPPORTS",
                               "src": "unrelated", "dst": "n0"})
        self.assertEqual(expected_result(Operation("taint", {
            "proof": "target", "id": "n0",
        }), graph), ["n1", "n2", "n3"])

    def test_rebuild_contains_updates_and_removals_and_matches_final_graph(self):
        journal, final_graph = rebuild_journal(100)
        self.assertEqual({op["name"] for op in journal}, {
            "create_node", "add_edge", "overwrite_field", "remove_edge",
        })
        self.assertEqual(len(final_graph["nodes"]), 100)
        self.assertEqual(len(final_graph["edges"]), 95)
        self.assertEqual(Oracle().apply_journal(journal), canonical_graph(final_graph))

    def test_normalization_does_not_hide_duplicate_query_results(self):
        self.assertEqual(normalize_result("frontier", ["n2", "n1"]), ["n1", "n2"])
        self.assertEqual(normalize_result("taint", ["n1", "n1"]), ["n1", "n1"])

    def test_expected_result_does_not_mutate_case_graph(self):
        case = next(c for c in generate_cases(quick=True) if c.key == "E1_overwrite_field")
        before = deepcopy(case.graph)
        self.assertIs(expected_result(case.operations[0], case.graph), True)
        self.assertEqual(case.graph, before)


if __name__ == "__main__":
    unittest.main()
