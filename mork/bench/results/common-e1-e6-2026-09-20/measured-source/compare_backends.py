"""Compare PeTTa, indexed Python dicts, and the live Neo4j adapter in elapsed time.

Run from the repository root:
PYTHONPATH=src:. python -m mork.bench.compare_backends --help.
Neo4j credentials come from the existing adapter environment/.env configuration.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import re
import sys
import time

from .dict_baseline import DictGraph, probes as dict_probes
from .experiments import cases
from .harness import Row, detect_runtime, parse_rows, program, run_petta, summarize
from .neo4j_baseline import Neo4jFixture, SUPPORTED
from .workload import commands


def measure(call, expected, iterations, warmup, batch_size):
    if call() != expected:
        raise RuntimeError('Backend returned an unexpected query result')
    for _ in range(warmup):
        for _ in range(batch_size):
            call()
    samples = []
    for _ in range(iterations):
        start = time.monotonic_ns()
        for _ in range(batch_size):
            result = call()
        elapsed = (time.monotonic_ns() - start) / 1000 / batch_size
        if result != expected:
            raise RuntimeError('Backend query result changed during measurement')
        samples.append(elapsed)
    return samples


def render(rows):
    index = {(r['experiment'], r['operation'], r['scale'], r['runtime']): r for r in rows}
    output = ['# PeTTa / Python dict / Neo4j elapsed-time comparison', '',
        'Median microseconds per call, from batches. Neo4j includes client sessions, managed transactions, Bolt transport, server execution, and result conversion. PeTTa runs inside its persistent child process; process startup/loading are excluded.', '',
        '| Experiment | Operation | Scale | PeTTa runtime | PeTTa µs | Dict µs | Neo4j µs | Neo4j / PeTTa | Neo4j / dict |',
        '| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:
        if not r['runtime'].startswith('petta-'):
            continue
        key = r['experiment'], r['operation'], r['scale']
        d, n = index[(*key, 'python-dict')], index[(*key, 'neo4j-adapter')]
        output.append(f'| {r["experiment"]} | {r["operation"]} | {r["scale"]} | {r["runtime"]} | '
                      f'{r["median"]:.3f} | {d["median"]:.3f} | {n["median"]:.3f} | '
                      f'{n["median"]/r["median"]:.2f}× | {n["median"]/d["median"]:.2f}× |')
    output.extend(['',
        'Ratios above 1 mean Neo4j took longer; below 1 mean Neo4j was faster. `petta-space` does not measure MORK. All clocks in this report are monotonic elapsed time; do not divide these numbers by the older CPU-time results.', '',
        'PeTTa reads a monotonic clock through its Python bridge, twice per batch. The loop/bridge/timer overhead is retained and amortized across the batch. Reported p95 values in JSON are percentiles of batch means, not individual-request p95.', '',
        'Q1 uses the public Neo4jAdapter.eligible_frontier() (proof-wide, sorted full move records); Q2 uses Neo4jAdapter.taint_cone() (IDs). Both match the one-state/refuted-root fixtures, but differ from MeTTa for arbitrary inputs: MeTTa Q1 is state-specific, and MeTTa Q2 checks the root status. Exact fixture result IDs are checked before timing.', '',
        'Node/edge/empty lookups use equivalent Cypher through the adapter transaction layer because the public adapter has no matching generic Move/edge read API. E4 is an absent node ID in Neo4j, versus an absent atom relation in PeTTa/dict; treat it as an empty-result-path comparison, not identical predicates.', '',
        'Neo4j stores equivalent logical nodes/relationships using its native property graph and normal schema indexes. Fixture loading is bulk Cypher outside timing. `atoms` in JSON is the common projected-input atom count, not the count of physical Neo4j records; physical fixture node/relationship counts are also saved.', '',
        'Each Neo4j case uses unique proof IDs plus an ownership tag, then verifies cleanup. Other database contents remain present and may affect performance. Repeated queries are warm-cache measurements. No isolated-server CPU or memory comparison is made.', '',
        'E3 (atom add/remove/check cycle) and L1 (MeTTa parsing/loading) are omitted because the adapter has no equivalent operation with the same transactional/serialization boundary. Live commit, durability, recovery, generic rule evaluation, and concurrent load are not compared.', ''])
    return '\n'.join(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--petta', default='petta')
    parser.add_argument('--allow-petta-space', action='store_true')
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--experiment', choices=SUPPORTED, action='append')
    parser.add_argument('--iterations', type=int, default=30)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--batch-size', type=int, default=20)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args(argv)
    if min(args.iterations, args.batch_size) < 1 or args.warmup < 0 or args.timeout <= 0:
        parser.error('iterations, batch-size and timeout must be positive; warmup nonnegative')
    root = args.output_dir.resolve()
    generated = root / 'generated'
    generated.mkdir(parents=True, exist_ok=True)
    rows = []
    samples_by_case = {}
    metadata = {'started_at': datetime.now(timezone.utc).isoformat(),
                'python': platform.python_version(), 'platform': platform.platform(),
                'logical_cpus': os.cpu_count(), 'arguments': sys.argv[1:],
                'iterations': args.iterations, 'warmup_batches': args.warmup,
                'batch_size': args.batch_size, 'quick': args.quick,
                'source_sha256': {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(Path('mork/bench').glob('*.py'))},
                'status': 'running'}
    (root / '.gitignore').write_text('generated/\n')
    adapter = None
    try:
        preflight = generated / 'preflight.metta'
        preflight.write_text('!(println! (BENCH_INIT (mm2-exec &mork 1)))\n')
        runtime = detect_runtime(run_petta([args.petta], preflight, args.timeout), args.allow_petta_space)
        metadata['petta_runtime'] = runtime
        from neo4j_adapter.adapter import Neo4jAdapter
        adapter = Neo4jAdapter()
        metadata['neo4j_server'] = adapter._read('benchmark_server_info', lambda tx: [dict(r) for r in
            tx.run('CALL dbms.components() YIELD name, versions, edition RETURN name, versions, edition')])
        metadata['database_nodes_before'] = adapter._read_value('benchmark_existing_count',
            'MATCH (n) RETURN count(n) AS n', {}, 'n')
        print(f'Runtime: {runtime}; Neo4j connected. Batch size: {args.batch_size}', flush=True)
        for name in dict.fromkeys(args.experiment or SUPPORTED):
            for case in cases(name, args.quick):
                print(f'{case.stem}: PeTTa, dict, Neo4j', flush=True)
                data = commands(case.nodes, case.background, claims=case.claims)
                path = generated / f'{case.stem}_data.metta'
                path.write_text('\n'.join(data) + '\n')
                script = generated / f'{case.stem}.metta'
                script.write_text(program(case, path, len(data), args.iterations, args.warmup,
                                          wall_clock=True, batch_size=args.batch_size))
                output = run_petta([args.petta], script, args.timeout)
                if detect_runtime(output, args.allow_petta_space) != runtime:
                    raise RuntimeError('PeTTa runtime changed')
                petta_rows = parse_rows(output, case, len(data), args.iterations, runtime)
                for index, value in re.findall(r'^\(BENCH_SAMPLE (\d+) ([^ ()]+)\)$', output, re.MULTILINE):
                    operation = case.probes[int(index)].name
                    samples_by_case.setdefault(f'{case.stem}/{operation}/{runtime}', []).append(float(value))
                graph = DictGraph(data)
                dictionary = dict_probes(graph, case)
                fixture = Neo4jFixture(adapter, data)
                metadata['active_fixture'] = {'token': fixture.token, 'proof_ids': list(fixture.proofs.values())}
                (root / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
                try:
                    fixture.load()
                    fixture.check_rule_results(case)
                    neo = fixture.probes(case)
                    for petta_row in petta_rows:
                        common = {'batch_size': args.batch_size, 'logical_nodes': fixture.node_count,
                                  'logical_edges': fixture.edge_count, 'sample_kind': 'batch_mean_per_call'}
                        rows.append({**asdict(replace(petta_row, clock='monotonic_wall',
                            note='inside PeTTa; Python monotonic clock bridge; startup/loading excluded')), **common})
                        for backend, functions in [('python-dict', dictionary), ('neo4j-adapter', neo)]:
                            call, expected = functions[petta_row.operation]
                            samples = measure(call, expected, args.iterations, args.warmup, args.batch_size)
                            samples_by_case[f'{case.stem}/{petta_row.operation}/{backend}'] = samples
                            median, p95 = summarize(samples)
                            row = Row(name, petta_row.operation, case.scale, len(data), median, p95,
                                      args.iterations, backend, clock='monotonic_wall',
                                      note='construction excluded; adapter includes transaction/transport overhead')
                            rows.append({**asdict(row), **common})
                    if len(graph.atoms) != len(data):
                        raise RuntimeError('Dictionary atom count changed')
                    fixture.check_counts()
                    fixture.check_rule_results(case)
                finally:
                    fixture.cleanup()
                    metadata.pop('active_fixture', None)
                (root / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
        metadata['database_nodes_after'] = adapter._read_value('benchmark_final_count',
            'MATCH (n) RETURN count(n) AS n', {}, 'n')
        metadata['status'] = 'complete'
        (root / 'comparison.md').write_text(render(rows))
        print(f'Completed {len(rows)} rows; all benchmark fixtures cleaned up.', flush=True)
    except Exception as exc:
        metadata['status'] = 'failed'
        metadata['error_type'] = type(exc).__name__
        print(f'Comparison failed ({type(exc).__name__}): {exc}', flush=True)
        return 1
    finally:
        metadata['finished_at'] = datetime.now(timezone.utc).isoformat()
        (root / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (root / 'samples.json').write_text(json.dumps(samples_by_case, indent=2) + '\n')
        if adapter:
            adapter.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
