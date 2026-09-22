"""Report statistics and interrupted-fixture safety, without native runtimes."""
import json
from pathlib import Path
import statistics
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from mork.bench.backends.mork_ffi import graph_atoms, parse
from mork.bench.experiments import basic_graph, generate_cases
from mork.bench.harness import cleanup_interrupted, main
from mork.bench.reporting import aggregate, report
from mork.bench.harness import check_atoms


def row(backend="mork-ffi", samples=(1.0, 2.0, 3.0), status="ok", case="E1_node"):
    value = {"case": case, "experiment": case.split("_")[0], "backend": backend,
             "status": status}
    if status == "ok":
        value.update(median_us=statistics.median(samples), samples_us=list(samples))
    else:
        value["error"] = "synthetic failure"
    return value


class HarnessReportTests(unittest.TestCase):
    def test_trials_have_equal_weight_in_median_of_trial_medians(self):
        values = [row(samples=(1, 1, 1)), row(samples=(100,))]
        result = aggregate(values)[0]
        self.assertEqual(result["median_us"], 50.5)
        self.assertEqual(result["pooled_p95_us"], 100)
        self.assertEqual(result["trial_median_min_us"], 1)
        self.assertEqual(result["trial_median_max_us"], 100)
        self.assertEqual(result["successful_trials"], 2)

    def test_backend_and_case_groups_remain_separate(self):
        values = [row(), row(backend="neo4j", samples=(2000,)),
                  row(case="E2_node_100", samples=(30,))]
        result = {(r["case"], r["backend"]): r for r in aggregate(values)}
        self.assertEqual(len(result), 3)
        self.assertEqual(result["E1_node", "mork-ffi"]["median_us"], 2)
        self.assertEqual(result["E1_node", "neo4j"]["median_us"], 2000)
        self.assertEqual(result["E2_node_100", "mork-ffi"]["median_us"], 30)

    def test_timeout_is_not_a_numeric_timing(self):
        result = aggregate([row(status="timeout")])[0]
        self.assertEqual(result["status"], "timeout")
        self.assertEqual(result["successful_trials"], 0)
        self.assertNotIn("median_us", result)
        self.assertNotIn("pooled_p95_us", result)

    def test_partial_failure_cannot_be_hidden_by_last_success(self):
        for values in ([row(), row(status="timeout")], [row(status="timeout"), row()]):
            with self.subTest(order=[r["status"] for r in values]):
                result = aggregate(values)[0]
                self.assertEqual(result["status"], "timeout")
                self.assertEqual(result["successful_trials"], 1)
                self.assertEqual(result["attempted_trials"], 2)

    def test_report_does_not_publish_partial_success_as_complete_timing(self):
        case = generate_cases(quick=True)[0]
        metadata = {"status": "complete_with_failures", "started_at": "2026-09-20",
                    "repeats": 5, "samples": 30, "warmup": 3, "timeout": 60,
                    "python": "test", "platform": "test", "command": "test-command"}
        text = report([case], [row(), row(status="timeout")], metadata)
        self.assertIn("| E1_node | 100 | 100 / 100 | timeout | not selected | not selected |", text)
        self.assertIn("Unsuccessful trials", text)
        self.assertIn("synthetic failure", text)

    def test_report_marks_successful_but_unfinished_repetitions_preliminary(self):
        case = generate_cases(quick=True)[0]
        metadata = {"status": "running", "started_at": "2026-09-20",
                    "repeats": 5, "samples": 30, "warmup": 3, "timeout": 60,
                    "python": "test", "platform": "test", "command": "test-command",
                    "selected_backends": ["mork-ffi"]}
        text = report([case], [row(), row()], metadata)
        self.assertIn("| 2.00 (preliminary; 2/5 trials) | not selected | not selected |", text)
        complete = report([case], [row() for _ in range(5)], metadata)
        self.assertIn("| 2.00 | not selected | not selected |", complete)
        self.assertNotIn("(preliminary;", complete)

    def test_report_distinguishes_pending_work_from_excluded_backends(self):
        case = generate_cases(quick=True)[0]
        metadata = {"status": "running", "started_at": "2026-09-20",
                    "repeats": 5, "samples": 30, "warmup": 3, "timeout": 60,
                    "python": "test", "platform": "test", "command": "test-command",
                    "selected_backends": ["mork-ffi", "mork-petta"]}
        text = report([case], [], metadata)
        self.assertIn("| E1_node | 100 | 100 / 100 | pending | pending | not selected |", text)

    def test_fresh_run_rejects_nonempty_output_without_writes_or_worker_launch(self):
        case = generate_cases(quick=True)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            trial = output / "artifacts" / "E1_node-mork-ffi-0"
            trial.mkdir(parents=True)
            (trial / "result.json").write_text(json.dumps(row()))
            (output / "environment.json").write_text('{"status":"saved-evidence"}\n')
            before = {str(p.relative_to(output)): (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in output.rglob("*") if p.is_file()}
            with patch("mork.bench.harness.generate_cases", return_value=[case]), \
                 patch("mork.bench.harness.subprocess.Popen") as launch:
                with self.assertRaises(SystemExit) as rejected:
                    main(["--backend", "mork-ffi", "--quick", "--repeats", "1",
                          "--samples", "1", "--output-dir", directory])
            self.assertNotEqual(rejected.exception.code, 0)
            launch.assert_not_called()
            after = {str(p.relative_to(output)): (p.read_bytes(), p.stat().st_mtime_ns)
                     for p in output.rglob("*") if p.is_file()}
            self.assertEqual(after, before)

    def test_interrupt_kills_worker_and_records_an_incomplete_run(self):
        from unittest.mock import Mock
        import signal
        case = generate_cases(quick=True)[0]
        process = SimpleNamespace(wait=Mock(side_effect=[KeyboardInterrupt, 0]),
                                  returncode=-signal.SIGKILL, pid=123456)
        with tempfile.TemporaryDirectory() as directory, \
             patch("mork.bench.harness.generate_cases", return_value=[case]), \
             patch("mork.bench.harness.platform.platform", return_value="test"), \
             patch("mork.bench.harness.subprocess.Popen", return_value=process), \
             patch("mork.bench.harness.os.killpg") as kill:
            status = main(["--backend", "mork-ffi", "--repeats", "1",
                           "--output-dir", directory])
            self.assertEqual(status, 130)
            kill.assert_called_once_with(process.pid, signal.SIGKILL)
            metadata = json.loads((Path(directory) / "environment.json").read_text())
            self.assertEqual(metadata["status"], "interrupted")
            result = json.loads((Path(directory) / "trials.json").read_text())[0]
            self.assertEqual(result["status"], "interrupted")
            self.assertNotIn("median_us", result)

    def test_resume_preserves_completed_trials_and_retries_only_interruption(self):
        from unittest.mock import Mock
        case = generate_cases(quick=True)[0]
        attempts = []

        def launch(command, **kwargs):
            config = json.loads(Path(command[-1]).read_text())
            attempts.append(config['trial'])
            if len(attempts) == 2:
                return SimpleNamespace(wait=Mock(side_effect=[KeyboardInterrupt, 0]),
                                       returncode=-9, pid=123456)
            value = row(samples=(float(len(attempts)),))
            value['trial'] = config['trial']
            Path(config['outfile']).write_text(json.dumps(value))
            return SimpleNamespace(wait=lambda **kwargs: None, returncode=0, pid=123456)

        with tempfile.TemporaryDirectory() as directory, \
             patch('mork.bench.harness.generate_cases', return_value=[case]), \
             patch('mork.bench.harness.platform.platform', return_value='test'), \
             patch('mork.bench.harness.subprocess.Popen', side_effect=launch), \
             patch('mork.bench.harness.os.killpg'):
            arguments = ['--backend', 'mork-ffi', '--quick', '--repeats', '2',
                         '--samples', '1', '--output-dir', directory]
            self.assertEqual(main(arguments), 130)
            first = json.loads((Path(directory)/'trials.json').read_text())[0]
            self.assertEqual(main([*arguments, '--resume']), 0)
            values = json.loads((Path(directory)/'trials.json').read_text())
            self.assertEqual(attempts, [0, 1, 1])
            self.assertEqual(values[0], first)
            self.assertEqual([v['trial'] for v in values], [0, 1])
            metadata = json.loads((Path(directory)/'environment.json').read_text())
            self.assertEqual(metadata['continuations'][0]['retained_trials'], 1)
            self.assertTrue(list((Path(directory)/'artifacts/interrupted-attempts').iterdir()))
            with self.assertRaises(SystemExit):
                main([*arguments, '--resume', '--samples', '2'])


class AtomIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.graph = basic_graph(4)
        self.atoms = [parse(value) for value in graph_atoms(self.graph)]

    def test_valid_atoms_can_be_returned_in_any_order(self):
        check_atoms(list(reversed(self.atoms)), self.graph)

    def test_missing_reverse_index_fails_even_if_forward_graph_is_correct(self):
        values = list(self.atoms)
        values.pop(next(i for i, atom in enumerate(values) if atom[0] == "rev-edge"))
        with self.assertRaisesRegex(RuntimeError, "atom/index snapshot"):
            check_atoms(values, self.graph)

    def test_stale_reverse_index_after_edge_removal_fails(self):
        updated = {"nodes": self.graph["nodes"], "edges": self.graph["edges"][1:]}
        stale = [atom for atom in self.atoms if not (atom[0] == "edge" and atom[2] == "e1")]
        with self.assertRaisesRegex(RuntimeError, "atom/index snapshot"):
            check_atoms(stale, updated)

    def test_duplicate_atoms_are_not_hidden_by_set_equality(self):
        with self.assertRaisesRegex(RuntimeError, "atom count"):
            check_atoms(self.atoms + [self.atoms[0]], self.graph)


class InterruptedCleanupTests(unittest.TestCase):
    def check_cleanup(self, remaining):
        calls = []

        class Adapter:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                calls.append("closed")

            def _write_all(self, name, statements):
                calls.extend((name, query, params) for query, params in statements)

            def _read_value(self, name, query, params, key):
                calls.append((name, query, params))
                return remaining

        fake = ModuleType("neo4j_adapter.adapter")
        fake.Neo4jAdapter = Adapter
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json.cleanup.json"
            data = {"token": "isolated-owner", "pids": ["ptps-bench-isolated-target"]}
            path.write_text(json.dumps(data))
            with patch.dict(sys.modules, {"neo4j_adapter.adapter": fake}):
                if remaining:
                    with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
                        cleanup_interrupted(path)
                    self.assertTrue(path.exists(), "Failed cleanup must retain its recovery checkpoint")
                else:
                    cleanup_interrupted(path)
                    self.assertFalse(path.exists())
            for call in calls:
                if call == "closed":
                    continue
                _, query, params = call
                self.assertIn("n.proof_id IN $pids", query)
                self.assertIn("n.benchmark_run=$token", query)
                self.assertEqual(params, data)
            self.assertEqual(calls[-1], "closed")

    def test_timeout_cleanup_uses_exact_ownership_scope_and_checks_removal(self):
        self.check_cleanup(remaining=0)

    def test_failed_timeout_cleanup_preserves_checkpoint(self):
        self.check_cleanup(remaining=1)


if __name__ == "__main__":
    unittest.main()
