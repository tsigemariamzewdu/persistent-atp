"""Generate MeTTa timing programs, run PeTTa, and validate/report samples."""
from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .experiments import Case

RULES = Path(__file__).resolve().parents[3] / "rules"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Row:
    experiment: str
    operation: str
    scale: int
    atoms: int
    median: float
    p95: float
    iterations: int
    runtime: str
    unit: str = "us"
    clock: str = "petta_cpu"
    note: str = ""


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)

    def render(self) -> str:
        lines = ["exp operation                  scale    atoms    median       p95 unit clock runtime"]
        for row in self.rows:
            lines.append(f"{row.experiment:<3} {row.operation:<26} {row.scale:>6} {row.atoms:>8} "
                         f"{row.median:>9.2f} {row.p95:>9.2f} {row.unit:<4} {row.clock} {row.runtime}")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps([asdict(row) for row in self.rows], indent=2)


def summarize(samples: list[float]) -> tuple[float, float]:
    if not samples or any(not math.isfinite(x) or x < 0 for x in samples):
        raise ValueError("Missing, negative, or non-finite timing samples")
    ordered = sorted(samples)
    return statistics.median(ordered), ordered[math.ceil(len(ordered) * .95) - 1]


def run_petta(command: list[str], script: Path, timeout: float) -> str:
    """Keep verbose compiler output on disk rather than in the report."""
    log = script.with_suffix(".log")
    with log.open("w") as handle:
        result = subprocess.run([command[0], str(script.resolve()), *command[1:], "--silent"],
                                stdout=handle, stderr=subprocess.STDOUT, timeout=timeout)
    output = ANSI.sub("", log.read_text())
    if result.returncode or re.search(r"^ERROR[: ]", output, re.MULTILINE):
        raise RuntimeError(f"PeTTa failed for {script.name}; see {log}\n{output[-2000:]}")
    return output


def detect_runtime(output: str, allow_petta_space: bool) -> str:
    markers = re.findall(r"^\(BENCH_INIT (.*)\)$", output, re.MULTILINE)
    if len(markers) != 1:
        raise RuntimeError("PeTTa did not emit exactly one BENCH_INIT marker")
    if "mm2-exec" in markers[0] or "partial" in markers[0]:
        if allow_petta_space:
            return "petta-space"
        raise RuntimeError(
            "MORK is not active: mm2-exec remained unevaluated. Configure your PeTTa "
            "launcher to load MORK, or pass --petta /path/to/a/MORK-enabled/runner. "
            "Use --allow-petta-space only to benchmark the ordinary PeTTa space; "
            "those results are NOT MORK measurements."
        )
    return "petta-mork"


def program(case: Case, data_path: Path, atoms: int, iterations: int, warmup: int,
            *, wall_clock: bool = False, batch_size: int = 1) -> str:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    timer = '(py-call ("time.monotonic_ns"))' if wall_clock else '(statistics cputime)'
    elapsed = '(/ (- $end $start) 1000)' if wall_clock else '(* (- $end $start) 1000000)'
    lines = ['!(println! (BENCH_INIT (mm2-exec &mork 1)))',
             '!(import_prolog_function statistics)']
    for module in ("index_views", "frontier", "dependency-taint"):
        lines.append(f'!(import! &self {json.dumps(str(RULES / module))})')
    # Loading is measured within the runtime. Includes parsing and executing the
    # projected file, but excludes process startup and the query module imports.
    lines.append(f'!(let* (($start {timer}) '
                 f'($loaded (import! &self {json.dumps(str(data_path.resolve()))})) '
                 f'($end {timer})) '
                 f'(println! (BENCH_LOAD {elapsed})))')
    lines.extend([
        f'!(test (size-atom (collapse (get-atoms &mork))) {atoms})',
        '!(println! (BENCH_ATOMS (size-atom (collapse (get-atoms &mork)))))',
    ])
    for index, probe in enumerate(case.probes):
        lines.append(f'!(test {probe.expression} {probe.expected})')
        measured = probe.expression
        if batch_size > 1:
            lines.append(f'(= (bench-repeat-{index} $n) '
                         f'(if (== $n 0) True (let $result {probe.expression} '
                         f'(bench-repeat-{index} (- $n 1)))))')
            measured = f'(bench-repeat-{index} {batch_size})'
        for _ in range(warmup):
            lines.append(f'!{measured}')
        for _ in range(iterations):
            lines.append(f'!(let* (($start {timer}) ($result {measured}) '
                         f'($end {timer})) '
                         f'(println! (BENCH_SAMPLE {index} (/ {elapsed} {batch_size}))))')
        lines.append(f'!(test {probe.expression} {probe.expected})')
    lines.extend([
        f'!(test (size-atom (collapse (get-atoms &mork))) {atoms})',
        '!(println! BENCH_DONE)',
    ])
    return "\n".join(lines) + "\n"


def parse_rows(output: str, case: Case, atoms: int, iterations: int, runtime: str) -> list[Row]:
    if not re.search(r"^BENCH_DONE$", output, re.MULTILINE):
        raise RuntimeError("Benchmark did not complete its correctness checks")
    counts = re.findall(r"^\(BENCH_ATOMS (\d+)\)$", output, re.MULTILINE)
    if counts != [str(atoms)]:
        raise RuntimeError(f"Unexpected atom count: {counts}; expected {atoms}")
    values: dict[int, list[float]] = {}
    for index, value in re.findall(r"^\(BENCH_SAMPLE (\d+) ([^ ()]+)\)$", output, re.MULTILINE):
        values.setdefault(int(index), []).append(float(value))
    if set(values) != set(range(len(case.probes))):
        raise RuntimeError("Missing or unexpected probe sample IDs")
    rows = []
    for index, probe in enumerate(case.probes):
        samples = values[index]
        if len(samples) != iterations:
            raise RuntimeError(f"{probe.name}: expected {iterations} samples, got {len(samples)}")
        median, p95 = summarize(samples)
        rows.append(Row(case.experiment, probe.name, case.scale, atoms, median, p95,
                        iterations, runtime, note="PeTTa CPU time; startup/load excluded"))
    if case.experiment == "L1":
        loads = re.findall(r"^\(BENCH_LOAD ([^ ()]+)\)$", output, re.MULTILINE)
        if len(loads) != 1:
            raise RuntimeError("Missing or duplicate load timing")
        median, p95 = summarize([float(loads[0])])
        rows.append(Row("L1", "load-projection", case.scale, atoms, median, p95, 1,
                        runtime, note="one shot; includes parsing and executing projected file"))
    return rows
