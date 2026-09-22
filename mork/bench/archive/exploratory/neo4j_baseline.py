"""Neo4j adapter queries over uniquely scoped benchmark graphs.

Fixture writes and cleanup use BOTH exact proof IDs and a per-case ownership tag.
No production data is reset. The adapter installs its usual constraints/indexes.
"""
from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from .dict_baseline import DictGraph
from .experiments import Case

SUPPORTED = ('E1', 'E2', 'E4', 'Q1', 'Q2')


class Neo4jFixture:
    def __init__(self, adapter, commands: list[str]):
        self.adapter = adapter
        self.token = uuid4().hex
        graph = DictGraph(commands)
        self.proofs = {proof: f'bench-{self.token}-{proof}' for proof, _ in graph.nodes}
        self.proofs.setdefault('target', f'bench-{self.token}-target')
        self.target = self.proofs['target']
        self.node_count = len(graph.nodes)
        self.edge_count = sum(len(edges) for edges in graph.outgoing.values())
        self.nodes = defaultdict(list)
        self.edges = defaultdict(list)
        for (proof, entity), label in graph.nodes.items():
            if label not in ('State', 'Move', 'Claim'):
                raise ValueError(f'Unsupported benchmark label: {label}')
            self.nodes[label].append({
                'proof_id': self.proofs[proof], 'id': entity,
                'status': graph.fields[proof, entity, 'status'],
                'layer': graph.layers[proof, entity], 'benchmark_run': self.token,
            })
        for (proof, source), edges in graph.outgoing.items():
            for relation, destination, edge in edges:
                if relation not in ('PROPOSES', 'DEPENDS_ON'):
                    raise ValueError(f'Unsupported benchmark relationship: {relation}')
                self.edges[relation].append({'pid': self.proofs[proof], 'src': source,
                                            'dst': destination, 'id': edge})

    def load(self):
        statements = []
        # Fixed label/type allowlists above make these interpolations safe.
        for label, rows in self.nodes.items():
            statements.append((f'UNWIND $rows AS row CREATE (n:{label}) SET n = row', {'rows': rows}))
        for relation, rows in self.edges.items():
            source_label, destination_label = ('State', 'Move') if relation == 'PROPOSES' else ('Claim', 'Claim')
            statements.append((
                f'UNWIND $rows AS row MATCH (s:{source_label} {{proof_id: row.pid, id: row.src}}), '
                f'(d:{destination_label} {{proof_id: row.pid, id: row.dst}}) '
                'WHERE s.benchmark_run = $token AND d.benchmark_run = $token '
                f'CREATE (s)-[:{relation} {{edge_id: row.id, benchmark_run: $token}}]->(d)',
                {'rows': rows, 'token': self.token}))
        if statements:
            self.adapter._write_all('benchmark_load', statements)
        self.check_counts()

    def counts(self):
        params = {'pids': list(self.proofs.values()), 'token': self.token}
        nodes = self.adapter._read_value('benchmark_count_nodes',
            'MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run = $token RETURN count(n) AS n', params, 'n')
        edges = self.adapter._read_value('benchmark_count_edges',
            'MATCH (s)-[r]->(d) WHERE s.proof_id IN $pids AND d.proof_id IN $pids '
            'AND s.benchmark_run = $token AND d.benchmark_run = $token '
            'AND r.benchmark_run = $token RETURN count(r) AS n', params, 'n')
        return nodes, edges

    def check_counts(self):
        actual = self.counts()
        if actual != (self.node_count, self.edge_count):
            raise RuntimeError(f'Neo4j fixture count mismatch: {actual}')

    def cleanup(self):
        self.adapter._write_all('benchmark_cleanup', [(
            'MATCH (n) WHERE n.proof_id IN $pids AND n.benchmark_run = $token DETACH DELETE n',
            {'pids': list(self.proofs.values()), 'token': self.token})])
        if self.counts() != (0, 0):
            raise RuntimeError(f'Benchmark cleanup incomplete for token {self.token}')

    def probes(self, case: Case):
        pid = self.target
        def query(operation, cypher, **params):
            return self.adapter._read_value(operation, cypher, {'pid': pid, **params}, 'values', default=[])
        return {
            'node': (lambda: query('benchmark_node',
                'MATCH (m:Move {proof_id: $pid, id: "n1"}) RETURN collect("Move") AS values'), ['Move']),
            'incoming-edges': (lambda: query('benchmark_incoming',
                'MATCH (s)-[r:PROPOSES]->(d:Move {proof_id: $pid, id: "n1"}) '
                'WHERE s.proof_id = $pid RETURN collect([type(r), s.id, r.edge_id]) AS values'),
                [['PROPOSES', 'n0', 'e1']]),
            'outgoing-edges': (lambda: query('benchmark_outgoing',
                'MATCH (s:Move {proof_id: $pid, id: "n1"})-[r:PROPOSES]->(d) '
                'WHERE d.proof_id = $pid RETURN collect([type(r), d.id, r.edge_id]) AS values'), []),
            'empty-match': (lambda: query('benchmark_empty',
                'MATCH (n:Move {proof_id: $pid, id: "bench-absent"}) RETURN collect(n.id) AS values'), []),
            # Public production adapter methods: include result transfer/conversion.
            'frontier-for-state': (lambda: len(self.adapter.eligible_frontier(pid)), case.nodes - 1),
            'taint-cone': (lambda: len(self.adapter.taint_cone(pid, 'n0')), case.nodes - 1),
        }

    def check_rule_results(self, case: Case):
        expected = {f'n{i}' for i in range(1, case.nodes)}
        if case.experiment == 'Q1':
            actual = {row['id'] for row in self.adapter.eligible_frontier(self.target)}
            if actual != expected:
                raise RuntimeError('Neo4j frontier returned incorrect IDs')
        elif case.experiment == 'Q2':
            if set(self.adapter.taint_cone(self.target, 'n0')) != expected:
                raise RuntimeError('Neo4j taint cone returned incorrect IDs')
