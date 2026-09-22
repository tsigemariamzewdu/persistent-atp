"""The simpler package preserves workloads, executable paths, and saved evidence."""
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mork.bench import harness
from mork.bench.backends import mork_ffi, neo4j, petta
from mork.bench.experiments import generate_cases, inverse_operations


ROOT = Path(__file__).resolve().parents[3]
MEASURED_SPEC = (ROOT / "mork/bench/results/common-e1-e6-2026-09-20"
                 / "measured-source/spec.py")


def fingerprint(directory):
    """Read-only comparison catches both overwritten evidence and extra files."""
    return {
        str(path.relative_to(directory)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in directory.rglob("*") if path.is_file()
    }


class PackageStructureTests(unittest.TestCase):
    def test_all_fixtures_match_the_immutable_measured_experiments(self):
        name = "_original_ptps_measured_spec"
        spec = importlib.util.spec_from_file_location(name, MEASURED_SPEC)
        original = importlib.util.module_from_spec(spec)
        # dataclasses resolves annotations through sys.modules during import.
        with patch.dict(sys.modules, {name: original}):
            spec.loader.exec_module(original)
            before = original.generate_cases()
        after = generate_cases()
        self.assertEqual(len(after), 51)
        self.assertEqual([case.key for case in after], [case.key for case in before])
        for actual, expected in zip(after, before):
            with self.subTest(case=actual.key):
                self.assertEqual(asdict(actual), asdict(expected))

    def test_backend_imports_and_generated_program_paths(self):
        self.assertEqual(mork_ffi.MorkBackend.__module__, "mork.bench.backends.mork_ffi")
        self.assertEqual(neo4j.Neo4jBackend.__module__, "mork.bench.backends.neo4j")
        self.assertEqual(petta.RULES.resolve(), ROOT / "mork/rules")
        cases = {case.key: case for case in generate_cases(quick=True)}
        for key in ("E1_node", "E1_overwrite_field", "E6_rebuild_10"):
            with self.subTest(case=key), tempfile.TemporaryDirectory() as directory:
                case = cases[key]
                inverse = (inverse_operations(case.operations[0], case.graph)
                           if case.operations else [])
                program = petta.make_program(case, Path(directory), 1, 0, inverse)
                for module in ("frontier", "dependency-taint"):
                    self.assertTrue((petta.RULES / f"{module}.metta").is_file())
                    self.assertIn(str(petta.RULES / module), program)
                suffix = "journal" if case.experiment == "E6" else "data"
                fixture = Path(directory) / f"{key}-{suffix}.metta"
                self.assertTrue(fixture.is_file())
                self.assertIn(str(fixture), program)
                if inverse:
                    self.assertIn("PTPS_CHECK", program)
                    self.assertIn("PTPS_RESTORED", program)

    def test_cli_help_imports_the_active_package_without_native_runtime(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
        result = subprocess.run(
            [sys.executable, "-m", "mork.bench", "--help"], cwd=ROOT,
            env=environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--experiment", result.stdout)
        self.assertIn("--resume", result.stdout)
        self.assertIn("E6", result.stdout)

    def test_worker_module_dispatch_records_launcher_failure_without_native_runtime(self):
        case = generate_cases(quick=True)[0]
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            case_file = directory / "case.json"
            case_file.write_text(json.dumps(asdict(case)))
            outfile = directory / "result.json"
            config = {
                "case_file": str(case_file), "outfile": str(outfile),
                "backend": "mork-petta", "trial": 0, "samples": 1, "warmup": 0,
                "petta": str(directory / "missing-petta-launcher"),
                "artifacts": str(directory / "artifacts"),
            }
            config_file = directory / "config.json"
            config_file.write_text(json.dumps(config))
            environment = os.environ.copy()
            environment["PYTHONPATH"] = os.pathsep.join((str(ROOT / "src"), str(ROOT)))
            result = subprocess.run(
                [sys.executable, "-m", "mork.bench.harness", str(config_file)],
                cwd=ROOT, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertTrue(outfile.is_file(), result.stderr)
            row = json.loads(outfile.read_text())
            self.assertEqual(row["case"], case.key)
            self.assertEqual(row["status"], "error")
            self.assertEqual(row["error_type"], "FileNotFoundError")
            self.assertNotIn("median_us", row)
            self.assertTrue((directory / "artifacts/run.metta").is_file())


class EvidenceProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / "run"
        self.case = generate_cases(quick=True)[0]
        self.library = self.directory / "test-library.so"
        self.library.write_bytes(b"Not loaded: the worker is mocked in this test.\n")
        self.launcher = self.directory / "test-petta"
        self.launcher.write_text("#!/bin/sh\nexit 1\n")
        self.arguments = [
            "--backend", "mork-ffi", "--quick", "--repeats", "1", "--samples", "1",
            "--warmup", "0", "--output-dir", str(self.output),
            "--mork-library", str(self.library), "--petta", str(self.launcher),
        ]

    def complete_fake_run(self):
        def launch(command, **kwargs):
            self.assertEqual(command[1:3], ["-m", "mork.bench.harness"])
            config = json.loads(Path(command[-1]).read_text())
            row = {
                "case": self.case.key, "experiment": self.case.experiment,
                "backend": config["backend"], "trial": config["trial"], "status": "ok",
                "samples_us": [1.0], "median_us": 1.0, "p95_us": 1.0,
                "correctness": "passed",
            }
            Path(config["outfile"]).write_text(json.dumps(row))
            return SimpleNamespace(wait=lambda **kwargs: None, returncode=0, pid=123456)

        with patch.object(harness, "generate_cases", return_value=[self.case]), \
             patch.object(harness.platform, "platform", return_value="test-platform"), \
             patch.object(harness.subprocess, "Popen", side_effect=launch) as worker, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(harness.main(self.arguments), 0)
        worker.assert_called_once()
        return json.loads((self.output / "environment.json").read_text())

    def assert_rejected_without_changes(self, arguments):
        before = fingerprint(self.output)
        with patch.object(harness, "generate_cases", return_value=[self.case]), \
             patch.object(harness.platform, "platform", return_value="test-platform"), \
             patch.object(harness.subprocess, "Popen") as worker, \
             redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as rejected:
                harness.main(arguments)
        self.assertNotEqual(rejected.exception.code, 0)
        worker.assert_not_called()
        self.assertEqual(fingerprint(self.output), before)

    def test_snapshots_preserve_nested_active_and_application_source_paths(self):
        metadata = self.complete_fake_run()
        self.assertEqual(metadata["layout_version"], 2)
        hashes = metadata["source_sha256"]
        required = {
            "mork/bench/__main__.py", "mork/bench/experiments.py", "mork/bench/harness.py",
            "mork/bench/reporting.py", "mork/bench/backends/__init__.py",
            "mork/bench/backends/mork_ffi.py", "mork/bench/backends/_ffi_transport.py",
            "mork/bench/backends/petta.py", "mork/bench/backends/neo4j.py",
            "mork/rules/frontier.metta", "mork/rules/dependency-taint.metta",
            "neo4j_adapter/adapter.py",
        }
        self.assertTrue(required.issubset(hashes), sorted(required - hashes.keys()))
        self.assertEqual(metadata["launcher_sha256"], hashlib.sha256(self.launcher.read_bytes()).hexdigest())
        for relative, digest in hashes.items():
            with self.subTest(source=relative):
                self.assertFalse({"results", "archive", "tests"}.intersection(Path(relative).parts))
                self.assertEqual(hashlib.sha256((ROOT / relative).read_bytes()).hexdigest(), digest)
                snapshot = self.output / "measured-source" / relative
                self.assertTrue(snapshot.is_file())
                self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), digest)

    def test_old_layout_resume_is_rejected_before_modifying_saved_evidence(self):
        metadata = self.complete_fake_run()
        for version in (None, 1):
            with self.subTest(layout_version=version):
                previous = deepcopy(metadata)
                if version is None:
                    previous.pop("layout_version")
                else:
                    previous["layout_version"] = version
                (self.output / "environment.json").write_text(json.dumps(previous))
                self.assert_rejected_without_changes([*self.arguments, "--resume"])

    def test_resume_rejects_changed_backend_harness_and_application_hashes(self):
        metadata = self.complete_fake_run()
        for relative in (
                "mork/bench/backends/mork_ffi.py", "mork/bench/backends/petta.py",
                "mork/bench/harness.py", "mork/rules/frontier.metta", "neo4j_adapter/adapter.py"):
            with self.subTest(source=relative):
                previous = deepcopy(metadata)
                self.assertIn(relative, previous["source_sha256"])
                previous["source_sha256"][relative] = "0" * 64
                (self.output / "environment.json").write_text(json.dumps(previous))
                self.assert_rejected_without_changes([*self.arguments, "--resume"])

    def test_resume_requires_the_exact_source_set_and_runtime_hashes(self):
        metadata = self.complete_fake_run()
        for change in ("missing_source", "extra_source", "library_sha256", "launcher_sha256", "runtime_sha256"):
            with self.subTest(change=change):
                previous = deepcopy(metadata)
                if change == "missing_source":
                    previous["source_sha256"].pop("mork/bench/backends/neo4j.py")
                elif change == "extra_source":
                    previous["source_sha256"]["mork/bench/backends/stale.py"] = "0" * 64
                else:
                    previous[change] = "0" * 64
                (self.output / "environment.json").write_text(json.dumps(previous))
                self.assert_rejected_without_changes([*self.arguments, "--resume"])


if __name__ == "__main__":
    unittest.main()
