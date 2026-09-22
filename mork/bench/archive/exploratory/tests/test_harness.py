"""Run with python -m unittest discover -s mork/bench/tests."""
import unittest
from pathlib import Path

from mork.bench.archive.exploratory.experiments import cases
from mork.bench.archive.exploratory.harness import detect_runtime, parse_rows, program, summarize
from mork.bench.archive.exploratory.workload import commands


class HarnessTests(unittest.TestCase):
    def test_missing_mork_requires_explicit_fallback(self):
        output = '(BENCH_INIT (partial mm2-exec (&mork 1)))\n'
        with self.assertRaisesRegex(RuntimeError, 'MORK is not active'):
            detect_runtime(output, False)
        self.assertEqual(detect_runtime(output, True), 'petta-space')

    def test_missing_runtime_marker_is_not_success(self):
        with self.assertRaises(RuntimeError):
            detect_runtime('true\n', True)

    def test_distribution_and_invalid_clock_sample(self):
        self.assertEqual(summarize(list(range(1, 21))), (10.5, 19))
        for samples in ([], [-1], [float('nan')], [float('inf')]):
            with self.assertRaises(ValueError):
                summarize(samples)

    def test_parser_requires_completion_count_and_samples(self):
        case = cases('E4', True)[0]
        good = '(BENCH_ATOMS 0)\n(BENCH_SAMPLE 0 2.5)\nBENCH_DONE\n'
        rows = parse_rows(good, case, 0, 1, 'petta-space')
        self.assertEqual(rows[0].median, 2.5)
        for output in (good.replace('BENCH_DONE', ''),
                       good.replace('ATOMS 0', 'ATOMS 1'),
                       good.replace('(BENCH_SAMPLE 0 2.5)\n', ''),
                       good + '(BENCH_SAMPLE 0 3)\n'):
            with self.assertRaises(RuntimeError):
                parse_rows(output, case, 0, 1, 'petta-space')

    def test_workload_uses_projector_indexes_and_layers(self):
        atoms = commands(2)
        self.assertEqual(len(atoms), 10)
        self.assertIn('!(add-atom &mork (rev-edge "target" "n1" "PROPOSES" "n0" "e1"))', atoms)
        self.assertIn('!(add-atom &mork (layer "target" "edge:e1" "committed"))', atoms)
        self.assertEqual(commands(10, 50), commands(10, 50))
        self.assertEqual(len(commands(10, 50)), len(set(commands(10, 50))))

    def test_program_times_queries_after_load_and_checks_results(self):
        case = cases('E2', True)[0]
        source = program(case, Path('/tmp/data.metta'), 66, 2, 1)
        self.assertLess(source.index('BENCH_LOAD'), source.index('BENCH_SAMPLE'))
        self.assertEqual(source.count('(BENCH_SAMPLE'), 6)
        self.assertIn('!(test (collapse (incoming-edges', source)
        self.assertTrue(source.endswith('!(println! BENCH_DONE)\n'))


if __name__ == '__main__':
    unittest.main()
