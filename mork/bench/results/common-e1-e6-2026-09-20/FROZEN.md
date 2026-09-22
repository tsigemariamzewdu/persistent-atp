# Frozen evaluation: September 20–21, 2026

This evaluation was frozen on September 22 when the active benchmark code was
reorganized. It contains **712 recorded trials: 704 successful and eight whole-trial
timeouts**. The existing samples, statistics, runtime records, and original
source snapshots are preserved. No performance measurements were added during
the reorganization.

The evaluation is incomplete:

- E5 diamond graphs with 10,000 claims have only **two of five planned trials**
  for MORK FFI and Neo4j. Their numerical cells are preliminary.
- E6 rebuilds with 10,000 nodes have no recorded trials for any backend.
- Eight MORK–PeTTa case/backend combinations timed out. A timeout applies to
  the complete trial, including setup and validation; it is not a measured
  query latency.

`environment.json` retains its last recorded status, `running`. That historical
field is not a live-process status and does not mean this evaluation will resume.
The current runner rejects its older source layout. Use a **fresh output
directory** for new measurements; do not append to or overwrite this evidence.

## Reading and reproducing the evidence

- [Narrative report](../../results.md): results, interpretation, and limitations.
- [Recorded table](results.md): generated tables with preliminary and pending cells.
- [Raw trials](trials.json) and [summary](summary.json): measured samples and statistics.
- [Environment](environment.json) and [hardware](hardware.json): recorded configuration.
- [Measured source](measured-source/): the benchmark implementation when the run began.
- [Continuation source](continuation-source/): the driver used when the run continued.
- [Report source](report-source/): the final pre-reorganization driver/report renderer,
  preserved separately because reporting corrections are not new measurements.
- [Application source record](application-source.json), [application sources](application-source/),
  and [runtime](runtime/): recorded rules, adapter code, and runtime build information.

The old source snapshots use the old module names and paths. They are evidence
of the measured implementation, not a runnable package in their snapshot
directory. Reproducing that exact implementation requires reconstructing its
original layout and pinned runtime. The [current instructions](../../README.md)
run the same logical E1–E6 workloads through the reorganized code, with their
own source hashes and output directory.

Large `artifacts/` files are retained locally and excluded from Git. They contain
the generated programs, fixture inputs, and detailed worker logs. Original
generated programs refer to absolute paths on the measurement machine.
