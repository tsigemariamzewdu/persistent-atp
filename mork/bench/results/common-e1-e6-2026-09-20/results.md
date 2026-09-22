# PTPS graph benchmarks: E1–E6

This report evaluates **MORK through Python FFI**, **MORK through PeTTa**, and **Neo4j** using the same logical workloads and output contracts. Ordinary PeTTa space and the Python correctness oracle are not measured backends.

The main question is: **How much time does each graph implementation take to perform the operations needed by PTPS, and how does that cost change as the stored graph grows?** Each implementation receives the same logical graph and must return the same information or produce the same state change. The two MORK routes share the same native library; their access and evaluation paths differ. Neo4j uses native nodes, properties, and relationships through the project's managed transaction adapter.

The six experiments cover individual reads and mutations (E1), growth within the queried proof (E2), growth of unrelated proofs (E3), eligible-move queries (E4), dependency-impact queries (E5), and rebuilding a graph from an operation history (E6). These controlled, synthetic workloads measure the implemented graph operations. They do not measure the time to prove a theorem or execute the complete PTPS search loop.

Saved runner status: **running**. Started 2026-09-20T18:42:49.779597+00:00. This is the last recorded status, not a live-process check.

Target configuration: 5 independent trials per case/backend; 30 measured calls after 3 warm-ups per trial; 120 seconds maximum for an entire trial including setup and validation. E6 runs one empty-projection rebuild per independent trial with no operation warm-up.

Tables show **median microseconds per logical operation for E1–E5, and per complete rebuild for E6** (median of trial medians). A timeout/error has no invented timing and stops further repetitions of that case/backend. Timeouts bound the complete trial, not necessarily a single query. A preliminary cell includes its completed/target trial count; pending means a selected workload has no recorded trial yet. Not selected means that backend was excluded from this run. Raw single-call timings, pooled p95, and trial ranges are in the JSON artifacts.

## Runtime identity and measurement boundary

- Python 3.12.12; platform Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.35.
- MORK library SHA256: `c5eef6d6284479575523225a0a086937d92aab5ea218d277234a0933472372de`. Both MORK paths preload this identical binary.
- The isolated PeTTa bridge has documented flush-registration and conjunctive-match compatibility patches. Its ordinary-space fallback is rejected. See [runtime manifest](runtime/source-versions.json) and [patch](runtime/runtime-compatibility.patch).
- Each operation returns a fully materialized common result. Setup, graph loading, checking and restoration are outside the timer. Neo4j includes native managed transaction/transport and commit acknowledgement; MORK mutations include index updates and read-visible completion. These are not equal durable-commit guarantees.
- PeTTa clocks are read through its Python bridge; that timer overhead remains. Timings use monotonic elapsed time, not the historical CPU-time measurements.
- Field/edge mutation fixtures are restored outside timing and checked to prevent duplicate or no-op measurements. New MORK processes isolate the process-wide native space. Neo4j fixtures have unique ownership and proof namespaces and verified cleanup.
- Frontier returns state-scoped unique move IDs with mixed eligibility; taint checks a refuted root and returns unique dependent claim IDs. The two MORK paths use identical node/field/layer/edge/rev-edge atom shapes.
- FFI frontier joins and dependency traversal execute in Python over native MORK matches. PeTTa evaluates the existing MeTTa rules with real MORK lookups. Neo4j uses matching native Cypher through the adapter transaction layer. These are integration implementations, not isolated engine timings.

## Results

### E1 — Individual graph reads and genuine mutations

**Purpose.** E1 establishes the elapsed time of one basic graph operation at a fixed graph size. It separates four reads from five mutations so their costs can be compared individually; graph-growth effects are examined in E2 and E3.

**Workload.** Every case starts from the same graph containing **1,000 nodes and 1,000 edges** in one proof. One State node (`n0`) proposes 999 Move nodes through `PROPOSES` edges. One additional `SUPPORTS` edge connects `n1` to `n2`. Every node initially has `status=open`; `n0` has `depth=0` and the Move nodes have `depth=1`. The table's scale and node/edge counts describe this starting graph.

**Read cases.** `E1_node` retrieves `n1`'s ID, label, and both fields; `E1_missing_node` looks up an absent ID and returns `None`. `E1_incoming` returns the single `PROPOSES` edge from `n0` to `n1`, and `E1_outgoing` returns the single `SUPPORTS` edge from `n1` to `n2`. Both edge reads return complete records containing the edge ID, relationship type, source, and destination.

**Mutation cases.** `E1_create_node` creates a new Move with `status=open` and `depth=1`; `E1_insert_field` adds the absent field `score=7` to `n1`; `E1_overwrite_field` changes `n1.status` from `open` to `leased`; `E1_add_edge` creates a new `SUPPORTS` edge from `n1` to `n3`; and `E1_remove_edge` removes the existing `PROPOSES` edge `e1` from `n0` to `n1`. After each mutation, its effect is checked and an inverse operation restores the original graph outside the timer. Each sample therefore performs a real change rather than repeating an insertion or deletion that no longer changes the graph.

