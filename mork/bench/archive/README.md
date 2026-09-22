# Archived exploratory benchmarks

This directory preserves the earlier exploratory runner and September 19
reports. The active, shared three-integration E1–E6 suite is documented in
[the benchmark README](../README.md).

| Location | Contents |
|---|---|
| [`exploratory/`](exploratory/) | Earlier PeTTa runner, comparison helpers, fixtures, and their tests |
| [`results/petta-space-2026-09-19/`](results/petta-space-2026-09-19/README.md) | Ordinary PeTTa-space measurements |
| [`results/petta-vs-dict-2026-09-19/`](results/petta-vs-dict-2026-09-19/README.md) | Ordinary PeTTa and Python dictionaries |
| [`results/petta-dict-neo4j-2026-09-19/`](results/petta-dict-neo4j-2026-09-19/README.md) | Ordinary PeTTa, Python dictionaries, and Neo4j |

**These PeTTa runs did not enable native MORK.** Their timings cannot populate
the MORK–PeTTa column of the current report. Workloads, numbering, output
contracts, and some clocks also differ. Preserve their original interpretation
rather than combining their numbers with the shared E1–E6 evaluation.

The archived entry points, run from the repository root, are:

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench.archive.exploratory --help
PYTHONPATH=src:. .venv/bin/python -m mork.bench.archive.exploratory.compare_backends --help
```

They retain their historical options and experiment names. For current
measurements use `python -m mork.bench`, which executes the shared E1–E6 suite.
Archived report commands and paths describe the original runs and are retained
as historical evidence; use the relocated entry points above when inspecting
the archived implementation.

The original FFI E1–E7 suite is a separate reference at Git commit
`20ce55b97a396a384346a33b85493768fde5a89e` on `mork-ffi`. This archive contains the
intermediate exploratory implementation, not an exact copy of that original
FFI suite. See [the comparison](../docs/COMPARISON.md) for the precise mapping.

The September 20–21 native-MORK evaluation remains under
[`../results/common-e1-e6-2026-09-20/`](../results/common-e1-e6-2026-09-20/FROZEN.md),
with its original measured source snapshots. It is frozen and incomplete;
archive relocation does not change any measurements or complete missing trials.
