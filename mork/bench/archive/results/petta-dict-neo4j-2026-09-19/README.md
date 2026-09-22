# PeTTa, indexed dictionaries, and Neo4j adapter

**This run compares ordinary PeTTa space, indexed Python dictionaries, and a live Neo4j adapter. MORK is not active in the current launcher and has no measured result here.**

Completed 2026-09-19T19:31:21.492885+00:00. All 17 workload cases and 31 three-way comparisons completed, producing 93 result rows. All query/graph-count checks passed, as did the 14 Python harness/baseline tests.

Neo4j server: 5.20.0 community; Python driver 6.3.0. The endpoint is loopback: True. CPU: 12th Gen Intel(R) Core(TM) i5-1235U.

Every benchmark fixture was cleaned up. Database node count before: **382**; after: **382**. Existing data was retained; these numbers do not claim the server was otherwise isolated.

## Results at 1,000 target nodes/claims

Median elapsed time per call, in microseconds. Ratio = Neo4j / PeTTa: above 1 means Neo4j took longer; below 1 means it was faster.

| Operation | PeTTa µs | Dict µs | Neo4j µs | Neo4j / PeTTa |
| --- | ---: | ---: | ---: | ---: |
| node | 1.320 | 0.160 | 2076.261 | 1572.95× |
| incoming-edges | 1.913 | 0.137 | 1640.191 | 857.50× |
| outgoing-edges | 32.715 | 0.106 | 2689.797 | 82.22× |
| frontier-for-state | 10781.505 | 384.666 | 33634.095 | 3.12× |
| taint-cone | 8932.785 | 689.132 | 4012.649 | 0.45× |

## Per-experiment results

- [E1: unrelated-proof growth](E1.md)
- [E2: target-proof growth](E2.md)
- [E4: empty-result queries](E4.md)
- [Q1: frontier queries](Q1.md)
- [Q2: taint-cone queries](Q2.md)
- [All 31 comparisons](comparison.md)

## What these numbers mean

Neo4j is measured through the real Python adapter: client session and managed transaction, Bolt request/response, database execution, and returned-record conversion are all included. PeTTa and dictionaries run queries in process with graph setup excluded. Neo4j therefore pays a per-request cost that in-process backends do not. This is an application-call comparison, not a comparison of isolated database algorithms or server CPU time.

The Q1 call is the production eligible_frontier method, which returns sorted full move records across a proof. MeTTa returns move IDs for one state; the fixture contains exactly one state, making the result sets equivalent. Q2 calls the production taint_cone method, which returns dependent claim IDs. Its API does not require a refuted root, whereas the MeTTa rule does; this fixture always has a refuted root. Python implements equivalent graph algorithms with adjacency indexes. Exact Neo4j frontier/taint ID sets are validated outside timing.

Generic node-label/edge reads use equivalent Cypher through the adapter transaction layer: the public adapter has no directly matching generic Move/edge read API. E4 compares empty-result paths, but the predicates differ (absent node ID in Neo4j; absent atom relation in PeTTa/dict). Do not generalize E4 to all misses.

Each row is based on 30 batches of 20 calls following 3 warm-up batches. Medians and p95 are calculated from per-call batch means. The JSON p95 is not an individual-request tail latency. All backends use monotonic elapsed clocks; PeTTa accesses its clock through the Python bridge, twice per batch. Loop, timer, and bridge overhead remain. The older CPU-time results are a different measurement and must not be mixed into these ratios.

These are warm repeated reads from one sweep, without parallel load. The comparison does not establish throughput, cold-start latency, memory cost, durability, or a universal backend slowdown. Equivalent logical fixtures are stored using each backend’s native indexes and representation; Neo4j physical node/edge counts differ from the projected atom count.

## Coverage and missing pieces

| Backend / operation | Status |
| --- | --- |
| Ordinary PeTTa space | Measured through petta file.metta |
| Python dict | Measured using indexed graph implementation |
| Neo4j adapter | Measured against the live server |
| MORK through PeTTa | Not measured: current launcher leaves mm2-exec unevaluated |
| Atom add/remove cycle (E3) | Omitted: no matching public adapter atom API / transaction boundary |
| Projection-file loading (L1) | Omitted: parsing MeTTa and constructing a property graph are different operations |
| Commit latency, persistence, recovery, concurrency, memory | Not measured |

## Reproduce

From the repository root, with Neo4j connection settings in .env/environment:

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench.compare_backends --allow-petta-space --output-dir mork/bench/results/petta-dict-neo4j-2026-09-19
```

For a MORK-through-PeTTa comparison, use a MORK-enabled launcher via --petta and omit --allow-petta-space. Keep results from that runtime separate. The recorded values here remain labelled petta-space.

## Evidence

- [Raw result rows](results.json)
- [Raw batch samples for all three backends](samples.json)
- [Environment, server version, timings, cleanup counts, source hashes](environment.json)
- [Repository/runtime context and adapter/rule source hashes](source-context.json)
- [14 passing tests](harness-tests.log)
- Generated PeTTa files and per-case logs remain locally in generated/, excluded from Git.
