"""Common E1--E6 evaluation of MORK FFI, MORK through PeTTa, and Neo4j."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import sys
import time

from .spec import EXPERIMENTS, generate_cases
from .harness import summarize

ROOT = Path(__file__).resolve().parents[2]
BACKENDS = ('mork-ffi', 'mork-petta', 'neo4j')


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def cleanup_interrupted(checkpoint):
    if not checkpoint.exists():
        return
    from neo4j_adapter.adapter import Neo4jAdapter
    data = json.loads(checkpoint.read_text())
    with Neo4jAdapter() as adapter:
        adapter._write_all('benchmark_interrupted_cleanup', [(
            'MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run=$token DETACH DELETE n', data)])
        remaining = adapter._read_value('benchmark_interrupted_count',
            'MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run=$token RETURN count(n) AS n', data, 'n')
        if remaining != 0:
            raise RuntimeError('Interrupted fixture cleanup failed')
    checkpoint.unlink()


def aggregate(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row['case'], row['backend']), []).append(row)
    result = []
    for (case, backend), trials in groups.items():
        ok = [row for row in trials if row['status'] == 'ok']
        failures = [row for row in trials if row['status'] != 'ok']
        item = {'case': case, 'experiment': trials[0]['experiment'], 'backend': backend,
                'successful_trials': len(ok), 'attempted_trials': len(trials),
                'status': failures[-1]['status'] if failures else 'ok'}
        if ok:
            medians = [r['median_us'] for r in ok]
            samples = [value for r in ok for value in r['samples_us']]
            item.update(median_us=statistics.median(medians),
                        pooled_p95_us=summarize(samples)[1],
                        trial_median_min_us=min(medians), trial_median_max_us=max(medians))
        result.append(item)
    return result


def report(cases, rows, metadata):
    summaries = aggregate(rows)
    index = {(r['case'], r['backend']): r for r in summaries}
    out = ['# PTPS graph benchmarks: E1–E6', '',
        'This report evaluates **MORK through Python FFI**, **MORK through PeTTa**, and **Neo4j** using the same logical workloads and output contracts. Ordinary PeTTa space and the Python correctness oracle are not measured backends.', '',
        f'Run status: **{metadata["status"]}**. Started {metadata["started_at"]}.', '',
        f'Configuration: {metadata["repeats"]} independent trials per successful case/backend; '
        f'{metadata["samples"]} measured calls after {metadata["warmup"]} warm-ups per trial; '
        f'{metadata["timeout"]:g} seconds maximum for an entire trial including setup and validation. '
        'E6 runs one cold projection rebuild per independent trial with no operation warm-up.', '',
        'Tables show **median microseconds per logical operation for E1–E5, and per complete rebuild for E6** (median of trial medians). '
        'A timeout/error has no invented timing and stops further repetitions of that case/backend. '
        'Timeouts bound the complete trial, not necessarily a single query. Raw single-call timings, pooled p95, and trial ranges are in the JSON artifacts.', '',
        '## Runtime identity and measurement boundary', '',
        f'- Python {metadata["python"]}; platform {metadata["platform"]}.',
        f'- MORK library SHA256: `{metadata.get("library_sha256", "unavailable")}`. Both MORK paths preload this identical binary.',
        '- The isolated PeTTa bridge has documented flush-registration and conjunctive-match compatibility patches. Its ordinary-space fallback is rejected. See [runtime manifest](runtime/source-versions.json) and [patch](runtime/runtime-compatibility.patch).',
        '- Each operation returns a fully materialized common result. Setup, graph loading, checking and restoration are outside the timer. Neo4j includes native managed transaction/transport and commit acknowledgement; MORK mutations include index updates and read-visible completion. These are not equal durable-commit guarantees.',
        '- PeTTa clocks are read through its Python bridge; that timer overhead remains. Timings use monotonic elapsed time, not the historical CPU-time measurements.',
        '- Field/edge mutation fixtures are restored outside timing and checked to prevent duplicate or no-op measurements. New MORK processes isolate the process-wide native space. Neo4j fixtures have unique ownership and proof namespaces and verified cleanup.',
        '- Frontier returns state-scoped unique move IDs with mixed eligibility; taint checks a refuted root and returns unique dependent claim IDs. The two MORK paths use identical node/field/layer/edge/rev-edge atom shapes.',
        '- FFI frontier joins and dependency traversal execute in Python over native MORK matches. PeTTa evaluates the existing MeTTa rules with real MORK lookups. Neo4j uses matching native Cypher through the adapter transaction layer. These are integration implementations, not isolated engine timings.', '',
        '## Results', '']
    for experiment, title in EXPERIMENTS.items():
        selected = [c for c in cases if c.experiment == experiment]
        if not selected:
            continue
        out.extend([f'### {experiment} — {title}', '',
            '| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |',
            '| --- | ---: | ---: | ---: | ---: | ---: |'])
        for case in selected:
            cells = []
            for backend in BACKENDS:
                value = index.get((case.key, backend))
                if value is None:
                    cells.append('not selected')
                elif value['status'] == 'ok':
                    cells.append(f'{value["median_us"]:,.2f}')
                else:
                    cells.append(value['status'])
            out.append(f'| {case.key} | {case.scale} | {case.node_count:,} / {case.edge_count:,} | ' + ' | '.join(cells) + ' |')
        if experiment == 'E6':
            out.extend(['', 'E6 reports **total rebuild time**, not per-event latency. Journal counts: ' +
                ', '.join(f'{c.scale:,} created nodes → {len(c.journal):,} operations' for c in selected) +
                '. PeTTa total adds generation of its executable journal to runtime import/parse/application time; the components are retained in trial metadata. This is empty-projection rebuild from prevalidated history, not process crash recovery.'])
        out.append('')
    failed = [r for r in rows if r['status'] != 'ok']
    out.extend(['## Validation and limitations', '',
        f'{sum(r["status"] == "ok" for r in rows)} successful, fully checked trials; {len(failed)} unsuccessful trials. '
        'Successful read trials validate returned values against an independent oracle. Successful mutation trials verify changed state and restoration; complete final graphs and MORK reverse indexes are also checked.', '',
        'This is a sequential, warm-operation evaluation on one machine; independent trials do not constitute a hardware population or confidence interval. Frontier result count changes with eligibility. Dependency graphs include direct stars, long chains, and bounded-depth reconvergent DAGs; all non-root claims are affected. Graph sizes and answer sizes are recorded, and the entire workload grid is retained even when a backend fails.', '',
        'Neo4j retains its normal indexes and native durability costs. Other data may exist on that server; this is not isolated-server throughput. Memory reclamation, durable PTPS commits, process restart, concurrent load, and theorem-proving success are not measured.', ''])
    if failed:
        out.extend(['### Unsuccessful trials', '', '| Case | Backend | Status | Detail |', '| --- | --- | --- | --- |'])
        for r in failed:
            detail = str(r.get('error', '')).replace('|', '/').replace('\n', ' ')[:220]
            out.append(f'| {r["case"]} | {r["backend"]} | {r["status"]} | {detail} |')
    out.extend(['', '## Reproduction and evidence', '',
        'Detailed definitions and per-experiment instructions: [METHODOLOGY.md](../../METHODOLOGY.md).', '',
        '```sh', metadata['command'], '```', '',
        '- [Individual trial records and samples](trials.json)',
        '- [Aggregated medians, pooled p95, and trial ranges](summary.json)',
        '- [Environment, command, source hashes and run status](environment.json)',
        '- [Measured benchmark source](measured-source/) preserves the files identified by the recorded source hashes.',
        '- Generated scripts, case inputs and worker logs are retained locally in `artifacts/` (excluded from Git).', ''])
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('all', *BACKENDS), default='all')
    parser.add_argument('--experiment', choices=EXPERIMENTS, action='append')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--scales', default='100,1000,10000')
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--samples', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--output-dir', type=Path, default=Path('mork/bench/results/common-e1-e6'))
    parser.add_argument('--mork-library', type=Path, default=ROOT/'.bench-runtime/PeTTa/mork_ffi/target/release/libmork_ffi.so')
    parser.add_argument('--petta', type=Path, default=ROOT/'scripts/bench-petta.sh')
    parser.add_argument('--resume', action='store_true', help='Continue an interrupted output directory with identical workloads and timing settings')
    args = parser.parse_args(argv)
    if min(args.repeats, args.samples) < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error('repeats/samples/timeout must be positive; warmup nonnegative')
    try:
        scales = tuple(int(v) for v in args.scales.split(','))
        cases = generate_cases(args.quick, scales)
    except ValueError as exc:
        parser.error(str(exc))
    cases = [c for c in cases if not args.experiment or c.experiment in args.experiment]
    selected = list(BACKENDS if args.backend == 'all' else [args.backend])
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    artifacts = output / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    (output/'.gitignore').write_text('artifacts/\n')
    runtime = output/'runtime'
    runtime.mkdir(exist_ok=True)
    for name in ('source-versions.json', 'runtime-compatibility.patch'):
        source = ROOT/'.bench-runtime'/name
        if source.exists():
            shutil.copy2(source, runtime/name)
    library = args.mork_library.resolve()
    runner = args.petta.resolve()
    import shlex
    metadata = {'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                'python': platform.python_version(), 'platform': platform.platform(),
                'repeats': args.repeats, 'samples': args.samples, 'warmup': args.warmup,
                'timeout': args.timeout, 'backend_order': 'rotated by independent trial',
                'command': 'PYTHONPATH=src:. .venv/bin/python -m mork.bench ' + shlex.join(sys.argv[1:] if argv is None else argv),
                'library_path': str(library), 'petta_runner': str(runner),
                'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted((ROOT/'mork/bench').glob('*.py'))}}
    if library.exists():
        metadata['library_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    rows, stopped = [], set()
    metadata['case_keys'] = [case.key for case in cases]
    metadata['selected_backends'] = selected
    if args.resume:
        previous = json.loads((output/'environment.json').read_text())
        original_tokens = shlex.split(previous['command'])
        original_args = parser.parse_args(original_tokens[original_tokens.index('mork.bench') + 1:])
        for key in ('backend', 'experiment', 'quick', 'scales', 'repeats', 'samples', 'warmup', 'timeout'):
            if getattr(original_args, key) != getattr(args, key):
                parser.error(f'Cannot resume with a changed {key}; use the original settings')
        if metadata.get('library_sha256') != previous.get('library_sha256'):
            parser.error('Cannot resume with a different MORK library')
        for name, digest in previous['source_sha256'].items():
            if name != 'mork/bench/unified.py' and metadata['source_sha256'].get(name) != digest:
                parser.error(f'Cannot resume after measured source changed: {name}')
        rows = json.loads((output/'trials.json').read_text())
        interrupted_rows = [r for r in rows if r['status'] == 'interrupted']
        rows = [r for r in rows if r['status'] != 'interrupted']
        previous.setdefault('continuations', []).append({
            'resumed_at': metadata['started_at'], 'command': metadata['command'],
            'retained_trials': len(rows), 'interrupted_trials': interrupted_rows,
            'driver_sha256': metadata['source_sha256']['mork/bench/unified.py']})
        previous.update(status='running', case_keys=metadata['case_keys'], selected_backends=selected)
        previous.pop('finished_at', None)
        metadata = previous
        resumed_source = output/'continuation-source'
        resumed_source.mkdir(exist_ok=True)
        shutil.copy2(ROOT/'mork/bench/unified.py', resumed_source/'unified.py')
        stopped = {(r['case'], r['backend']) for r in rows if r['status'] != 'ok'}
    else:
        measured_source = output/'measured-source'
        measured_source.mkdir(exist_ok=True)
        for name in metadata['source_sha256']:
            shutil.copy2(ROOT/name, measured_source/Path(name).name)
    completed = {(r['case'], r['backend'], r['trial']) for r in rows}
    write_json(output/'environment.json', metadata)
    for case in cases:
        case_file = artifacts/f'{case.key}.json'
        write_json(case_file, asdict(case))
        for trial in range(args.repeats):
            ordered = selected[trial % len(selected):] + selected[:trial % len(selected)]
            for backend in ordered:
                if (case.key, backend) in stopped or (case.key, backend, trial) in completed:
                    continue
                name = f'{case.key}-{backend}-{trial}'
                trial_dir = artifacts/name
                outfile = trial_dir/'result.json'
                # A crashed worker must never inherit a previous run's success.
                cleanup_interrupted(Path(str(outfile) + '.cleanup.json'))
                if args.resume and trial_dir.exists():
                    archive = artifacts/'interrupted-attempts'
                    archive.mkdir(exist_ok=True)
                    shutil.move(str(trial_dir), str(archive/(name + '-' + str(time.time_ns()))))
                trial_dir.mkdir(exist_ok=True)
                outfile.unlink(missing_ok=True)
                config = {'case_file': str(case_file), 'outfile': str(outfile), 'backend': backend,
                          'trial': trial, 'samples': args.samples, 'warmup': args.warmup,
                          'artifacts': str(trial_dir), 'petta': str(runner)}
                config_file = trial_dir/'config.json'
                write_json(config_file, config)
                env = dict(os.environ)
                env['PYTHONPATH'] = str(ROOT/'src') + os.pathsep + str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
                if backend in ('mork-ffi', 'mork-petta'):
                    env['MORK_LIBRARY'] = str(library)
                    env['LD_PRELOAD'] = str(library)
                print(f'{case.key} / {backend} / trial {trial + 1}', flush=True)
                start = time.monotonic()
                timeout = False
                interrupted = False
                with (trial_dir/'worker.log').open('w') as log:
                    proc = subprocess.Popen([sys.executable, '-m', 'mork.bench.worker', str(config_file)],
                                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
                    try:
                        proc.wait(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        timeout = True
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                    except KeyboardInterrupt:
                        interrupted = True
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                if interrupted or timeout or not outfile.exists():
                    row = {'case': case.key, 'experiment': case.experiment, 'backend': backend, 'trial': trial,
                           'status': 'interrupted' if interrupted else 'timeout' if timeout else 'error',
                           'error': 'Interrupted by user' if interrupted else f'Whole trial exceeded {args.timeout:g}s' if timeout else f'Worker exited {proc.returncode} before reporting'}
                else:
                    row = json.loads(outfile.read_text())
                try:
                    cleanup_interrupted(Path(str(outfile) + '.cleanup.json'))
                except Exception as exc:
                    row.update(status='cleanup_error', error=str(exc))
                row['trial_wall_seconds'] = time.monotonic() - start
                rows.append(row)
                if row['status'] != 'ok':
                    stopped.add((case.key, backend))
                    print(f'  {row["status"]}: {row.get("error", "")[:160]}', flush=True)
                write_json(output/'trials.json', rows)
                write_json(output/'summary.json', aggregate(rows))
                (output/'results.md').write_text(report(cases, rows, metadata))
                if interrupted:
                    metadata.update(status='interrupted', finished_at=datetime.now(timezone.utc).isoformat(),
                                    total_trials=len(rows), failed_case_backends=len(stopped))
                    write_json(output/'environment.json', metadata)
                    (output/'results.md').write_text(report(cases, rows, metadata))
                    return 130
    metadata.update(status='complete_with_failures' if stopped else 'complete',
                    finished_at=datetime.now(timezone.utc).isoformat(), total_trials=len(rows),
                    failed_case_backends=len(stopped))
    write_json(output/'environment.json', metadata)
    (output/'results.md').write_text(report(cases, rows, metadata))
    print(f'Wrote {output / "results.md"}; status={metadata["status"]}', flush=True)
    return 1 if stopped else 0
