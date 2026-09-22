"""Common canonical graph schema accessed through MORK's Python FFI.

The transport is retained from the original mork-ffi branch. Both MORK access
paths use these same node/field/layer/edge/rev-edge atom shapes.
"""
from __future__ import annotations

from collections import defaultdict
import json
import re
from .ffi_transport import MorkSpace

TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|[()]|[^\s()]+')


def encode(value):
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def parse(text):
    stack, result = [], []
    for token in TOKEN.findall(text):
        if token == '(':
            item = []
            (stack[-1] if stack else result).append(item)
            stack.append(item)
        elif token == ')':
            if not stack:
                raise ValueError('Unbalanced result from MORK')
            stack.pop()
        else:
            if token in ('True', 'true'):
                value = True
            elif token in ('False', 'false'):
                value = False
            elif token in ('None', 'null'):
                value = None
            else:
                try:
                    value = json.loads(token)
                except json.JSONDecodeError:
                    value = token
            (stack[-1] if stack else result).append(value)
    if stack or len(result) != 1:
        raise ValueError(f'Invalid result: {text[:200]}')
    return result[0]


def atom(kind, *values):
    return '(' + kind + ' ' + ' '.join(encode(v) for v in values) + ')'


def graph_atoms(graph):
    for node in graph['nodes']:
        p, i = node['proof'], node['id']
        yield atom('node', p, i, node['label'])
        yield atom('layer', p, i, 'committed')
        for key, value in sorted(node['fields'].items()):
            yield atom('field', p, i, key, value)
    for edge in graph['edges']:
        p, i, rel, src, dst = (edge[k] for k in ('proof', 'id', 'rel', 'src', 'dst'))
        yield atom('edge', p, i, rel, src, dst)
        yield atom('rev-edge', p, dst, rel, src, i)


class MorkBackend:
    def __init__(self):
        self.space = MorkSpace()
        if self.space.atoms():
            raise RuntimeError('FFI process must begin with an empty MORK space')

    def load(self, graph):
        values = list(graph_atoms(graph))
        for start in range(0, len(values), 2000):
            self.space.add(*values[start:start + 2000])

    def matches(self, pattern, template):
        return [parse(value) for value in self.space.match(pattern, template)]

    def clear(self, pattern):
        found = self.space.match(pattern, pattern)
        if found:
            self.space.remove(*found)

    def execute(self, operation):
        name, a = operation.name, operation.args
        p, i = encode(a['proof']), encode(a['id'])
        if name in ('node', 'missing_node'):
            labels = self.matches(f'(node {p} {i} $label)', '$label')
            if not labels:
                return None
            fields = self.matches(f'(field {p} {i} $key $value)', '($key $value)')
            return [a['id'], labels[0], sorted(fields)]
        if name in ('incoming', 'outgoing'):
            rel = encode(a['rel'])
            if name == 'incoming':
                return self.matches(f'(rev-edge {p} {i} {rel} $src $eid)', f'($eid {rel} $src {i})')
            return self.matches(f'(edge {p} $eid {rel} {i} $dst)', f'($eid {rel} {i} $dst)')
        if name == 'create_node':
            self.space.add(atom('node', a['proof'], a['id'], a['label']),
                           atom('layer', a['proof'], a['id'], 'committed'),
                           *(atom('field', a['proof'], a['id'], k, v) for k, v in sorted(a['fields'].items())))
        elif name in ('insert_field', 'overwrite_field'):
            if name == 'overwrite_field':
                self.clear(f'(field {p} {i} {encode(a["field"])} $v)')
            self.space.add(atom('field', a['proof'], a['id'], a['field'], a['value']))
        elif name == 'add_edge':
            self.space.add(atom('edge', a['proof'], a['id'], a['rel'], a['src'], a['dst']),
                           atom('rev-edge', a['proof'], a['dst'], a['rel'], a['src'], a['id']))
        elif name == 'remove_edge':
            edges = self.matches(f'(edge {p} {i} $rel $src $dst)', '($rel $src $dst)')
            for rel, src, dst in edges:
                self.space.remove(atom('edge', a['proof'], a['id'], rel, src, dst),
                                  atom('rev-edge', a['proof'], dst, rel, src, a['id']))
        elif name == 'delete_node':
            self.clear(f'(field {p} {i} $k $v)')
            self.clear(f'(layer {p} {i} $v)')
            self.clear(f'(node {p} {i} $v)')
        elif name == 'delete_field':
            self.clear(f'(field {p} {i} {encode(a["field"])} $v)')
        elif name == 'frontier':
            status = self.matches(f'(field {p} {i} "status" $s)', '$s')
            if status and status[0] in ('tainted', 'formally-closed'):
                return []
            return self._frontier(p, i)
        elif name == 'taint':
            status = self.matches(f'(field {p} {i} "status" $s)', '$s')
            if status != ['refuted']:
                return []
            claims = set(self.matches(f'(node {p} $id "Claim")', '$id'))
            committed = set(self.matches(f'(layer {p} $id "committed")', '$id'))
            reverse = defaultdict(list)
            for src, dst in self.matches(f'(edge {p} $e "DEPENDS_ON" $src $dst)', '($src $dst)'):
                if src in claims and src in committed:
                    reverse[dst].append(src)
            found, pending = {a['id']}, [a['id']]
            while pending:
                for dependent in reverse[pending.pop()]:
                    if dependent not in found:
                        found.add(dependent)
                        pending.append(dependent)
            found.remove(a['id'])
            return list(found)
        else:
            raise ValueError(f'Unknown operation: {name}')
        return True

    def _frontier(self, proof, state):
        moves = set(self.matches(f'(node {proof} $m "Move")', '$m'))
        committed = set(self.matches(f'(layer {proof} $m "committed")', '$m'))
        statuses = dict(self.matches(f'(field {proof} $m "status" $s)', '($m $s)'))
        proposed = self.matches(f'(edge {proof} $e "PROPOSES" {state} $m)', '$m')
        return list(dict.fromkeys(move for move in proposed if move in moves and move in committed
                                 and statuses.get(move) in ('open', 'reopened')))

    def snapshot(self):
        nodes, fields, edges = [], defaultdict(dict), []
        for p, i, key, value in self.matches('(field $p $i $k $v)', '($p $i $k $v)'):
            fields[p, i][key] = value
        for p, i, label in self.matches('(node $p $i $label)', '($p $i $label)'):
            nodes.append({'proof': p, 'id': i, 'label': label, 'fields': fields[p, i]})
        for p, i, rel, src, dst in self.matches('(edge $p $i $r $s $d)', '($p $i $r $s $d)'):
            edges.append(dict(proof=p, id=i, rel=rel, src=src, dst=dst))
        return {'nodes': sorted(nodes, key=lambda n: (n['proof'], n['id'])),
                'edges': sorted(edges, key=lambda e: (e['proof'], e['id']))}

    def close(self):
        pass  # The fresh worker process owns the process-global MORK space.
