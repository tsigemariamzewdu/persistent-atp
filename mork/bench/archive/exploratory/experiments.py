"""Experiment definitions for the PeTTa/MeTTa interface, without Python FFI."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Probe:
    name: str
    expression: str
    expected: str


@dataclass(frozen=True)
class Case:
    experiment: str
    scale: int
    nodes: int
    background: int = 0
    claims: bool = False
    probes: tuple[Probe, ...] = ()

    @property
    def stem(self) -> str:
        return f"{self.experiment}_{self.scale}"


LOOKUPS = (
    Probe("node", '(collapse (match &mork (node "target" "n1" $label) $label))', '("Move")'),
    Probe("incoming-edges", '(collapse (incoming-edges "target" "n1"))',
          '(("PROPOSES" "n0" "e1"))'),
    Probe("outgoing-edges", '(collapse (outgoing-edges "target" "n1"))', '()'),
)

EXPERIMENTS = {
    "E1": "unrelated proofs vs fixed leaf queries",
    "E2": "own proof growth vs fixed leaf queries",
    "E3": "atom add/remove cycle",
    "E4": "empty match overhead through PeTTa",
    "Q1": "frontier query vs candidate count",
    "Q2": "taint-cone query vs dependent count",
    "L1": "journal projection and projected file loading",
}


def cases(name: str, quick: bool) -> list[Case]:
    sizes = [10, 50] if quick else [50, 250, 1000]
    if name == "E1":
        return [Case(name, n, 10, background=n, probes=LOOKUPS)
                for n in ([0, 50, 250] if quick else [0, 250, 1000, 5000])]
    if name == "E2":
        return [Case(name, n, n, probes=LOOKUPS) for n in sizes]
    if name == "E3":
        probe = Probe("add-remove-cycle", '(let* (($added (add-atom &mork (bench-temp "unique"))) '
                      '($before (size-atom (collapse (match &mork (bench-temp $x) $x)))) '
                      '($removed (remove-atom &mork (bench-temp "unique")))) '
                      '($before (size-atom (collapse (match &mork (bench-temp $x) $x)))))', '(1 0)')
        return [Case(name, n, n, probes=(probe,)) for n in sizes]
    if name == "E4":
        probe = Probe("empty-match", '(collapse (match &mork (bench-absent $x) $x))', '()')
        return [Case(name, n, n, probes=(probe,)) for n in [0, *sizes]]
    if name in ("Q1", "Q2"):
        function = "frontier-for-state" if name == "Q1" else "taint-cone"
        return [Case(name, n, n, claims=name == "Q2", probes=(Probe(
            function, f'(size-atom ({function} "target" "n0"))', str(n - 1)),)) for n in sizes]
    if name == "L1":
        return [Case(name, n, n) for n in sizes]
    raise ValueError(f"Unknown experiment: {name}")
