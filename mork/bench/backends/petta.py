"""Generate real MeTTa workloads over the shared MORK atom schema."""
from __future__ import annotations

import json
from pathlib import Path
from .mork_ffi import atom, encode, graph_atoms

RULES = Path(__file__).resolve().parents[2] / 'rules'
READS = {'node', 'missing_node', 'incoming', 'outgoing', 'frontier', 'taint'}


def sequence(expressions):
    expressions = [*expressions, '(mork-flush &mork)']
    return '(let* (' + ' '.join(f'($step{i} {expr})' for i, expr in enumerate(expressions)) + ') True)'


def clear(pattern):
    return f'(collapse (match &mork {pattern} (remove-atom &mork {pattern})))'


def operation_expr(operation):
    name, a = operation.name, operation.args
    p, i = encode(a['proof']), encode(a['id'])
    if name in ('node', 'missing_node'):
        return f'(bench-node {p} {i})'
    if name in ('incoming', 'outgoing'):
        rel = encode(a['rel'])
        if name == 'incoming':
            return f'(collapse (match &mork (rev-edge {p} {i} {rel} $src $eid) ($eid {rel} $src {i})))'
        return f'(collapse (match &mork (edge {p} $eid {rel} {i} $dst) ($eid {rel} {i} $dst)))'
    if name == 'frontier':
        return f'(unique-atom (frontier-for-state {p} {i}))'
    if name == 'taint':
        return f'(unique-atom (taint-cone {p} {i}))'
    if name == 'create_node':
        return sequence(f'(add-atom &mork {value})' for value in graph_atoms({'nodes': [
            {'proof': a['proof'], 'id': a['id'], 'label': a['label'], 'fields': a['fields']}], 'edges': []}))
    if name in ('insert_field', 'overwrite_field'):
        expressions = []
        if name == 'overwrite_field':
            expressions.append(clear(f'(field {p} {i} {encode(a["field"])} $v)'))
        expressions.append(f'(add-atom &mork {atom("field", a["proof"], a["id"], a["field"], a["value"])})')
        return sequence(expressions)
    if name == 'add_edge':
        return sequence(f'(add-atom &mork {value})' for value in graph_atoms({'nodes': [], 'edges': [a]}))
    if name == 'remove_edge':
        # Removal must also maintain the common reverse index.
        return sequence([f'(collapse (match &mork (edge {p} {i} $rel $src $dst) '
            f'(let* (($forward (remove-atom &mork (edge {p} {i} $rel $src $dst))) '
            f'($reverse (remove-atom &mork (rev-edge {p} $dst $rel $src {i})))) True)))'])
    if name == 'delete_field':
        return sequence([clear(f'(field {p} {i} {encode(a["field"])} $v)')])
    if name == 'delete_node':
        return sequence([clear(f'(field {p} {i} $k $v)'), clear(f'(layer {p} {i} $v)'), clear(f'(node {p} {i} $v)')])
    raise ValueError(name)


NODE = '''(= (bench-node $p $id)
  (let $labels (collapse (match &mork (node $p $id $label) $label))
    (if (== $labels ()) None
      ($id (car-atom $labels) (sort (collapse (match &mork (field $p $id $k $v) ($k $v))))))))'''


def make_program(case, directory, samples, warmup, inverse_ops):
    directory = Path(directory)
    data = directory / f'{case.key}-data.metta'
    if case.experiment != 'E6':
        data.write_text('\n'.join(f'!(add-atom &mork {a})' for a in graph_atoms(case.graph)) + '\n')
    lines = ['!(println! (PTPS_INIT (mork-flush &mork)))', NODE]
    for module in ('frontier', 'dependency-taint'):
        lines.append(f'!(import! &self {encode(str(RULES / module))})')
    if case.experiment == 'E6':
        from ..experiments import Operation
        expressions = [operation_expr(Operation(op['name'], op['args'])) for op in case.journal]
        journal_path = directory / f'{case.key}-journal.metta'
        journal_path.write_text('\n'.join('!' + e for e in expressions) + '\n')
        expression = f'(import! &self {encode(str(journal_path))})'
        lines.append(timed(expression, 0))
    else:
        lines.append(f'!(import! &self {encode(str(data))})')
        lines.append('!(mork-flush &mork)')
        op = case.operations[0]
        expression = operation_expr(op)
        inverse = [operation_expr(inv) for inv in inverse_ops]
        # Return preflight results for exact correctness checks outside the timer.
        lines.append(f'!(println! (PTPS_RESULT {expression}))')
        check = None
        if inverse:
            from ..experiments import mutation_check
            check = operation_expr(mutation_check(op, case.graph))
            lines.append('!(println! (PTPS_MUTATED (collapse (get-atoms &mork))))')
        lines.extend('!' + inv for inv in inverse)
        if check:
            lines.append(f'!(println! (PTPS_RESTORED {check}))')
        for _ in range(warmup):
            lines.append('!' + expression)
            lines.extend('!' + inv for inv in inverse)
            if check:
                lines.append(f'!(println! (PTPS_RESTORED {check}))')
        for index in range(samples):
            lines.append(timed(expression, index))
            if check:
                lines.append(f'!(println! (PTPS_CHECK {check}))')
            lines.extend('!' + inv for inv in inverse)
            if check:
                lines.append(f'!(println! (PTPS_RESTORED {check}))')
    # Snapshot all atoms to validate the complete final graph AND its reverse indexes.
    lines.extend(['!(println! (PTPS_ATOMS (collapse (get-atoms &mork))))',
                  '!(println! PTPS_DONE)'])
    return '\n'.join(lines) + '\n'


def timed(expression, index):
    return ('!(let* (($begin (py-call ("time.monotonic_ns"))) '
            f'($result {expression}) ($end (py-call ("time.monotonic_ns")))) '
            f'(println! (PTPS_SAMPLE {index} (/ (- $end $begin) 1000) $result)))')
