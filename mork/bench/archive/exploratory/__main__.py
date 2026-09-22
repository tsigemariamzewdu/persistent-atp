"""CLI for benchmarks run through `petta file.metta`."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .experiments import EXPERIMENTS, cases
from .harness import Report, Row, detect_runtime, parse_rows, program, run_petta, summarize
from .workload import commands


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", choices=EXPERIMENTS, action="append",
                        help="repeat to select experiments; default: all")
    parser.add_argument("--quick", action="store_true", help="small workloads, 10 samples")
    parser.add_argument("--iterations", type=int, help="measured query repetitions")
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--petta", default="petta", help="PeTTa executable or launcher path")
    parser.add_argument("--petta-arg", action="append", default=[], help="extra argument after the .metta path")
    parser.add_argument("--timeout", type=float, default=120, help="seconds per PeTTa process")
    parser.add_argument("--json", type=Path, help="save result rows as JSON")
    parser.add_argument("--compare-dict", action="store_true", help="measure equivalent indexed Python-dict queries")
    parser.add_argument("--comparison-markdown", type=Path, help="save comparison table (requires --compare-dict)")
    parser.add_argument("--output-dir", type=Path, help="retain runnable .metta files and logs here")
    parser.add_argument("--generate-only", action="store_true", help="generate files without running PeTTa")
    parser.add_argument("--allow-petta-space", action="store_true",
                        help="explicitly permit non-MORK PeTTa space measurements")
    args = parser.parse_args(argv)
    iterations = args.iterations if args.iterations is not None else (10 if args.quick else 30)
    if iterations < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error("iterations and timeout must be positive; warmup must be nonnegative")
    if args.generate_only and not args.output_dir:
        parser.error("--generate-only requires --output-dir")
    if args.comparison_markdown and (not args.compare_dict or args.generate_only):
        parser.error("--comparison-markdown requires --compare-dict and an actual run")
    directory = args.output_dir or Path(tempfile.mkdtemp(prefix="petta-bench-"))
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    command = [args.petta, *args.petta_arg]
    report = Report()
    runtime = "not-run"
    print(f"Benchmark files and logs: {directory}", flush=True)
    try:
        if not args.generate_only:
            preflight = directory / "preflight.metta"
            preflight.write_text('!(println! (BENCH_INIT (mm2-exec &mork 1)))\n')
            runtime = detect_runtime(run_petta(command, preflight, args.timeout), args.allow_petta_space)
            print(f"Runtime: {runtime}", flush=True)
        for name in dict.fromkeys(args.experiment or EXPERIMENTS):
            for case in cases(name, args.quick):
                samples = []
                for index in range(iterations + args.warmup if name == "L1" else 1):
                    start = time.perf_counter_ns()
                    data = commands(case.nodes, case.background, claims=case.claims)
                    elapsed = (time.perf_counter_ns() - start) / 1000
                    if index >= args.warmup:
                        samples.append(elapsed)
                data_path = directory / f"{case.stem}_data.metta"
                data_path.write_text("\n".join(data) + "\n")
                script = directory / f"{case.stem}.metta"
                script.write_text(program(case, data_path, len(data), iterations, args.warmup))
                print(f"{case.stem}: {EXPERIMENTS[name]}", flush=True)
                if args.generate_only:
                    continue
                output = run_petta(command, script, args.timeout)
                if detect_runtime(output, args.allow_petta_space) != runtime:
                    raise RuntimeError("Runtime changed between processes")
                report.rows.extend(parse_rows(output, case, len(data), iterations, runtime))
                if args.compare_dict:
                    from .dict_baseline import measure_case
                    report.rows.extend(measure_case(case, data, iterations, args.warmup))
                if name == "L1":
                    median, p95 = summarize(samples)
                    report.rows.append(Row(name, "generate-and-project", case.scale, len(data),
                                           median, p95, iterations, "python", clock="python_monotonic",
                                           note="synthetic journal generation + production projector; no file I/O"))
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1
    if not args.generate_only:
        print(report.render())
        if args.json:
            args.json.write_text(report.to_json() + "\n")
        if args.compare_dict:
            from .dict_baseline import comparison_markdown
            comparison = comparison_markdown(report.rows)
            print(comparison)
            if args.comparison_markdown:
                args.comparison_markdown.write_text(comparison)
    return 0


if __name__ == "__main__":
    sys.exit(main())
