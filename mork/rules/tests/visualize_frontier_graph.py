"""Visualize the graph used by the frontier tests (test_frontier.metta).

Renders the union of the shared fixture (tests/test_graph.metta) and the
frontier extras (tests/test_frontier.metta) from the actual add-atom
stanzas, so it reflects exactly what is declared. Proof scopes are
detected from the atoms and color-coded on node borders.

Usage:
    python visualize_frontier_graph.py            # save PNG + print summary
    python visualize_frontier_graph.py --rev      # overlay rev-edge index
    python visualize_frontier_graph.py --show     # open interactive window
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

from visualize_test_graph import EDGE_COLORS, NODE_COLORS

HERE = Path(__file__).resolve().parent
FILES = [HERE / "test_graph.metta", HERE / "test_frontier.metta"]

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
    rev_edges = []  # (scope, eid, rel, src, dst) normalized to forward form

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


def describe(nodes, fields, edges, rev_edges):
    lines = []

    scopes = {}
    for scope, nid, _ in nodes:
        scopes.setdefault(scope, []).append(nid)
    lines.append("=== Nodes by proof scope ===")
    for scope, nids in sorted(scopes.items()):
        lines.append("  %-11s %-3d  %s" % (scope, len(nids), ", ".join(sorted(nids))))
    lines.append("")

    lines.append("=== Nodes (id, label, status) ===")
    by_id = {(s, nid): label for s, nid, label in nodes}
    status = {(s, nid): val for s, nid, name, val in fields if name == "status"}
    for (s, nid), label in sorted(by_id.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        st = status.get((s, nid), "")
        lines.append("  [%-11s] %-4s %-8s %s" % (s, nid, label, st))
    lines.append("")

    lines.append("=== Edges (%d) ===" % len(edges))
    for s, eid, rel, src, dst in sorted(edges, key=lambda e: e[1]):
        lines.append("  [%-11s] %-3s %s -%s-> %s" % (s, eid, src, rel, dst))
    lines.append("")

    # Reverse index consistency, per scope.
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

    # Dangling references: edge endpoints with no node atom in that scope.
    node_scopes = {(s, nid) for s, nid, _ in nodes}
    lines.append("=== Cross-scope / dangling endpoint check ===")
    for s, eid, rel, src, dst in sorted(edges, key=lambda e: e[1]):
        for end, kind in ((src, "src"), (dst, "dst")):
            if (s, end) not in node_scopes:
                lines.append("  edge %s [%s] refs %s %s=%s (declared in %s)"
                             % (eid, s, kind, end,
                                next((sc for sc, nid, _ in nodes if nid == end), "?"),
                                "no scope"))
    if not any(True for s, eid, rel, src, dst in edges
               if (s, src) not in node_scopes or (s, dst) not in node_scopes):
        lines.append("  none — every edge endpoint has a node in its scope")
    lines.append("")

    for s, nid, _ in nodes:
        if not any(ed for ed in edges if ed[0] == s and (ed[3] == nid or ed[4] == nid)):
            lines.append("  isolated node: %s (%s)" % (nid, s))

    return "\n".join(lines)


def build(nodes, edges):
    G = nx.DiGraph()
    for s, nid, label in nodes:
        G.add_node(nid, label=label, scope=s)
    for s, eid, rel, src, dst in edges:
        G.add_edge(src, dst, rel=rel, eid=eid, scope=s)
    return G


def render(G, status, out_path, rev_edges=()):
    pos = nx.spring_layout(G, seed=7, k=1.4)
    fig, ax = plt.subplots(figsize=(12, 9))

    scopes_seen = {}
    for nid in G.nodes():
        scope = G.nodes[nid]["scope"]
        scope_color(scope, scopes_seen)

    for nid, (x, y) in pos.items():
        label = G.nodes[nid]["label"]
        st = status.get(nid)
        body = "%s\n%s" % (nid, label)
        if st:
            body += "\n(%s)" % st
        ax.scatter(
            [x], [y],
            s=1800,
            color=NODE_COLORS.get(label, "#cccccc"),
            edgecolors=scope_color(G.nodes[nid]["scope"], scopes_seen),
            linewidths=2.2,
            zorder=3,
        )
        ax.text(x, y, body, ha="center", va="center", fontsize=8, zorder=4)

    for u, v, d in G.edges(data=True):
        mid = ((pos[u][0] + pos[v][0]) / 2, (pos[u][1] + pos[v][1]) / 2)
        ax.annotate(
            "", xy=pos[v], xytext=pos[u],
            arrowprops=dict(
                arrowstyle="-|>",
                color=EDGE_COLORS.get(d["rel"], "#555555"),
                lw=2,
                shrinkA=26,
                shrinkB=26,
            ),
        )
        ax.text(
            mid[0] + 0.015, mid[1] + 0.015,
            "%s\n%s" % (d["rel"], d["eid"]),
            ha="center", va="center", fontsize=6.5,
            color=EDGE_COLORS.get(d["rel"], "#555555"),
        )

    if rev_edges:
        for s, eid, rel, src, dst in rev_edges:
            if src not in pos or dst not in pos:
                continue
            ax.annotate(
                "", xy=pos[dst], xytext=pos[src],
                arrowprops=dict(
                    arrowstyle="-|>",
                    color="#999999",
                    lw=1,
                    ls=(0, (4, 2)),
                    shrinkA=30,
                    shrinkB=30,
                ),
                zorder=2,
            )
        ax.plot([], [], ls=(0, (4, 2)), color="#999999",
                label="rev-edge (generated index)")

    for scope, color in scopes_seen.items():
        ax.plot([], [], marker="o", color=color, label="scope: %s" % scope,
                linestyle="none")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.8)

    ax.set_title("Frontier test graph  —  %d nodes, %d edges (union of both files)"
                 % (G.number_of_nodes(), G.number_of_edges()))
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

    status = {}
    for s, nid, name, val in fields:
        if name == "status":
            status.setdefault(nid, val)

    G = build(nodes, edges)
    out_path = HERE / "test_frontier_graph.png"
    fig = render(G, status, out_path, rev_edges if show_rev else ())
    print("\nsaved: %s" % out_path)

    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()