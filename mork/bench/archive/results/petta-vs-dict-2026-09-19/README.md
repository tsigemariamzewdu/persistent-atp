# PeTTa-space vs Python-dictionary results

**The current runtime is ordinary PeTTa space, not MORK. These ratios do not measure MORK performance.**

The full paired sweep completed: 23 workload cases, 34 paired operation/scale comparisons, and 74 total result rows (including 6 unpaired projection/load rows). All benchmark correctness checks and 10 Python harness/baseline tests passed.

Run recorded 2026-09-19T19:22:01.028989+00:00. CPU: 12th Gen Intel(R) Core(TM) i5-1235U; Python 3.12.12; SWI-Prolog version 9.3.33 for x86_64-linux.

## At 1,000 target nodes/claims

Median CPU microseconds per call. Ratio = PeTTa / dict: higher means PeTTa used more CPU time.

| Operation | PeTTa µs | Dict µs | Ratio |
| --- | ---: | ---: | ---: |
| node | 3.614 | 0.520 | 6.95× |
| incoming-edges | 4.412 | 0.450 | 9.80× |
| outgoing-edges | 52.832 | 0.440 | 120.07× |
| add-remove-cycle | 6.183 | 0.718 | 8.61× |
| empty-match | 169.036 | 0.324 | 521.72× |
| frontier-for-state | 10973.049 | 314.405 | 34.90× |
| taint-cone | 8710.273 | 586.160 | 14.86× |

These are ratios from one sweep, not fixed properties of either system. Sub-microsecond dictionary operations are sensitive to timer overhead. The empty-match test queries an entirely absent relation, so its ratio should not be generalized to all failed lookups.

## Every experiment

- [E1: unrelated-proof growth](E1.md)
- [E2: target-proof growth](E2.md)
- [E3: add/check/remove/check cycle](E3.md)
- [E4: empty match](E4.md)
- [Q1: frontier queries](Q1.md)
- [Q2: taint-cone queries](Q2.md)
- L1 is recorded in the raw rows, but has no dictionary ratio: parsing and executing a MeTTa file is a different operation from building a dictionary.

## What is and is not comparable

| Capability | Coverage |
| --- | --- |
| Node, incoming/outgoing edges, atom add/remove | Same projected data and equivalent returned values; both directions indexed explicitly in Python |
| Frontier and taint | Equivalent results on the generated acyclic graphs; Python explicitly implements the algorithms |
| Generic MeTTa evaluation / unification | Not implemented by the dictionary baseline |
| MORK storage performance | Not measured: the current PeTTa launcher does not enable MORK |
| Loading | PeTTa projection-file loading measured; no paired ratio |
| Memory, persistence, commit-gate integration, recovery, concurrency | Not measured |

The Python baseline is a purpose-built indexed graph, not a bare dict.get for every operation and not the production MemoryView adapter. Both sides materialize results. Python does not return precomputed frontier/taint counts. Data generation and index construction are outside query timing.

Both sides measure executing-thread CPU time with 3 discarded warm-ups and 30 measured samples. PeTTa and Python use different timers, and their timer/call overhead is retained. The Python baseline starts with a fresh graph for each case; PeTTa starts a fresh process. PeTTa runs first, then Python, for each case. This compares complete implementations, including their different indexes and evaluation overhead; it does not isolate the storage engine.

## Reproduce

```sh
.venv/bin/python -m mork.bench --allow-petta-space --compare-dict --output-dir mork/bench/results/petta-vs-dict-2026-09-19/generated --json mork/bench/results/petta-vs-dict-2026-09-19/results.json --comparison-markdown mork/bench/results/petta-vs-dict-2026-09-19/comparison.md
```

For MORK measurements, configure a MORK-enabled launcher and remove `--allow-petta-space` before rerunning. These saved results must retain their `petta-space` label.

## Evidence

- [Complete comparison table](comparison.md)
- [Raw rows](results.json)
- [Driver output](run.log)
- [Environment, source hashes, and exact command](environment.json)
- [10 passing harness/baseline tests](harness-tests.log)
- Generated programs and per-case logs remain locally in `generated/`, excluded from Git.
