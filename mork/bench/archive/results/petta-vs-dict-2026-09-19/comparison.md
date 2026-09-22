# PeTTa vs indexed Python dictionaries

Ratio = PeTTa median / Python-dict median. Above 1 means PeTTa took more CPU time.

| Experiment | Operation | Scale | Atoms | Runtime | PeTTa median µs | Dict median µs | Ratio | PeTTa p95 µs | Dict p95 µs |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| E1 | node | 0 | 66 | petta-space | 3.368 | 0.434 | 7.76× | 6.065 | 1.167 |
| E1 | incoming-edges | 0 | 66 | petta-space | 4.915 | 0.467 | 10.53× | 15.204 | 0.505 |
| E1 | outgoing-edges | 0 | 66 | petta-space | 3.863 | 0.566 | 6.83× | 8.841 | 2.324 |
| E1 | node | 250 | 1776 | petta-space | 3.201 | 0.387 | 8.28× | 7.811 | 0.675 |
| E1 | incoming-edges | 250 | 1776 | petta-space | 5.629 | 0.423 | 13.29× | 8.232 | 0.671 |
| E1 | outgoing-edges | 250 | 1776 | petta-space | 4.851 | 0.371 | 13.08× | 67.319 | 0.413 |
| E1 | node | 1000 | 6906 | petta-space | 2.439 | 0.617 | 3.96× | 2.628 | 1.088 |
| E1 | incoming-edges | 1000 | 6906 | petta-space | 4.277 | 0.666 | 6.42× | 8.438 | 0.820 |
| E1 | outgoing-edges | 1000 | 6906 | petta-space | 4.126 | 0.622 | 6.63× | 261.874 | 0.811 |
| E1 | node | 5000 | 34266 | petta-space | 3.104 | 1.116 | 2.78× | 4.876 | 2.036 |
| E1 | incoming-edges | 5000 | 34266 | petta-space | 4.437 | 0.714 | 6.21× | 10.818 | 12.956 |
| E1 | outgoing-edges | 5000 | 34266 | petta-space | 4.303 | 0.424 | 10.14× | 829.264 | 0.676 |
| E2 | node | 50 | 346 | petta-space | 4.883 | 0.806 | 6.06× | 9.601 | 4.922 |
| E2 | incoming-edges | 50 | 346 | petta-space | 4.898 | 0.792 | 6.18× | 9.826 | 1.202 |
| E2 | outgoing-edges | 50 | 346 | petta-space | 4.770 | 0.739 | 6.45× | 7.277 | 1.042 |
| E2 | node | 250 | 1746 | petta-space | 2.467 | 0.526 | 4.69× | 4.278 | 1.062 |
| E2 | incoming-edges | 250 | 1746 | petta-space | 3.581 | 0.506 | 7.08× | 7.391 | 0.845 |
| E2 | outgoing-edges | 250 | 1746 | petta-space | 15.224 | 0.451 | 33.79× | 29.673 | 0.542 |
| E2 | node | 1000 | 6996 | petta-space | 3.614 | 0.520 | 6.95× | 4.980 | 1.201 |
| E2 | incoming-edges | 1000 | 6996 | petta-space | 4.412 | 0.450 | 9.80× | 7.667 | 0.751 |
| E2 | outgoing-edges | 1000 | 6996 | petta-space | 52.832 | 0.440 | 120.07× | 77.471 | 0.767 |
| E3 | add-remove-cycle | 50 | 346 | petta-space | 9.219 | 0.641 | 14.39× | 19.640 | 1.071 |
| E3 | add-remove-cycle | 250 | 1746 | petta-space | 6.948 | 0.768 | 9.04× | 13.141 | 1.534 |
| E3 | add-remove-cycle | 1000 | 6996 | petta-space | 6.183 | 0.718 | 8.61× | 7.631 | 1.423 |
| E4 | empty-match | 0 | 0 | petta-space | 288.793 | 0.478 | 604.17× | 720.538 | 0.754 |
| E4 | empty-match | 50 | 346 | petta-space | 282.060 | 0.426 | 661.34× | 472.964 | 0.752 |
| E4 | empty-match | 250 | 1746 | petta-space | 251.589 | 0.360 | 697.89× | 415.051 | 0.587 |
| E4 | empty-match | 1000 | 6996 | petta-space | 169.036 | 0.324 | 521.72× | 561.867 | 0.623 |
| Q1 | frontier-for-state | 50 | 346 | petta-space | 638.824 | 16.742 | 38.16× | 1595.717 | 28.321 |
| Q1 | frontier-for-state | 250 | 1746 | petta-space | 2638.531 | 74.933 | 35.21× | 5231.345 | 105.514 |
| Q1 | frontier-for-state | 1000 | 6996 | petta-space | 10973.049 | 314.405 | 34.90× | 15190.794 | 1452.432 |
| Q2 | taint-cone | 50 | 297 | petta-space | 396.955 | 22.853 | 17.37× | 534.662 | 24.246 |
| Q2 | taint-cone | 250 | 1497 | petta-space | 2535.388 | 162.192 | 15.63× | 7799.761 | 190.416 |
| Q2 | taint-cone | 1000 | 5997 | petta-space | 8710.273 | 586.160 | 14.86× | 11312.896 | 1080.438 |

## Interpretation and limits

- `petta-space` is ordinary PeTTa, not MORK. A MORK slowdown cannot be inferred from those rows.
- Both sides use the exact same projected atoms, materialize query results, and check expected results. Graph construction is outside query timing.
- PeTTa uses executing-thread CPU time; Python uses `thread_time_ns`. Each side has identical warm-up/sample counts. Individual calls are timed, so timer and language-call overhead remain, especially for sub-microsecond dictionary operations.
- Python is a purpose-built graph implementation with hash indexes for nodes, fields, labels, layers, and both adjacency directions. PeTTa executes the existing MeTTa rules. These ratios compare complete implementations, not isolated storage engines or equal index layouts.
- Frontier and taint queries materialize lists before counting. Python reachability is an iterative search; it is not a general MeTTa evaluator. Equivalence is checked on these acyclic benchmark workloads, not all possible graphs.
- L1 has no paired ratio: parsing/executing a MeTTa file is not equivalent to constructing dictionaries. Python projection is already measured separately.
- This does not compare memory use, persistence, live commits, crash recovery, general unification, or concurrent workloads. No single overall slowdown is meaningful across these operations.
- One sweep, with PeTTa followed by Python per case. Repeat independent sweeps for stable estimates; p95 from a small sample is noisy.
