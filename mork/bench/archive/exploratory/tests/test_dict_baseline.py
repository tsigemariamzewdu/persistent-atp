import unittest

from mork.bench.archive.exploratory.dict_baseline import DictGraph, comparison_markdown, measure_case, probes
from mork.bench.archive.exploratory.experiments import EXPERIMENTS, cases
from mork.bench.archive.exploratory.workload import commands, journal
from mork.projector.core import project_event_journal


class DictBaselineTests(unittest.TestCase):
    def test_every_quick_workload_has_equivalent_results(self):
        for experiment in EXPERIMENTS:
            for case in cases(experiment, True):
                with self.subTest(case=case.stem):
                    data = commands(case.nodes, case.background, claims=case.claims)
                    graph = DictGraph(data)
                    self.assertEqual(len(graph.atoms), len(data))
                    for probe in case.probes:
                        call, expected = probes(graph, case)[probe.name]
                        self.assertEqual(call(), expected)
                    # Verify entire output, not just the measured count, for rules.
                    if experiment == 'Q1':
                        self.assertEqual(graph.frontier('target', 'n0'),
                                         [f'n{i}' for i in range(1, case.nodes)])
                    if experiment == 'Q2':
                        self.assertEqual(graph.taint_cone('target', 'n0'),
                                         [f'n{i}' for i in range(1, case.nodes)])
                    self.assertEqual(len(graph.atoms), len(data))

    def test_frontier_respects_move_and_state_status(self):
        graph = DictGraph(commands(4))
        graph.fields['target', 'n1', 'status'] = 'leased'
        graph.fields['target', 'n2', 'status'] = 'reopened'
        graph.layers['target', 'n3'] = 'speculative'
        self.assertEqual(graph.frontier('target', 'n0'), ['n2'])
        graph.fields['target', 'n0', 'status'] = 'tainted'
        self.assertEqual(graph.frontier('target', 'n0'), [])

    def test_taint_traverses_chain_and_requires_refuted_root(self):
        data = journal('target', 4, claims=True)
        for op in data['events'][0]['payload']['ops']:
            if op['op'] == 'add_edge':
                i = int(op['edge_id'].split('e')[-1])
                op['dst'] = f'target/n{i-1}'
        graph = DictGraph(project_event_journal(data))
        self.assertEqual(graph.taint_cone('target', 'n0'), ['n1', 'n2', 'n3'])
        graph.fields['target', 'n0', 'status'] = 'open'
        self.assertEqual(graph.taint_cone('target', 'n0'), [])

    def test_measurement_labels_and_comparison_ratio(self):
        case = cases('E3', True)[0]
        row = measure_case(case, commands(case.nodes), 3, 1)[0]
        self.assertEqual(row.runtime, 'python-dict')
        self.assertEqual(row.clock, 'python_thread_cpu')
        from dataclasses import replace
        baseline = replace(row, median=1, p95=2)
        petta = replace(row, runtime='petta-space', median=4, p95=8)
        output = comparison_markdown([petta, baseline])
        self.assertIn('4.00×', output)
        self.assertIn('not MORK', output)
        with self.assertRaises(ValueError):
            comparison_markdown([replace(petta, atoms=0), baseline])


if __name__ == '__main__':
    unittest.main()
