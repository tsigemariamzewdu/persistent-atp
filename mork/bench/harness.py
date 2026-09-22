"""Run isolated benchmark trials, validate results, and coordinate resumable evaluations.

Use ``python -m mork.bench`` for the CLI. Running this module directly is the
internal worker entry point: ``python -m mork.bench.harness CONFIG.json``.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import traceback

from .experiments import (EXPERIMENTS, Case, Operation, Oracle, canonical_graph,
                          expected_result, generate_cases, inverse_operations,
                          mutation_check, normalize_result)
from .backends.mork_ffi import graph_atoms, parse, MorkBackend
from .reporting import BACKENDS, aggregate, report, summarize

ROOT = Path(__file__).resolve().parents[2]
LAYOUT_VERSION = 2


def source_hashes():
    """Identify the active runner, backends, and application rules it measures."""
    paths = set((ROOT/'mork/bench').glob('*.py'))
    paths.update((ROOT/'mork/bench/backends').glob('*.py'))
    paths.update((ROOT/'mork/rules').glob('*.metta'))
    paths.update((ROOT/'neo4j_adapter').glob('*.py'))
    paths.add(ROOT/'scripts/bench-petta.sh')
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


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
    if output.exists() and not output.is_dir():
        parser.error('Output path must be a directory')
    if not args.resume and output.exists() and any(output.iterdir()):
        parser.error('Output directory is not empty; use a fresh directory or --resume')
    library = args.mork_library.resolve()
    runner = args.petta.resolve()
    runtime_files = [ROOT/'.bench-runtime'/name
                     for name in ('source-versions.json', 'runtime-compatibility.patch')]
    metadata = {'layout_version': LAYOUT_VERSION,
                'status': 'running', 'started_at': datetime.now(timezone.utc).isoformat(),
                'python': platform.python_version(), 'platform': platform.platform(),
                'repeats': args.repeats, 'samples': args.samples, 'warmup': args.warmup,
                'timeout': args.timeout, 'backend_order': 'rotated by independent trial',
                'command': 'PYTHONPATH=src:. .venv/bin/python -m mork.bench ' + shlex.join(sys.argv[1:] if argv is None else argv),
                'library_path': str(library), 'petta_runner': str(runner),
                'methodology_path': os.path.relpath(ROOT/'mork/bench/docs/METHODOLOGY.md', output),
                'source_sha256': source_hashes(),
                'runtime_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in runtime_files if path.is_file()}}
    if library.exists():
        metadata['library_sha256'] = hashlib.sha256(library.read_bytes()).hexdigest()
    if runner.exists():
        metadata['launcher_sha256'] = hashlib.sha256(runner.read_bytes()).hexdigest()
    rows, stopped = [], set()
    metadata['case_keys'] = [case.key for case in cases]
    metadata['selected_backends'] = selected
    if args.resume:
        try:
            previous = json.loads((output/'environment.json').read_text())
            rows = json.loads((output/'trials.json').read_text())
        except (OSError, ValueError) as exc:
            parser.error(f'Cannot resume without readable environment.json and trials.json: {exc}')
        if previous.get('layout_version') != LAYOUT_VERSION:
            parser.error('Cannot resume an older-layout evaluation; its original source snapshots '
                         'are preserved. Start a fresh output directory with this runner')
        original_tokens = shlex.split(previous['command'])
        original_args = parser.parse_args(original_tokens[original_tokens.index('mork.bench') + 1:])
        for key in ('backend', 'experiment', 'quick', 'scales', 'repeats', 'samples', 'warmup', 'timeout'):
            if getattr(original_args, key) != getattr(args, key):
                parser.error(f'Cannot resume with a changed {key}; use the original settings')
        if metadata.get('library_sha256') != previous.get('library_sha256'):
            parser.error('Cannot resume with a different MORK library')
        if metadata.get('launcher_sha256') != previous.get('launcher_sha256'):
            parser.error('Cannot resume with a different PeTTa launcher')
        if metadata['runtime_sha256'] != previous.get('runtime_sha256'):
            parser.error('Cannot resume with changed runtime records')
        if metadata['source_sha256'] != previous.get('source_sha256'):
            parser.error('Cannot resume after measured source changed; use a fresh output directory')
        if (metadata['case_keys'] != previous.get('case_keys') or
                selected != previous.get('selected_backends')):
            parser.error('Cannot resume with different cases or backends')
        interrupted_rows = [r for r in rows if r['status'] == 'interrupted']
        rows = [r for r in rows if r['status'] != 'interrupted']
        previous.setdefault('continuations', []).append({
            'resumed_at': metadata['started_at'], 'command': metadata['command'],
            'retained_trials': len(rows), 'interrupted_trials': interrupted_rows,
            'driver_sha256': metadata['source_sha256']['mork/bench/harness.py']})
        previous.update(status='running', case_keys=metadata['case_keys'], selected_backends=selected)
        previous.pop('finished_at', None)
        metadata = previous
        stopped = {(r['case'], r['backend']) for r in rows if r['status'] != 'ok'}

    # Validation above must not alter an existing evaluation, even on rejection.
    output.mkdir(parents=True, exist_ok=True)
    artifacts = output/'artifacts'
    artifacts.mkdir(exist_ok=True)
    (output/'.gitignore').write_text('artifacts/\n')
    if not args.resume:
        runtime = output/'runtime'
        runtime.mkdir(exist_ok=True)
        for source in runtime_files:
            if source.is_file():
                shutil.copy2(source, runtime/source.name)
        measured_source = output/'measured-source'
        for name in metadata['source_sha256']:
            destination = measured_source/name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, destination)
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
                    proc = subprocess.Popen([sys.executable, '-m', 'mork.bench.harness', str(config_file)],
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


def read_case(path):
    value = json.loads(Path(path).read_text())
    value['operations'] = [Operation(**op) for op in value['operations']]
    return Case(**value)


def checked_equal(actual, expected, description):
    if actual != expected:
        raise RuntimeError(f'{description}: incorrect result (see validation artifact)')


def atom_set(values):
    return {json.dumps(value, sort_keys=True, separators=(',', ':')) for value in values}


def check_atoms(values, graph):
    expected = [parse(value) for value in graph_atoms(graph)]
    checked_equal(atom_set(values), atom_set(expected), 'MORK atom/index snapshot')
    checked_equal(len(values), len(expected), 'MORK atom count (duplicates)')


def run_python_backend(case, backend_name, samples, warmup, outfile):
    if backend_name == 'mork-ffi':
        backend = MorkBackend()
        metadata = {'library': os.environ.get('MORK_LIBRARY'), 'process_isolated': True}
    else:
        from .backends.neo4j import Neo4jBackend
        backend = Neo4jBackend()
        for proof in {n['proof'] for n in case.graph['nodes']}:
            backend._proof(proof)
        metadata = backend.metadata
        metadata['proof_namespaces'] = dict(backend.proofs)
        Path(str(outfile) + '.cleanup.json').write_text(json.dumps({
            'token': backend.token, 'pids': list(backend.proofs.values())}))
    values = []
    try:
        if case.experiment == 'E6':
            backend.load({'nodes': [], 'edges': []})
            start = time.monotonic_ns()
            for raw in case.journal:
                backend.execute(Operation(**raw))
            values.append((time.monotonic_ns() - start) / 1000)
            checked_equal(canonical_graph(backend.snapshot()), canonical_graph(case.graph), 'Rebuild final graph')
        else:
            backend.load(case.graph)
            checked_equal(canonical_graph(backend.snapshot()), canonical_graph(case.graph), 'Initial graph')
            op = case.operations[0]
            expected = normalize_result(op, expected_result(op, case.graph))
            inverse = inverse_operations(op, case.graph)
            check = mutation_check(op, case.graph)
            changed = Oracle(case.graph)
            changed.execute(op)
            if check:
                after = normalize_result(check, changed.execute(check))
                before = normalize_result(check, expected_result(check, case.graph))
            for index in range(1 + warmup + samples):
                start = time.monotonic_ns()
                answer = backend.execute(op)
                elapsed = (time.monotonic_ns() - start) / 1000
                checked_equal(normalize_result(op, answer), expected, 'Operation return')
                if check:
                    checked_equal(normalize_result(check, backend.execute(check)), after, 'Mutation took effect')
                for reset in inverse:
                    backend.execute(reset)
                if check:
                    checked_equal(normalize_result(check, backend.execute(check)), before, 'Mutation reset')
                if index > warmup:
                    values.append(elapsed)
            checked_equal(canonical_graph(backend.snapshot()), canonical_graph(case.graph), 'Restored final graph')
        if backend_name == 'mork-ffi':
            check_atoms([parse(value) for value in backend.space.atoms()], case.graph)
        return values, metadata
    finally:
        backend.close()
        if backend_name == 'neo4j':
            metadata['cleanup_verified'] = True
            Path(str(outfile) + '.cleanup.json').unlink(missing_ok=True)


def run_petta(case, runner, samples, warmup, directory):
    from .backends.petta import make_program
    directory.mkdir(parents=True, exist_ok=True)
    inverse = inverse_operations(case.operations[0], case.graph) if case.operations else []
    begin = time.monotonic_ns()
    source = make_program(case, directory, samples, warmup, inverse)
    generation_us = (time.monotonic_ns() - begin) / 1000
    path = directory / 'run.metta'
    path.write_text(source)
    log = directory / 'petta.log'
    with log.open('w') as output:
        result = subprocess.run([runner, str(path.resolve()), '--silent'], stdout=output, stderr=subprocess.STDOUT)
    text = re.sub(r'\x1b\[[0-9;]*m', '', log.read_text())
    if result.returncode or re.search(r'^ERROR[: ]', text, re.MULTILINE):
        raise RuntimeError(f'PeTTa failed; see {log}: {text[-1000:]}')
    init = re.findall(r'^\(PTPS_INIT (.*)\)$', text, re.MULTILINE)
    if len(init) != 1 or parse(init[0]) is not True:
        raise RuntimeError('Actual MORK is required; ordinary PeTTa fallback is not a measured backend')
    checked_equal(len(re.findall(r'^PTPS_DONE$', text, re.MULTILINE)), 1, 'PeTTa completion')
    values = []
    expected = normalize_result(case.operations[0], expected_result(case.operations[0], case.graph)) if case.operations else None
    counts = {'PTPS_RESULT': 0, 'PTPS_MUTATED': 0, 'PTPS_CHECK': 0, 'PTPS_RESTORED': 0}
    for line in text.splitlines():
        for marker in counts:
            if line.startswith('(' + marker + ' '):
                counts[marker] += 1
        if line.startswith('(PTPS_SAMPLE '):
            record = parse(line)
            values.append(float(record[2]))
            if case.operations:
                checked_equal(normalize_result(case.operations[0], record[3]), expected, 'PeTTa timed return')
        elif line.startswith('(PTPS_RESULT '):
            checked_equal(normalize_result(case.operations[0], parse(line)[1]), expected, 'PeTTa preflight return')
        elif line.startswith('(PTPS_MUTATED '):
            oracle = Oracle(case.graph)
            oracle.execute(case.operations[0])
            check_atoms(parse(line)[1], oracle.snapshot())
        elif line.startswith('(PTPS_CHECK '):
            op = case.operations[0]
            check = mutation_check(op, case.graph)
            oracle = Oracle(case.graph)
            oracle.execute(op)
            checked_equal(normalize_result(check, parse(line)[1]), normalize_result(check, oracle.execute(check)), 'PeTTa mutation effect')
        elif line.startswith('(PTPS_RESTORED '):
            check = mutation_check(case.operations[0], case.graph)
            checked_equal(normalize_result(check, parse(line)[1]), normalize_result(check, expected_result(check, case.graph)), 'PeTTa reset took effect')
    expected_counts = {'PTPS_RESULT': 0 if case.experiment == 'E6' else 1,
                       'PTPS_MUTATED': 1 if inverse else 0,
                       'PTPS_CHECK': samples if inverse else 0,
                       'PTPS_RESTORED': samples + warmup + 1 if inverse else 0}
    checked_equal(counts, expected_counts, 'PeTTa validation marker counts')
    snapshots = [parse(line)[1] for line in text.splitlines() if line.startswith('(PTPS_ATOMS ')]
    checked_equal(len(snapshots), 1, 'PeTTa snapshot presence')
    check_atoms(snapshots[0], case.graph)
    checked_equal(len(values), 1 if case.experiment == 'E6' else samples, 'PeTTa sample count')
    metadata = {'runner': runner, 'runtime_init': init[0], 'journal_generation_us': generation_us if case.experiment == 'E6' else 0}
    if case.experiment == 'E6':
        metadata['application_us'] = values[0]
        values[0] += generation_us
    return values, metadata


def run_trial(config_file):
    config = json.loads(Path(config_file).read_text())
    outfile = Path(config['outfile'])
    case = read_case(config['case_file'])
    row = {key: config[key] for key in ('backend', 'trial')}
    row.update(experiment=case.experiment, case=case.key, scale=case.scale,
               nodes=case.node_count, edges=case.edge_count,
               atoms=len(list(graph_atoms(case.graph))), journal_operations=len(case.journal),
               operation=case.operations[0].name if case.operations else 'rebuild',
               clock='monotonic_elapsed', unit='us', status='running')
    try:
        if config['backend'] == 'mork-petta':
            values, metadata = run_petta(case, config['petta'], config['samples'], config['warmup'],
                                         Path(config['artifacts']))
        else:
            values, metadata = run_python_backend(case, config['backend'], config['samples'], config['warmup'], outfile)
        median, p95 = summarize(values)
        row.update(status='ok', samples_us=values, median_us=median, p95_us=p95,
                   metadata=metadata, correctness='passed')
    except BaseException as exc:
        row.update(status='error', error_type=type(exc).__name__, error=str(exc))
        traceback.print_exc()
    outfile.write_text(json.dumps(row, indent=2) + '\n')
    return 0 if row['status'] == 'ok' else 1



if __name__ == "__main__":
    raise SystemExit(run_trial(sys.argv[1]))
