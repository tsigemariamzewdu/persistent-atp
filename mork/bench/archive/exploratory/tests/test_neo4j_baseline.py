import unittest
from pathlib import Path

from mork.bench.archive.exploratory.compare_backends import measure
from mork.bench.archive.exploratory.experiments import cases
from mork.bench.archive.exploratory.harness import program
from mork.bench.archive.exploratory.neo4j_baseline import Neo4jFixture
from mork.bench.archive.exploratory.workload import commands


class FakeAdapter:
    def __init__(self):
        self.calls = []
        self.nodes = self.edges = 0

    def _write_all(self, operation, statements):
        self.calls.append((operation, statements))
        if operation == 'benchmark_load':
            self.nodes = sum(len(p['rows']) for q,p in statements if 'SET n = row' in q)
            self.edges = sum(len(p['rows']) for q,p in statements if 'SET n = row' not in q)
        if operation == 'benchmark_cleanup':
            self.nodes = self.edges = 0

    def _read_value(self, operation, query, params, key):
        return self.edges if 'count(r)' in query else self.nodes


class Neo4jBaselineTests(unittest.TestCase):
    def test_fixture_counts_and_cleanup_are_scoped(self):
        adapter = FakeAdapter()
        fixture = Neo4jFixture(adapter, commands(10, 50))
        fixture.load()
        self.assertEqual(fixture.counts(), (60, 57))
        self.assertTrue(all(pid.startswith(f'bench-{fixture.token}-') for pid in fixture.proofs.values()))
        fixture.cleanup()
        query, params = adapter.calls[-1][1][0]
        self.assertIn('n.proof_id IN $pids', query)
        self.assertIn('n.benchmark_run = $token', query)
        self.assertEqual(params['token'], fixture.token)
        self.assertEqual(set(params['pids']), set(fixture.proofs.values()))
        self.assertEqual(fixture.counts(), (0, 0))

    def test_fixture_names_never_reuse_target_or_other_runs(self):
        a = Neo4jFixture(FakeAdapter(), commands(2))
        b = Neo4jFixture(FakeAdapter(), commands(2))
        self.assertNotEqual(a.target, b.target)
        self.assertNotEqual(a.target, 'target')

    def test_wall_batch_program_is_balanced_and_repeats(self):
        case = cases('Q1', True)[0]
        for wall in (False, True):
            source = program(case, Path('/tmp/fixture.metta'), 66, 3, 1,
                             wall_clock=wall, batch_size=20)
            for line in source.splitlines():
                self.assertEqual(line.count('('), line.count(')'), line)
            self.assertIn('(bench-repeat-0 20)', source)
            self.assertEqual(source.count('(BENCH_SAMPLE'), 3)
            if wall:
                self.assertIn('time.monotonic_ns', source)
                self.assertNotIn('(statistics cputime)', source)

    def test_measure_checks_outputs_and_batch_call_count(self):
        calls = []
        def query():
            calls.append(1)
            return ['x']
        values = measure(query, ['x'], iterations=3, warmup=1, batch_size=2)
        self.assertEqual(len(calls), 9)  # precheck + two warmup + six measured
        self.assertEqual(len(values), 3)
        with self.assertRaises(RuntimeError):
            measure(query, [], 1, 0, 1)


if __name__ == '__main__':
    unittest.main()
