"""Visualize the graph used by the dependency-taint tests.

Renders the union of the shared fixture (tests/test_graph.metta) and the
dependency-taint extras (tests/test_dependency_taint.metta) from the actual
add-atom stanzas, and recomputes the section 4/5 rule results in Python so
you can cross-check the .metta tests against the graph.

Semantics (from dependency-taint.metta):
  - (edge $p $eid "DEPENDS_ON" $a $b)  ->  $a depends on $b
  - reaches?(x, b)  ->  following DEPENDS_ON from x (x == b allowed)
  - refuted root's taint cone  ->  all claims (except root) reaching root
  - affected states  ->  formally-closed states using a tainted claim

Usage:
    python visualize_dependency_taint_graph.py          # PNG + printed checks
    python visualize_dependency_taint_graph.py --rev    # overlay rev-edge index
    python visualize_dependency_taint_graph.py --show   # interactive window
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx

from visualize_test_graph import EDGE_COLORS, NODE_COLORS

HERE = Path(__file__).resolve().parent
FILES = [HERE / "test_graph.metta", HERE / "test_dependency_taint.metta"]

# visual styling extras
TAINT_SRC = "#d62728"     # refuted claim (taint source)
TAINTED = "#ff7f0e"       # claims in the taint cone
AFFECTED = "#d62728"      # closed states that must reopen
CLEAN = "#2ca02c"         # clean chain / unaffected
USES_COLOR = "#9467bd"    # USES_CLAIM edges
BASE_COLOR = "#bbbbbb"    # non-DEPENDS_ON/USES_CLAIM edges (base fixture)


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


def extract(edges):
    depends_on = []   # (eid, a, b)   a depends on b
    uses_claim = []   # (eid, sid, cid)
    other = []        # (eid, rel, src, dst)
    for s, eid, rel, src, dst in edges:
        if rel == "DEPENDS_ON":
            depends_on.append((eid, src, dst))
        elif rel == "USES_CLAIM":
            uses_claim.append((eid, src, dst))
        else:
            other.append((eid, rel, src, dst))
    return depends_on, uses_claim, other


class Reachability:
    """Python mirror of the dependency-taint.metta rules."""

    def __init__(self, nodes, fields, edges):
        self.claims = {nid for s, nid, lab in nodes if lab == "Claim"}
        self.states = {nid for s, nid, lab in nodes if lab == "State"}
        self.fields = {(s, nid, name): val for s, nid, name, val in fields}
        self.dep_edges, self.use_edges, _ = extract(edges)
        self.fwd = {}  # a -> [b]  (a depends on b)
        for eid, a, b in self.dep_edges:
            self.fwd.setdefault(a, []).append(b)
        self.status = {}
        for (s, nid, name), val in self.fields.items():
            if name == "status":
                self.status[(s, nid)] = val

    def _reaches(self, x, b, seen):
        if x == b:
            return True
        if x in seen:
            return False
        seen.add(x)
        return any(self._reaches(y, b, seen) for y in self.fwd.get(x, []))

    def reaches(self, a, b):
        return self._reaches(a, b, set())

    def deps_of(self, x):
        return sorted(self.fwd.get(x, []))

    def depends_on(self, claim):
        return sorted(c for c in self.claims
                      if c != claim and self.reaches(c, claim))

    def depends_on_chain(self, claim):
        return sorted(c for c in self.claims
                      if c != claim and self.reaches(claim, c))

    def would_cycle(self, dep, dep_of):
        return self.reaches(dep_of, dep)

    def is_refuted(self, node):
        return self.status.get(("test-proof", node)) == "refuted"

    def taint_cone(self, root):
        if not self.is_refuted(root):
            return []
        return sorted(c for c in self.claims
                      if c != root and self.reaches(c, root))

    def affected_states(self, root):
        if not self.is_refuted(root):
            return []
        cone = set(self.taint_cone(root))
        out = []
        for sid in sorted(self.states):
            used = [cid for eid, s, cid in self.use_edges if s == sid]
            if (self.status.get(("test-proof", sid)) == "formally-closed"
                    and any(c in cone for c in used)):
                out.append(sid)
        return out


def describe(nodes, fields, edges, rev_edges, R):
    lines = []

    scopes = {}
    for scope, nid, _ in nodes:
        scopes.setdefault(scope, []).append(nid)
    lines.append("=== Nodes by proof scope ===")
    for scope, nids in sorted(scopes.items()):
        lines.append("  %-11s %-3d  %s" % (scope, len(nids), ", ".join(sorted(nids))))
    lines.append("")

    status = {nid: val for (s, nid), val in R.status.items()}
    lines.append("=== Nodes (id, label, status) ===")
    for s, nid, label in sorted(nodes, key=lambda n: (n[0], n[1])):
        st = status.get(nid, "")
        lines.append("  [%-11s] %-4s %-9s %s" % (s, nid, label, st))
    lines.append("")

    dep, use, other = extract(edges)
    lines.append("=== DEPENDS_ON edges (%d)  (a -depends_on-> b)" % len(dep))
    for eid, a, b in sorted(dep, key=lambda e: e[0]):
        lines.append("  %-3s  %s -DEPENDS_ON-> %s" % (eid, a, b))
    lines.append("")

    lines.append("=== USES_CLAIM edges (%d)  (state -uses-> claim)" % len(use))
    for eid, a, b in sorted(use, key=lambda e: e[0]):
        lines.append("  %-3s  %s -USES_CLAIM-> %s" % (eid, a, b))
    lines.append("")

    lines.append("=== Other (base fixture) edges (%d) ===" % len(other))
    for eid, rel, a, b in sorted(other, key=lambda e: e[0]):
        lines.append("  %-3s  %s -%s-> %s" % (eid, a, rel, b))
    lines.append("")

    fwd = {(s, e, rel, src, dst) for s, e, rel, src, dst in edges}
    rev = {(s, e, rel, src, dst) for s, e, rel, src, dst in rev_edges}
    if fwd == rev:
        lines.append("  forward == reverse index (%d edge(s))" % len(fwd))
    else:
        lines.append("  MISMATCH missing=%s extra=%s"
                     % (sorted(fwd - rev), sorted(rev - fwd)))
    lines.append("")

    lines.append("=== 4.3 deps-of ===")
    for cid in sorted(R.claims):
        lines.append("  deps-of %s = %s" % (cid, R.deps_of(cid)))
    lines.append("")

    lines.append("=== 4.7 depends-on (transitive dependents) ===")
    for cid in sorted(R.claims):
        lines.append("  depends-on %s = %s" % (cid, R.depends_on(cid)))
    lines.append("")

    lines.append("=== 4.8 depends-on-chain (transitive dependencies) ===")
    for cid in sorted(R.claims):
        lines.append("  depends-on-chain %s = %s" % (cid, R.depends_on_chain(cid)))
    lines.append("")

    lines.append("=== 4.9 would-cycle? (would adding a->b cycle?) ===")
    for a, b in [("c1", "c4"), ("c5", "c7"), ("c1", "c5"),
                 ("c4", "c1"), ("c1", "c2")]:
        lines.append("  added %s->%s cycle? %s" % (a, b, R.would_cycle(a, b)))
    lines.append("")

    lines.append("=== 5.1 taint-cone ===")
    for cid in sorted(R.claims):
        lines.append("  taint-cone %s = %s" % (cid, R.taint_cone(cid)))
    lines.append("")

    lines.append("=== 5.5 affected-states ===")
    for cid in sorted(R.claims):
        lines.append("  affected-states %s = %s" % (cid, R.affected_states(cid)))
    lines.append("")

    return "\n".join(lines)


def render(nodes, fields, edges, R, out_path, rev_edges=()):
    # Generous manual layout: big gaps between nodes so nothing collides.
    #   chain 1 (clean):   c4 -> c3 -> c2 -> c1      along x=0, spacing 2.4
    #   chain 2 (tainted): c7 -> c6 -> c5            along x=5.2, spacing 2.4
    #   states (USES_CLAIM) sit right of chain 2 / left of chain 1
    pos = {
        "c1": (0.0, 0.0), "c2": (0.0, 2.4), "c3": (0.0, 4.8), "c4": (0.0, 7.2),
        "c5": (5.2, 0.0), "c6": (5.2, 2.4), "c7": (5.2, 4.8),
        "s4": (-3.0, 1.2),          # uses c1 (clean, closed, unaffected)
        "s3": (8.6, 2.0),           # uses c6 (open -> not affected)
        "s1": (8.6, 3.4),           # uses c6 (closed -> affected)
        "s2": (8.6, 4.8),           # uses c7 (closed -> affected)
        "a1": (2.6, 6.0),           # base fixture: ON_STATE -> s1
        "m1": (8.6, -0.4),          # base fixture: PROPOSES from s1
    }
    fig, ax = plt.subplots(figsize=(15, 9))
    ax.set_xlim(-4.4, 10.4)
    ax.set_ylim(-2.2, 8.8)

    dep, use, other = extract(edges)
    status = {}
    for (s, nid), val in R.status.items():
        status[nid] = val

    taint_cone = set(R.taint_cone("c5"))

    def draw_edge(u, v, label_lines, color, lw=2.6, style="-", zorder=3):
        ax.annotate(
            "", xy=pos[v], xytext=pos[u],
            arrowprops=dict(
                arrowstyle="-|>", mutation_scale=20,
                color=color, lw=lw, ls=style,
                shrinkA=30, shrinkB=30,
            ),
            zorder=zorder,
        )
        (x1, y1), (x2, y2) = pos[u], pos[v]
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        dx, dy = x2 - x1, y2 - y1
        L = (dx * dx + dy * dy) ** 0.5 or 1.0
        tx, ty = mx - dy / L * 0.24, my + dx / L * 0.24
        ax.text(tx, ty, label_lines, ha="center", va="center", fontsize=8.5,
                color=color, zorder=5,
                bbox=dict(boxstyle="round,pad=0.25", fc="white",
                          ec=color, lw=1.2))

    # DEPENDS_ON edges first, thick and black so they cannot be missed
    for eid, a, b in sorted(dep, key=lambda e: e[0]):
        draw_edge(a, b, "DEPENDS_ON\n%s" % eid, "#111111", lw=3.0)

    # USES_CLAIM edges
    for eid, sid, cid in sorted(use, key=lambda e: e[0]):
        draw_edge(sid, cid, "USES\n%s" % eid, USES_COLOR, lw=2.2)

    # base fixture edges, faint dashed gray
    for eid, rel, a, b in other:
        draw_edge(a, b, "%s\n%s" % (rel, eid), BASE_COLOR, lw=1.4, style=(0, (4, 2)))

    def claim_color(nid):
        if status.get(nid) == "refuted":
            return TAINT_SRC
        if nid in taint_cone:
            return TAINTED
        return CLEAN

    for nid, (x, y) in pos.items():
        label = dict((nn, lab) for s, nn, lab in nodes)[nid]
        edge_color = "#000000"
        face = NODE_COLORS.get(label, "#cccccc")
        if label == "Claim":
            face = claim_color(nid)
        if label == "State":
            if nid in R.affected_states("c5"):
                edge_color = AFFECTED
        body = nid if label == "Claim" else "%s (%s)" % (nid, label)
        if label == "State" and nid in status:
            body += "\n%s" % status[nid]
        ax.scatter([x], [y], s=1100, color=face,
                   edgecolors=edge_color, linewidths=2.2, zorder=4)
        ax.text(x, y, body, ha="center", va="center",
                fontsize=10, fontweight="bold", zorder=5)

    if rev_edges:
        ax.plot([], [], ls=(0, (4, 2)), color="#999999",
                label="rev-edge (generated index)")
    ax.plot([], [], color="#111111", lw=3,
            label="DEPENDS_ON (a depends on b)")
    ax.plot([], [], color=USES_COLOR, label="USES_CLAIM (state uses claim)")
    ax.plot([], [], color=BASE_COLOR, label="base fixture edges (e1-e3)")
    ax.plot([], [], marker="o", color=TAINT_SRC,
            label="refuted claim (c5, taint source)")
    ax.plot([], [], marker="o", color=TAINTED,
            label="in c5 taint cone (c6, c7)")
    ax.plot([], [], marker="o", color=CLEAN, label="clean claim chain")
    ax.plot([], [], marker="o", color="#aec7e8",
            label="State (red ring = affected)")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.92)

    ax.set_title("Dependency-taint test graph  —  %d nodes, %d edges\n"
                 "c5 refuted -> taints c6,c7 -> reopens s1,s2"
                 % (len(pos), len(edges)))
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

    R = Reachability(nodes, fields, edges)
    print(describe(nodes, fields, edges, rev_edges, R))

    out_path = HERE / "test_dependency_taint_graph.png"
    fig = render(nodes, fields, edges, R, out_path, rev_edges if show_rev else ())
    print("\nsaved: %s" % out_path)

    if show:
        plt.show()
    else:
        plt.close(fig)


if __name__ == "__main__":
    main()