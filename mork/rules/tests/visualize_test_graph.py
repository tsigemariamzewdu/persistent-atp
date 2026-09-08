"""Visualize test_graph.metta as a directed graph.

Usage:
    python visualize_test_graph.py            # save PNG + print structure
    python visualize_test_graph.py --rev      # also overlay the reverse index
    python visualize_test_graph.py --show     # open an interactive window

Parses the (node ...), (edge ...), and (rev-edge ...) add-atom stanzas
directly from the Metta file, so the picture always reflects what is
actually declared. Cross-checks that every forward edge has a matching
reverse-index entry.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

HERE = Path(__file__).resolve().parent
METTA_FILE = HERE / "test_graph.metta"

NODE_COLORS = {
    "State": "#aec7e8",
    "Move": "#ffbb78",
    "Claim": "#98df8a",
    "Attempt": "#ff9896",
}
EDGE_COLORS = {
    "PROPOSES": "#1f77b4",
    "SUPPORTED_BY": "#2ca02c",
    "ON_STATE": "#d62728",
    "ON_MOVE": "#9467bd",
}


def parse_graph(text: str):
    nodes = {}  # id -> label
    edges = []  # (eid, rel, src, dst) from forward edge atoms
    rev_edges = []  # (eid, rel, src, dst) from rev-edge index atoms

    for line in text.splitlines():
        line = line.strip()
        m = re.search(r'\(node\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)', line)
        if m:
            _, node_id, label = m.groups()
            nodes[node_id] = label
            continue
        m = re.search(
            r'\(rev-edge\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)',
            line,
        )
        if m:
            # rev-edge schema: (rev-edge $p $target $rel $src $eid)
            # -> target is the forward edge's DESTINATION, src is its SOURCE.
            _, target, rel, src, eid = m.groups()
            rev_edges.append((eid, rel, src, target))
            continue
        m = re.search(
            r'\(edge\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\s+"([^"]+)"\)',
            line,
        )
        if m:
            _, eid, rel, src, dst = m.groups()
            edges.append((eid, rel, src, dst))

    return nodes, edges, rev_edges


def build(nodes, edges):
    G = nx.DiGraph()
    for nid, label in nodes.items():
        G.add_node(nid, label=label)
    for eid, rel, src, dst in edges:
        G.add_edge(src, dst, rel=rel, eid=eid)
    return G


def forward_key(e):
    """Canonical key of a forward edge (eid, rel, src, dst)."""
    return (e[0], e[1], e[2], e[3])


def describe(nodes, edges, rev_edges, G):
    lines = []
    lines.append("=== Nodes (%d) ===" % len(nodes))
    for nid, label in sorted(nodes.items()):
        deg = G.degree(nid)
        lines.append("  %-4s  %-8s  degree=%d" % (nid, label, deg))
    lines.append("")
    lines.append("=== Edges (%d) ===" % len(edges))
    for eid, rel, src, dst in sorted(edges, key=lambda e: e[0]):
        lines.append("  %-3s  %s -%s-> %s" % (eid, src, rel, dst))
    lines.append("")
    lines.append("=== Reverse index (%d, generated) ===" % len(rev_edges))
    for eid, rel, src, dst in sorted(rev_edges, key=lambda e: e[0]):
        lines.append("  %-3s  %s -%s-> %s   (rev-edge atom)" % (eid, rel, src, dst))
    lines.append("")

    forward = {forward_key(e) for e in edges}
    rev = {forward_key(e) for e in rev_edges}
    missing = sorted(forward - rev)
    extra = sorted(rev - forward)
    if not missing and not extra:
        lines.append("consistency: forward edges and reverse index AGREE (%d edge(s))"
                     % len(forward))
    else:
        if missing:
            lines.append("WARNING: reverse index MISSING for: %s" % missing)
        if extra:
            lines.append("WARNING: reverse index has EXTRA entries: %s" % extra)
    lines.append("")

    for nid, label in nodes.items():
        if G.degree(nid) == 0:
            lines.append("isolated node: %s (%s)" % (nid, label))
    return "\n".join(lines)


def render(G, out_path, rev_edges=()):
    pos = nx.spring_layout(G, seed=7, k=1.7)

    fig, ax = plt.subplots(figsize=(9, 7))
    for nid, (x, y) in pos.items():
        label = G.nodes[nid]["label"]
        ax.scatter(
            [x], [y],
            s=1600,
            color=NODE_COLORS.get(label, "#cccccc"),
            edgecolors="black",
            linewidths=1.2,
            zorder=3,
        )
        ax.text(
            x, y, "%s\n%s" % (nid, label),
            ha="center", va="center", fontsize=9, zorder=4,
        )

    for u, v, d in G.edges(data=True):
        rel = d["rel"]
        eid = d["eid"]
        mid = ((pos[u][0] + pos[v][0]) / 2, (pos[u][1] + pos[v][1]) / 2)
        ax.annotate(
            "", xy=pos[v], xytext=pos[u],
            arrowprops=dict(
                arrowstyle="-|>",
                color=EDGE_COLORS.get(rel, "#555555"),
                lw=2,
                shrinkA=26,
                shrinkB=26,
            ),
        )
        ax.text(
            mid[0] + 0.015, mid[1] + 0.015,
            "%s\n%s" % (rel, eid),
            ha="center", va="center", fontsize=7,
            color=EDGE_COLORS.get(rel, "#555555"),
        )

    if rev_edges:
        for eid, rel, src, dst in rev_edges:
            u, v = src, dst
            if u not in pos or v not in pos:
                continue
            ax.annotate(
                "", xy=pos[v], xytext=pos[u],
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
        ax.plot([], [], ls=(0, (4, 2)), color="#999999", lw=1.2,
                label="rev-edge (generated index)")
        ax.legend(loc="lower left", fontsize=8, framealpha=0.8)

    rev_note = ", +%d rev-edge" % len(rev_edges) if rev_edges else ""
    ax.set_title("test_graph.metta  —  %d nodes, %d forward edges%s"
                 % (G.number_of_nodes(), G.number_of_edges(), rev_note))
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    return fig


def main():
    show = "--show" in sys.argv
    show_rev = "--rev" in sys.argv
    text = METTA_FILE.read_text(encoding="utf-8")
    nodes, edges, rev_edges = parse_graph(text)
    G = build(nodes, edges)

    print(describe(nodes, edges, rev_edges, G))

    out_path = HERE / "test_graph.png"
    fig = render(G, out_path, rev_edges if show_rev else ())
    print("\nsaved: %s" % out_path)

    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()
