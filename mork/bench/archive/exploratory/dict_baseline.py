"""Indexed Python-dict baseline over the exact projected atoms used by PeTTa.

This is a purpose-built graph baseline, not a general MeTTa interpreter or the
commit gate's MemoryView. Both incoming and outgoing adjacency are indexed.
"""
from __future__ import annotations

from collections import defaultdict
import json
import re
import time
from typing import Callable

from .experiments import Case
from .harness import Row, summarize

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[^\s()]+')


class DictGraph:
    def __init__(self, commands: list[str]):
        self.atoms: dict[tuple, None] = {}
        self.nodes: dict[tuple[str, str], str] = {}
        self.fields: dict[tuple[str, str, str], object] = {}
        self.layers: dict[tuple[str, str], str] = {}
        self.by_label: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.incoming: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        self.outgoing: dict[tuple[str, str], list[tuple]] = defaultdict(list)
        self.relations: dict[str, dict[tuple, None]] = defaultdict(dict)
        for command in commands:
            tokens = TOKEN.findall(command)
            if tokens[:2] != ['!', 'add-atom'] or tokens[2] != '&mork':
                raise ValueError(f'Unsupported projection: {command}')
            atom = tuple(json.loads(t) if t.startswith('"') else t for t in tokens[3:])
            if atom in self.atoms:
                raise ValueError('Duplicate atom in benchmark workload')
            self.atoms[atom] = None
            self.relations[atom[0]][atom] = None
            kind, proof, entity, *rest = atom
            if kind == 'node':
                self.nodes[proof, entity] = rest[0]
                self.by_label[proof, rest[0]].append(entity)
            elif kind == 'field':
                self.fields[proof, entity, rest[0]] = rest[1]
            elif kind == 'layer':
                self.layers[proof, entity] = rest[0]
            elif kind == 'edge':
                relation, source, destination = rest
                self.outgoing[proof, source].append((relation, destination, entity))
            elif kind == 'rev-edge':
                relation, source, edge = rest
                self.incoming[proof, entity].append((relation, source, edge))

    def node(self, proof: str, node: str) -> list:
        value = self.nodes.get((proof, node))
        return [] if value is None else [value]

    def edges_to(self, proof: str, node: str) -> list:
        return list(self.incoming.get((proof, node), ()))

    def edges_from(self, proof: str, node: str) -> list:
        return list(self.outgoing.get((proof, node), ()))

    def frontier(self, proof: str, state: str) -> list[str]:
        result = []
        for relation, move, _ in self.outgoing.get((proof, state), ()):
            if (relation == 'PROPOSES' and self.nodes.get((proof, move)) == 'Move'
                    and self.layers.get((proof, move)) == 'committed'
                    and self.fields.get((proof, move, 'status')) in ('open', 'reopened')
                    and self.fields.get((proof, state, 'status')) not in ('tainted', 'formally-closed')):
                result.append(move)
        return result

    def reaches(self, proof: str, source: str, root: str) -> bool:
        # General reachability, not a star-specific shortcut or precomputed result.
        pending, visited = [source], set()
        while pending:
            current = pending.pop()
            if current == root:
                return True
            if current in visited or self.layers.get((proof, current)) != 'committed':
                continue
            visited.add(current)
            pending.extend(dst for rel, dst, _ in self.outgoing.get((proof, current), ())
                           if rel == 'DEPENDS_ON')
        return False

    def taint_cone(self, proof: str, root: str) -> list[str]:
        if self.fields.get((proof, root, 'status')) != 'refuted':
            return []
        return [claim for claim in self.by_label.get((proof, 'Claim'), ())
                if claim != root and self.layers.get((proof, claim)) == 'committed'
                and self.reaches(proof, claim, root)]

    def add_remove_cycle(self) -> tuple[int, int]:
        atom = ('bench-temp', 'unique')
        self.atoms[atom] = None
        self.relations['bench-temp'][atom] = None
        before = len(list(self.relations['bench-temp']))
        del self.atoms[atom]
        del self.relations['bench-temp'][atom]
        after = len(list(self.relations['bench-temp']))
        return before, after

    def empty_match(self) -> list:
        return list(self.relations.get('bench-absent', {}))


