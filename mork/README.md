# MORK

MORK contains the MeTTa proof-graph projection and query layer.

## Contents

- `bench/` - Shared E1–E6 benchmarks for MORK FFI, MORK through PeTTa, and Neo4j.
  See [`bench/README.md`](bench/README.md) for running and generating `.metta`
  files, [`bench/docs/METHODOLOGY.md`](bench/docs/METHODOLOGY.md) for the experiment
  definitions, and [`bench/results.md`](bench/results.md) for the frozen partial
  evaluation. Earlier exploratory code and reports are under `bench/archive/`.
- `event_journals/` - Source event journals used to build proof graphs.
- `projector/` - Python code that projects journal events into MORK atoms.
- `proofs/` - Generated or checked-in proof graph projections.
- `rules/` - Lazy MeTTa queries for indexes, frontiers, dependencies, taint,
  routes, and duplicate candidates. See [`rules/README.md`](rules/README.md).
