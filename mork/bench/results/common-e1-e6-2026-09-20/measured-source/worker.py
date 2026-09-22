"""One isolated backend/case/trial. Called by the common E1--E6 driver."""
from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

from .spec import Case, Operation, Oracle, canonical_graph, expected_result, inverse_operations, normalize_result, MUTATIONS
from .mork_backend import graph_atoms, parse, MorkBackend
from .harness import summarize


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


def mutation_check(operation, graph):
    a = operation.args
    if operation.name in ('create_node', 'insert_field', 'overwrite_field'):
        return Operation('node', {'proof': a['proof'], 'id': a['id']})
    if operation.name in ('add_edge', 'remove_edge'):
        edge = a if operation.name == 'add_edge' else next(e for e in graph['edges']
            if e['proof'] == a['proof'] and e['id'] == a['id'])
        return Operation('outgoing', {'proof': a['proof'], 'id': edge['src'], 'rel': edge['rel']})
    return None


def run_python_backend(case, backend_name, samples, warmup, outfile):
    if backend_name == 'mork-ffi':
        backend = MorkBackend()
        metadata = {'library': os.environ.get('MORK_LIBRARY'), 'process_isolated': True}
    else:
        from .neo4j_backend import Neo4jBackend
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
    from .petta_common import make_program
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


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
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


if __name__ == '__main__':
    raise SystemExit(main())