def probes(graph: DictGraph, case: Case) -> dict[str, tuple[Callable, object]]:
    return {
        'node': (lambda: graph.node('target', 'n1'), ['Move']),
        'incoming-edges': (lambda: graph.edges_to('target', 'n1'), [('PROPOSES', 'n0', 'e1')]),
        'outgoing-edges': (lambda: graph.edges_from('target', 'n1'), []),
        'add-remove-cycle': (graph.add_remove_cycle, (1, 0)),
        'empty-match': (graph.empty_match, []),
        'frontier-for-state': (lambda: len(graph.frontier('target', 'n0')), case.nodes - 1),
        'taint-cone': (lambda: len(graph.taint_cone('target', 'n0')), case.nodes - 1),
    }


def measure_case(case: Case, commands: list[str], iterations: int, warmup: int) -> list[Row]:
    if not case.probes:  # Loading a MeTTa program has no equivalent dictionary operation.
        return []
    graph = DictGraph(commands)
    before = dict(graph.atoms)
    available = probes(graph, case)
    rows = []
    for probe in case.probes:
        call, expected = available[probe.name]
        if call() != expected:
            raise RuntimeError(f'Dictionary correctness check failed: {case.stem}/{probe.name}')
        for _ in range(warmup):
            call()
        samples = []
        for _ in range(iterations):
            start = time.thread_time_ns()
            result = call()
            elapsed = (time.thread_time_ns() - start) / 1000
            if result != expected:
                raise RuntimeError(f'Dictionary result changed: {case.stem}/{probe.name}')
            samples.append(elapsed)
        if graph.atoms != before:
            raise RuntimeError(f'Dictionary atom state changed: {case.stem}/{probe.name}')
        median, p95 = summarize(samples)
        rows.append(Row(case.experiment, probe.name, case.scale, len(graph.atoms), median, p95,
                        iterations, 'python-dict', clock='python_thread_cpu',
                        note='indexed dict; same projected atoms and result semantics; construction excluded'))
    return rows


def comparison_markdown(rows: list[Row]) -> str:
    dictionary = {(r.experiment, r.operation, r.scale): r for r in rows if r.runtime == 'python-dict'}
    lines = ['# PeTTa vs indexed Python dictionaries', '',
             'Ratio = PeTTa median / Python-dict median. Above 1 means PeTTa took more CPU time.', '',
             '| Experiment | Operation | Scale | Atoms | Runtime | PeTTa median µs | Dict median µs | Ratio | PeTTa p95 µs | Dict p95 µs |',
             '| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |']
    for row in rows:
        if not row.runtime.startswith('petta-'):
            continue
        baseline = dictionary.get((row.experiment, row.operation, row.scale))
        if baseline is None:
            continue
        if row.atoms != baseline.atoms or row.iterations != baseline.iterations:
            raise ValueError('Comparison rows have mismatched workload or sample count')
        ratio = f'{row.median / baseline.median:.2f}×' if baseline.median else 'undefined'
        lines.append(f'| {row.experiment} | {row.operation} | {row.scale} | {row.atoms} | '
                     f'{row.runtime} | {row.median:.3f} | {baseline.median:.3f} | {ratio} | '
                     f'{row.p95:.3f} | {baseline.p95:.3f} |')
    lines.extend(['', '## Interpretation and limits', '',
        '- `petta-space` is ordinary PeTTa, not MORK. A MORK slowdown cannot be inferred from those rows.',
        '- Both sides use the exact same projected atoms, materialize query results, and check expected results. Graph construction is outside query timing.',
        '- PeTTa uses executing-thread CPU time; Python uses `thread_time_ns`. Each side has identical warm-up/sample counts. Individual calls are timed, so timer and language-call overhead remain, especially for sub-microsecond dictionary operations.',
        '- Python is a purpose-built graph implementation with hash indexes for nodes, fields, labels, layers, and both adjacency directions. PeTTa executes the existing MeTTa rules. These ratios compare complete implementations, not isolated storage engines or equal index layouts.',
        '- Frontier and taint queries materialize lists before counting. Python reachability is an iterative search; it is not a general MeTTa evaluator. Equivalence is checked on these acyclic benchmark workloads, not all possible graphs.',
        '- L1 has no paired ratio: parsing/executing a MeTTa file is not equivalent to constructing dictionaries. Python projection is already measured separately.',
        '- This does not compare memory use, persistence, live commits, crash recovery, general unification, or concurrent workloads. No single overall slowdown is meaningful across these operations.',
        '- One sweep, with PeTTa followed by Python per case. Repeat independent sweeps for stable estimates; p95 from a small sample is noisy.', ''])
    return '\n'.join(lines)
