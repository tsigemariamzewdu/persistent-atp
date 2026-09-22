# Full PeTTa-space benchmark results

**These are ordinary PeTTa-space results, not MORK results.** The current launcher did not enable MORK. Its initialization probe returned:

```text
(BENCH_INIT (partial mm2-exec (&mork 1)))
```

Run recorded 2026-09-19T19:17:32.825813+00:00. All 7 experiment groups, 23 scale cases, and 40 result rows completed successfully. Each case passed its atom-count and query-result checks. The 6 Python harness tests also passed ([test log](harness-tests.log)). Performance has no pass/fail threshold.

| Experiment | Result documentation | Cases | Rows |
| --- | --- | ---: | ---: |
| E1 | [unrelated proofs vs fixed leaf queries](E1.md) | 4 | 12 |
| E2 | [own proof growth vs fixed leaf queries](E2.md) | 3 | 9 |
| E3 | [atom add/remove cycle](E3.md) | 3 | 3 |
| E4 | [empty match overhead through PeTTa](E4.md) | 4 | 4 |
| Q1 | [frontier query vs candidate count](Q1.md) | 3 | 3 |
| Q2 | [taint-cone query vs dependent count](Q2.md) | 3 | 3 |
| L1 | [journal projection and projected file loading](L1.md) | 3 | 6 |

## Environment and method

- CPU: 12th Gen Intel(R) Core(TM) i5-1235U; 12 logical CPUs reported.
- Python: 3.12.12; SWI-Prolog version 9.3.33 for x86_64-linux.
- Repository branch: `benchmark-mork`, base commit `1c3beb67da52e1fd11396929f91f15abe275aa0a` plus the uncommitted benchmark adaptation. [Source hashes and environment](environment.json).
- PeTTa base commit: `e1490899cefc67c128d5311ff4861f9997674957`. Local modifications are recorded in the environment file.
- Full sizes; 3 warm-ups and 30 measured samples per query/cycle. Loading is one observation per size.
- PeTTa rows measure executing-thread CPU time, excluding startup and query data loading. Python projection rows measure monotonic elapsed time. All values are in microseconds.
- One sweep; not an average of independent repeated sweeps. No MORK performance, memory-reclamation, or deep-graph conclusions can be drawn.

## Reproduce the full run

```sh
.venv/bin/python -m mork.bench --allow-petta-space --output-dir mork/bench/results/petta-space-2026-09-19/generated --json mork/bench/results/petta-space-2026-09-19/results.json
```

This command explicitly permits the current ordinary PeTTa backend. To measure MORK, configure a MORK-enabled PeTTa launcher and rerun without `--allow-petta-space`; do not relabel these results.

## Evidence

- [Machine-readable rows](results.json)
- [Complete driver output](run.log)
- [Environment and source hashes](environment.json)
- [Harness test output](harness-tests.log)
- Generated `.metta` programs, data, and individual logs are retained locally in `generated/`; regenerate them using the command above on another machine.