**Reading the table.** Each value measures one operation on the already loaded graph, including query evaluation and construction of the answer, or mutation work and completion. MORK edge mutations maintain forward and reverse atoms; PeTTa flushes queued writes; Neo4j includes its managed transaction and transport. Startup, fixture loading, benchmark correctness checks, restoration, and cleanup are excluded. These are sequential, warm repeated operations with the repetition counts and median calculation stated above; they do not measure cold-cache access or concurrent throughput.

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E1_node | 1000 | 1,000 / 1,000 | 49.09 | 139.71 | 2,045.02 |
| E1_missing_node | 1000 | 1,000 / 1,000 | 14.19 | 41.49 | 2,091.46 |
| E1_incoming | 1000 | 1,000 / 1,000 | 31.27 | 95.32 | 3,949.54 |
| E1_outgoing | 1000 | 1,000 / 1,000 | 202.03 | 252.30 | 4,978.72 |
| E1_create_node | 1000 | 1,000 / 1,000 | 44.66 | 64.63 | 6,058.48 |
| E1_insert_field | 1000 | 1,000 / 1,000 | 27.26 | 41.25 | 6,817.40 |
| E1_overwrite_field | 1000 | 1,000 / 1,000 | 59.33 | 124.04 | 7,377.87 |
| E1_add_edge | 1000 | 1,000 / 1,000 | 43.05 | 64.73 | 8,744.53 |
| E1_remove_edge | 1000 | 1,000 / 1,000 | 260.23 | 331.48 | 12,168.80 |

### E2 — Growth within the target proof, with fixed-size answers

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E2_node_100 | 100 | 100 / 100 | 75.14 | 210.86 | 4,230.63 |
| E2_incoming_100 | 100 | 100 / 100 | 36.46 | 113.98 | 3,638.77 |
| E2_outgoing_100 | 100 | 100 / 100 | 55.13 | 119.20 | 3,350.41 |
| E2_overwrite_field_100 | 100 | 100 / 100 | 65.85 | 162.90 | 6,353.35 |
| E2_node_1000 | 1000 | 1,000 / 1,000 | 60.19 | 175.49 | 2,593.71 |
| E2_incoming_1000 | 1000 | 1,000 / 1,000 | 36.09 | 114.13 | 2,499.52 |
| E2_outgoing_1000 | 1000 | 1,000 / 1,000 | 185.76 | 229.12 | 3,354.11 |
| E2_overwrite_field_1000 | 1000 | 1,000 / 1,000 | 116.55 | 148.86 | 6,674.68 |
| E2_node_10000 | 10000 | 10,000 / 10,000 | 68.21 | 224.04 | 4,602.00 |
| E2_incoming_10000 | 10000 | 10,000 / 10,000 | 35.56 | 95.79 | 3,334.71 |
| E2_outgoing_10000 | 10000 | 10,000 / 10,000 | 1,160.71 | 1,376.74 | 2,210.02 |
| E2_overwrite_field_10000 | 10000 | 10,000 / 10,000 | 78.98 | 159.87 | 6,164.48 |

### E3 — Growth of unrelated proofs, with an unchanged target proof

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E3_node_0 | 0 | 100 / 100 | 73.88 | 161.74 | 2,416.04 |
| E3_incoming_0 | 0 | 100 / 100 | 36.60 | 106.53 | 3,111.35 |
| E3_outgoing_0 | 0 | 100 / 100 | 68.03 | 138.13 | 3,422.97 |
| E3_node_1000 | 1000 | 1,100 / 1,100 | 96.36 | 262.21 | 3,750.25 |
| E3_incoming_1000 | 1000 | 1,100 / 1,100 | 42.79 | 113.57 | 3,117.22 |
| E3_outgoing_1000 | 1000 | 1,100 / 1,100 | 52.58 | 129.73 | 3,841.57 |
| E3_node_10000 | 10000 | 10,100 / 10,100 | 64.19 | 211.47 | 3,688.15 |
| E3_incoming_10000 | 10000 | 10,100 / 10,100 | 36.29 | 109.93 | 3,909.34 |
| E3_outgoing_10000 | 10000 | 10,100 / 10,100 | 51.31 | 130.16 | 3,636.77 |

### E4 — Eligible frontier queries, varying candidates and selectivity

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E4_frontier_100_10pct | 100 | 101 / 100 | 1,458.09 | 75,166.68 | 3,639.98 |
| E4_frontier_100_50pct | 100 | 101 / 100 | 1,089.69 | 76,605.07 | 2,548.02 |
| E4_frontier_100_90pct | 100 | 101 / 100 | 1,406.13 | 73,504.73 | 4,050.78 |
| E4_frontier_1000_10pct | 1000 | 1,001 / 1,000 | 14,668.62 | 1,094,183.96 | 7,147.82 |
| E4_frontier_1000_50pct | 1000 | 1,001 / 1,000 | 12,877.01 | 1,008,956.67 | 6,654.68 |
| E4_frontier_1000_90pct | 1000 | 1,001 / 1,000 | 13,536.08 | 980,153.58 | 9,384.14 |
| E4_frontier_10000_10pct | 10000 | 10,001 / 10,000 | 140,207.38 | timeout | 37,227.44 |
| E4_frontier_10000_50pct | 10000 | 10,001 / 10,000 | 125,718.31 | timeout | 43,321.11 |
| E4_frontier_10000_90pct | 10000 | 10,001 / 10,000 | 135,341.79 | timeout | 51,250.93 |

