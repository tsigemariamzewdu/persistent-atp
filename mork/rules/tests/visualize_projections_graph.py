"""Visualize the graph used by the projection tests (test_projections.metta).

Renders the union of:
  - shared fixture:  tests/test_graph.metta
  - projections extras: tests/test_projections.metta

from the actual add-atom stanzas. Highlights exactly what the projection
rules compute so you can cross-check the tests by eye:
  - exact duplicate edges   (same rel/src/dst, different eid)  -> dashed red
  - semantic duplicate claims (same statement on 2 Claims)      -> red border
  - routes-to / predecessors per node (printed summary)

Usage:
    python visualize_projections_graph.py            # save PNG + print summary
    python visualize_projections_graph.py --rev      # overlay rev-edge index
    python visualize_projections_graph.py --show     # open interactive window
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

from visualize_test_graph import EDGE_COLORS, NODE_COLORS

HERE = Path(__file__).resolve().parent
FILES = [HERE / "test_graph.metta", HERE / "test_projections.metta"]

SCOPE_PALETTE = ["#4c72b0", "#dd8452", "#55a868", "#c44e52", "#8172b2"]


def scope_color(scope, used):
    if scope not in used:
        used[scope] = SCOPE_PALETTE[len(used) % len(SCOPE_PALETTE)]
    return used[scope]


def parse_file(path: Path):
    """Return (nodes, fields, edges, rev_edges) atom lists with scope hints."""
    nodes = []      # (scope, id, label)
    fields = []     # (scope, id, name, value)
    edges = []      # (scope, eid, rel, src, dst)
    rev_edges = []  # (scope, eid, rel, src, dst) in forward-normalized order

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        m = re.search(r'\(node\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)', line)
        if m:
            nodes.append(m.groups())
            continue
        m = re.search(
            r'\(field\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)', line)
        if m:
            fields.append(m.groups())
            continue
        m = re.search(
            r'\(rev-edge\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)',
            line,
        )
        if m:
            # rev-edge schema: (rev-edge $p $target $rel $src $eid)
            # -> target is the forward edge's DESTINATION, src is its SOURCE.
            scope, target, rel, src, eid = m.groups()
            rev_edges.append((scope, eid, rel, src, target))
            continue
        m = re.search(
            r'\(edge\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)',
            line,
        )
        if m:
            edges.append(m.groups())

    return nodes, fields, edges, rev_edges


def exact_duplicate_edges(edges):
    """(rel, src, dst) appearing under more than one eid, per scope."""
    groups = {}
    for s, eid, rel, src, dst in edges:
        groups.setdefault((s, rel, src, dst), []).append(eid)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


def semantic_duplicate_claims(nodes, fields):
    """Claim pairs sharing a statement value, per scope."""
    stmts = {}
    for s, nid, name, val in fields:
        if name != "statement":
            continue
        if (s, nid) not in {(sc, id) for sc, id, lab in nodes if lab == "Claim"}:
            continue
        stmts.setdefault((s, val), []).append(nid)
    return {k: sorted(v) for k, v in stmts.items() if len(v) > 1}


def describe(nodes, fields, edges, rev_edges):
    lines = []

    scopes = {}
    for scope, nid, _ in nodes:
        scopes.setdefault(scope, []).append(nid)
    lines.append("=== Nodes by proof scope ===")
    for scope, nids in sorted(scopes.items()):
        lines.append("  %-11s %-3d  %s" % (scope, len(nids), ", ".join(sorted(nids))))
    lines.append("")

    statements = {
        (s, nid): val for s, nid, name, val in fields if name == "statement"}
    lines.append("=== Nodes (id, label, statement) ===")
    for s, nid, label in sorted(nodes, key=lambda n: (n[0], n[1])):
        st = statements.get((s, nid), "")
        lines.append("  [%-11s] %-4s %-8s %s" % (s, nid, label, st))
    lines.append("")

    lines.append("=== Edges (%d) ===" % len(edges))
    for s, eid, rel, src, dst in sorted(edges, key=lambda e: e[1]):
        lines.append("  [%-11s] %-3s %s -%s-> %s" % (s, eid, src, rel, dst))
    lines.append("")

    fwd = {(s, e, rel, src, dst) for s, e, rel, src, dst in edges}
    rev = {(s, e, rel, src, dst) for s, e, rel, src, dst in rev_edges}
    for scope in sorted({s for s, *_ in edges} | {s for s, *_ in rev_edges}):
        fs = {(e, r, a, b) for (s, e, r, a, b) in fwd if s == scope}
        rs = {(e, r, a, b) for (s, e, r, a, b) in rev if s == scope}
        if fs == rs:
            lines.append("  [%s] forward == reverse index (%d edge(s))"
                         % (scope, len(fs)))
        else:
            lines.append("  [%s] MISMATCH missing=%s extra=%s"
                         % (scope, sorted(fs - rs), sorted(rs - fs)))
    lines.append("")

    dup = exact_duplicate_edges(edges)
    lines.append("=== 7.1 exact-duplicate-edges ===")
    if dup:
        for (s, rel, src, dst), eids in sorted(dup.items()):
            lines.append("  [%s] %s -%s-> %s under eids %s"
                         % (s, src, rel, dst, eids))
    else:
        lines.append("  none")
    lines.append("")

    sdup = semantic_duplicate_claims(nodes, fields)
    lines.append("=== 7.2 semantic-duplicate-claims ===")
    if sdup:
        for (s, val), nids in sorted(sdup.items()):
            lines.append("  [%s] claims %s share statement %s" % (s, nids, val))
    else:
        lines.append("  none")
    lines.append("")

    node_ids = {nid for s, nid, _ in nodes}
    lines.append("=== 6.2/6.3 routes-to / predecessors (per node) ===")
    incoming = {}
    for s, eid, rel, src, dst in edges:
        if dst in node_ids:
            incoming.setdefault(dst, []).append((rel, src, eid))
    for nid in sorted(node_ids):
        routes = sorted(incoming.get(nid, []))
        lines.append("  %-4s <- %s" % (nid, routes if routes else "()"))
    lines.append("")

    for s, nid, _ in nodes:
        if not any(ed for ed in edges if ed[0] == s and (ed[3] == nid or ed[4] == nid)):
            lines.append("  isolated node: %s (%s)" % (nid, s))

    return "\n".join(lines)


def build(nodes, edges):
    G = nx.MultiDiGraph()
    for s, nid, label in nodes:
        G.add_node(nid, label=label, scope=s)
    for s, eid, rel, src, dst in edges:
        G.add_edge(src, dst, key=eid, rel=rel, eid=eid, scope=s)
    return G


def render(G, statements, out_path, rev_edges=()):
    pos = {  # manual layout: one small graph, drawn as legibly as possible
        "a1": (-3.0, 1.8),
        "s1": (0.0, 0.0),
        "m1": (3.2, 1.4),
        "c1": (2.6, -1.8),
        "c2": (-3.4, -1.8),
        "c3": (0.8, 3.0),
    }
    fig, ax = plt.subplots(figsize=(12, 8))
    ax.set_xlim(-4.6, 4.6)
    ax.set_ylim(-3.0, 4.2)

    def draw_edge(u, v, color, label_lines, rad, style="-", lw=2.6, zorder=3):
        ax.annotate(
            "", xy=pos[v], xytext=pos[u],
            arrowprops=dict(
                arrowstyle="-|>", mutation_scale=20,
                color=color, lw=lw, ls=style,
                connectionstyle="arc3,rad=%s" % rad,
                shrinkA=34, shrinkB=34,
            ),
            zorder=zorder,
        )
        (x1, y1), (x2, y2) = pos[u], pos[v]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        off = rad * L * 0.6
        tx, ty = mx + (-dy / L) * off, my + (dx / L) * off
        ax.text(
            tx, ty, label_lines, ha="center", va="center", fontsize=9,
            color=color, zorder=5,
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=color, lw=0.8),
        )

    draw_edge("s1", "m1", EDGE_COLORS["PROPOSES"], "PROPOSES\ne1", 0.0)
    draw_edge("s1", "m1", "#d62728", "DUP\ne4", 0.28, style=(0, (4, 2)), lw=2.2)
    draw_edge("s1", "c1", EDGE_COLORS["SUPPORTED_BY"], "SUPPORTED_BY\ne2", 0.0)
    draw_edge("a1", "s1", EDGE_COLORS["ON_STATE"], "ON_STATE\ne3", 0.0)

    for nid, (x, y) in pos.items():
        label = G.nodes[nid]["label"]
        st = statements.get(nid)
        ax.scatter(
            [x], [y], s=1200,
            color=NODE_COLORS.get(label, "#cccccc"),
            edgecolors="#000000", linewidths=1.6, zorder=4,
        )
        body = "%s%s" % (nid, "" if label == "Claim" else " (%s)" % label)
        ax.text(x, y, body, ha="center", va="center",
                fontsize=11, fontweight="bold", zorder=5)

    for nid, st in statements.items():
        x, y = pos.get(nid, (0, 0))
        ax.text(x, y - 0.9, "stmt: \"%s\"" % st, ha="center", va="center",
                fontsize=9, color="#d62728", zorder=5)
    # red ring on claims that share a statement
    same = {}
    for nid, st in statements.items():
        same.setdefault(st, []).append(nid)
    for nid in [n2 for v in same.values() for n2 in v if len(v) > 1]:
        x, y = pos[nid]
        ax.scatter([x], [y], s=1500, facecolors="none",
                   edgecolors="#d62728", linewidths=1.6, zorder=4)

    if rev_edges:
        ax.plot([], [], ls=(0, (4, 2)), color="#999999",
                label="rev-edge (generated index)")

    for scope in sorted({G.nodes[n]["scope"] for n in G.nodes()}):
        ax.plot([], [], marker="o", linestyle="none",
                label="proof scope: %s" % scope)
    ax.plot([], [], ls=(0, (4, 2)), color="#d62728",
            label="exact duplicate edge (both e1, e4)")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)

    ax.set_title("Projections test graph  —  %d nodes, %d edge atoms\n"
                 "(e1 and e4 are duplicates: s1 -PROPOSES-> m1)"
                 % (G.number_of_nodes(), G.number_of_edges()))
    ax.set_aspect("equal")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def main():
    show = "--show" in sys.argv
    show_rev = "--rev" in sys.argv

    nodes, fields, edges, rev_edges = [], [], [], []
    for path in FILES:
        n, f, e, r = parse_file(path)
        nodes += n
        fields += f
        edges += e
        rev_edges += r

    print(describe(nodes, fields, edges, rev_edges))

    statements = {}
    for s, nid, name, val in fields:
        if name == "statement":
            statements.setdefault(nid, val)

    G = build(nodes, edges)
    out_path = HERE / "test_projections_graph.png"
    fig = render(G, statements, out_path, rev_edges if show_rev else ())
    print("\nsaved: %s" % out_path)

    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()