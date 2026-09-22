# PTPS graph benchmarks

This suite compares **MORK through Python FFI**, **MORK through PeTTa**, and
**Neo4j** on the same logical graphs and answer contracts:

> How much time does each graph implementation take to perform the operations
> needed by PTPS, and how does that cost change as the stored graph grows?

Both MORK paths use the same native library. A Python dictionary model checks
correctness; it is not a fourth timed backend. The measurements include each
integration's operation and result-construction costs. They do not measure the
complete proof-search loop or equivalent durable commit protocols.

## Start here

- [Results and interpretation](results.md): the **frozen, incomplete** September
  20–21 evaluation, including timeouts and preliminary measurements.
- [Methodology](docs/METHODOLOGY.md): exact graphs, operations, timing boundaries,
  validation, commands, and interpretation limits.
- [Original FFI comparison](docs/COMPARISON.md): what was retained, added,
  renumbered, and deferred from the original `mork-ffi` suite.
- [Meeting notes](docs/meeting-notes.md): explanation of the submitted tables.
- [Runtime setup](runtime/README.md): prerequisites, pinned sources, and the two
  recorded PeTTa bridge compatibility changes.
- [Archive](archive/README.md): earlier exploratory code and ordinary-PeTTa results.

## Experiments and files

| Experiment | Timed work | Deliberately varied |
|---|---|---|
| **E1** | Nine individual reads and genuine mutations | Operation, with a fixed 1,000-node graph |
| **E2** | Node/edge reads and field overwrite | Target proof size; probe answers remain fixed |
| **E3** | Node/edge reads in an unchanged target proof | Size of unrelated proofs |
| **E4** | Eligible move IDs for one state | Candidates and 10% / 50% / 90% eligibility |
| **E5** | Unique claims affected by a refuted root | Claims and star / chain / diamond shape |
| **E6** | Rebuild an empty graph from a common operation history | History size |

Full mode contains **51 cases per backend**; quick mode contains **37** smaller
cases. The exact size ladders and result contracts are in the methodology.

| File or directory | Responsibility |
|---|---|
| [`experiments.py`](experiments.py) | E1–E6 fixtures, operations, and correctness oracle |
| [`harness.py`](harness.py) | CLI, isolated workers, timing, validation, and cleanup |
| [`reporting.py`](reporting.py) | Aggregation and generated reports |
| [`backends/`](backends/) | `mork_ffi.py`, shared `_ffi_transport.py`, `petta.py`, and `neo4j.py` |
| [`tests/`](tests/) | Correctness checks for the benchmark infrastructure |
| [`docs/`](docs/) | Detailed methodology, comparison, and meeting explanation |
| [`runtime/`](runtime/) | Reproduction manifest, patch, lockfile, and runtime probes |
| [`results/`](results/) | Current evaluation evidence and its frozen source snapshots |
| [`archive/`](archive/) | Earlier exploratory implementation and reports |

## Prepare the runtimes

Run commands from the repository root with Python 3.11 or newer:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

After following the prerequisites in [runtime/README.md](runtime/README.md):

```sh
python3 scripts/setup-bench-runtime.py
python3 scripts/setup-bench-runtime.py --check
python3 scripts/check-bench-runtime.py
```

The build script refuses to replace an existing runtime. For an existing build,
use the two check commands. Both MORK paths default to the shared library under
`.bench-runtime/PeTTa/mork_ffi/target/release/`; PeTTa runs through
`scripts/bench-petta.sh`. The runner verifies native MORK rather than accepting
an ordinary PeTTa space named `&mork`.

Start Neo4j and configure `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and optionally
`NEO4J_DATABASE` through the environment or repository `.env`. The adapter uses
its normal constraints and indexes. Fixtures have unique ownership, and cleanup
checks only those fixtures; other data remains present and may affect timing.

## Run measurements

A short correctness and connectivity check:

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench --backend all --quick \
  --repeats 1 --samples 3 --warmup 1 --timeout 120 \
  --output-dir /tmp/ptps-bench-smoke
```

A full evaluation in a **fresh output directory**:

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench --backend all \
  --scales 100,1000,10000 --repeats 5 --samples 30 --warmup 3 \
  --timeout 120 --output-dir /tmp/ptps-e1-e6-new
```

Select an experiment with `--experiment E2`, or repeat the option to select
several. Select one backend with `--backend mork-ffi`, `--backend mork-petta`,
or `--backend neo4j`. See `python -m mork.bench --help` and the
[measurement commands](docs/METHODOLOGY.md#running-the-measurements) for all options.
The smoke run's reduced samples and sizes are not the reference evaluation.

E1–E5 default to five trials, three warm-ups, and 30 measured calls per trial.
Tables report the median of trial medians in microseconds per operation. E6
uses one complete rebuild per trial, with no per-trial warm-ups; its cells are
microseconds per rebuild. The timeout applies to the **whole trial**, including
setup and validation, not to one query. The CLI default is 60 seconds; these
commands use 120 seconds. A failed case/backend stops its remaining repetitions.

The [September evaluation](results/common-e1-e6-2026-09-20/FROZEN.md) is frozen
at **712 trials: 704 successful and eight timeouts**. Its two E5 diamond results
at 10,000 claims have only two of five planned trials; E6 at 10,000 nodes is
unmeasured. Its saved source layout predates this reorganization. **Do not resume
or overwrite that directory with the current runner.** New measurements belong
in new directories and must retain their own runtime and source records.

## Outputs, direct PeTTa execution, and checks

Each run saves `results.md`, `trials.json` (raw samples), `summary.json`
(statistics), `environment.json` (configuration and status), and source/runtime
snapshots. Local `artifacts/` contains exact inputs, generated MeTTa programs,
worker configurations, and logs. Some recorded runs also include hardware and
application-source snapshots. See the methodology for the artifact definitions.

A generated program can be run like a MeTTa test:

```sh
scripts/bench-petta.sh /absolute/path/to/run/artifacts/E1_node-mork-petta-0/run.metta --silent
```

Keep its companion files in place: generated programs import absolute paths.
Direct execution prints samples and validation markers; the Python harness
checks their contents and completeness before accepting a trial.

Run infrastructure checks without launching performance workloads:

```sh
.venv/bin/python -m unittest discover -s mork/bench/tests
python3 scripts/check-bench-runtime.py
```

Files saved in the workspace are not automatically staged, committed, or pushed.
Runtime builds and detailed `artifacts/` logs are ignored by Git. Review
`git status --short` and `git diff --check` before staging the intended source,
documentation, and result evidence; retain local artifacts separately when they
are needed to reproduce a generated program.