### E5 — Dependency impact on stars, chains, and reconvergent DAGs

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E5_taint_star_100 | 100 | 100 / 99 | 1,043.66 | 60,073.70 | 4,569.56 |
| E5_taint_chain_100 | 100 | 100 / 99 | 1,148.72 | 2,574,391.70 | 4,611.16 |
| E5_taint_diamond_100 | 100 | 100 / 196 | 1,182.30 | 116,199.01 | 2,670.75 |
| E5_taint_star_1000 | 1000 | 1,000 / 999 | 7,253.31 | 729,697.79 | 5,187.01 |
| E5_taint_chain_1000 | 1000 | 1,000 / 999 | 10,241.49 | timeout | 9,387.36 |
| E5_taint_diamond_1000 | 1000 | 1,000 / 1,996 | 15,986.52 | timeout | 10,345.62 |
| E5_taint_star_10000 | 10000 | 10,000 / 9,999 | 117,531.11 | timeout | 55,697.23 |
| E5_taint_chain_10000 | 10000 | 10,000 / 9,999 | 92,021.18 | timeout | 48,831.52 |
| E5_taint_diamond_10000 | 10000 | 10,000 / 19,996 | 160,789.09 (preliminary; 2/5 trials) | timeout | 50,832.79 (preliminary; 2/5 trials) |

### E6 — Rebuild a queryable graph from a common operation journal

| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
| --- | ---: | ---: | ---: | ---: | ---: |
| E6_rebuild_100 | 100 | 100 / 95 | 7,826.13 | 77,341.67 | 1,083,288.80 |
| E6_rebuild_1000 | 1000 | 1,000 / 950 | 108,737.42 | 1,196,197.69 | 15,916,067.64 |
| E6_rebuild_10000 | 10000 | 10,000 / 9,500 | pending | pending | pending |

E6 reports **total rebuild time**, not per-event latency. Journal counts: 100 created nodes → 215 operations, 1,000 created nodes → 2,150 operations, 10,000 created nodes → 21,500 operations. PeTTa total adds generation of its executable journal to runtime import/parse/application time; the components are retained in trial metadata. This is empty-projection rebuild from prevalidated history, not process crash recovery.

## Validation and limitations

704 successful, fully checked trials; 8 unsuccessful trials. Successful read trials validate returned values against an independent oracle. Successful mutation trials verify changed state and restoration; complete final graphs and MORK reverse indexes are also checked.

This is a sequential, warm-operation evaluation on one machine; independent trials do not constitute a hardware population or confidence interval. Frontier result count changes with eligibility. Dependency graphs include direct stars, long chains, and bounded-depth reconvergent DAGs; all non-root claims are affected. Graph sizes and answer sizes are recorded, and the entire workload grid is retained even when a backend fails.

Neo4j retains its normal indexes and native durability costs. Other data may exist on that server; this is not isolated-server throughput. Memory reclamation, durable PTPS commits, process restart, concurrent load, and theorem-proving success are not measured.

### Unsuccessful trials

| Case | Backend | Status | Detail |
| --- | --- | --- | --- |
| E5_taint_chain_1000 | mork-petta | timeout | Whole trial exceeded 120s |
| E5_taint_diamond_1000 | mork-petta | timeout | Whole trial exceeded 120s |
| E4_frontier_10000_10pct | mork-petta | timeout | Whole trial exceeded 120s |
| E4_frontier_10000_50pct | mork-petta | timeout | Whole trial exceeded 120s |
| E4_frontier_10000_90pct | mork-petta | timeout | Whole trial exceeded 120s |
| E5_taint_star_10000 | mork-petta | timeout | Whole trial exceeded 120s |
| E5_taint_chain_10000 | mork-petta | timeout | Whole trial exceeded 120s |
| E5_taint_diamond_10000 | mork-petta | timeout | Whole trial exceeded 120s |

## Reproduction and evidence

Detailed definitions and per-experiment instructions: [METHODOLOGY.md](../../docs/METHODOLOGY.md).

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench --repeats 5 --samples 30 --warmup 3 --timeout 120 --output-dir mork/bench/results/common-e1-e6-2026-09-20
```

- [Individual trial records and samples](trials.json)
- [Aggregated medians, pooled p95, and trial ranges](summary.json)
- [Environment, command, source hashes and run status](environment.json)
- [Measured benchmark source](measured-source/) preserves the files identified by the recorded source hashes.
- Generated scripts, case inputs and worker logs are retained locally in `artifacts/` (excluded from Git).
