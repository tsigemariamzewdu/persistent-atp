# PTPS graph performance: MORK FFI, MORK–PeTTa, and Neo4j

This evaluation compares three implementations of the graph operations needed
by PTPS: **MORK accessed through Python FFI**, **MORK accessed through PeTTa and
MeTTa rules**, and **Neo4j accessed through the project's transaction adapter**.
Both MORK paths use real MORK and the same compiled native library. Python
dictionaries supply an independent correctness model; they are not a measured
backend in this evaluation.

The question is: **How much time does each graph implementation take to perform
PTPS graph operations, and how does that cost change as stored graphs grow?**
This report interprets application-operation costs. It does not measure the
time needed to prove a theorem or complete the entire PTPS search loop.

Each implementation receives the same logical graph and must return the same
information or produce the same state change. The experiments cover individual
reads and mutations (E1), growth within the queried proof (E2), growth of unrelated
proofs (E3), eligible-move queries (E4), dependency-impact queries (E5), and rebuilding
a graph from an operation history (E6). The graphs are controlled synthetic
workloads. Matching their logical contents makes the requested work comparable;
the implementations retain their own storage representations and execution paths.

This is a redesigned suite derived from the original FFI benchmark, whose
experiments were numbered E1–E7. The [old-to-new comparison](docs/COMPARISON.md)
records the renumbering, changed fixtures and adapters, added queries, and
deferred commit/memory experiments. Historical and current timings are not a
controlled before/after measurement of the same implementation.

**Evaluation status: frozen and incomplete.** The September 20–21 evaluation
contains **712 recorded trials: 704 successful and eight whole-trial timeouts**.
All E1–E3 combinations completed five trials. E4 has three PeTTa timeouts; E5 has
five PeTTa timeouts. E5's 10,000-claim diamond has only two of five successful
trials for FFI and Neo4j, so those two medians are preliminary. E6 at 10,000 nodes
has not been measured. Other numeric cells have five successful trials.

Saved measurement values and raw trial records are preserved. The generated
tables label the unmeasured E6 cells **pending** and the two partial E5 medians
**preliminary**, with their trial counts. The submitted earlier snapshot used
`not selected` for those E6 cells and did not identify the incomplete E5 counts;
those reporting labels were corrected without adding performance measurements.
The saved `running` metadata is not a live-process check. The restructured runner
cannot resume this older source layout; use a fresh output directory for a new
evaluation. See [the freeze record](results/common-e1-e6-2026-09-20/FROZEN.md).

## What was measured

| Experiment | Operation or question | Deliberately varied | Deliberately held fixed |
|---|---|---|---|
| **E1: Individual operations** | Nine basic reads and mutations | Operation type | 1,000-node graph |
| **E2: Target-proof growth** | Node/edge reads and field overwrite | Target proof: 100 / 1,000 / 10,000 nodes | Probe payload, node degree, and exact answers |
| **E3: Unrelated-proof growth** | Reads against an unchanged proof | Background: 0 / 1,000 / 10,000 nodes | 100-node target proof and exact answers |
| **E4: Eligible frontier** | Find eligible moves for one state | 100 / 1,000 / 10,000 candidates; 10% / 50% / 90% eligible | Eligibility rules and returned ID format |
| **E5: Dependency impact** | Find claims affected by a refuted root | 100 / 1,000 / 10,000 claims; star / chain / reconvergent diamond | Refuted-root condition and unique dependent-ID format |
| **E6: Projection rebuild** | Apply a common history to an empty graph | 215 / 2,150 / 21,500 journal operations | Operation semantics and final-graph validation |

E1 includes an existing-node record, a missing node, incoming edges, outgoing
edges, node creation, field insertion, field overwrite, edge insertion, and edge
removal. Returning a node means returning its ID, label, and fields on all three
implementations. Frontier and dependency queries return fully materialized
unique IDs, not full records in one backend and IDs in another.

Fixed answers make E2 and E3 informative: if the same one-edge answer becomes
more expensive, the slowdown cannot simply be attributed to returning more
edges. E2 grows the proof being queried; E3 grows other proofs. E4 deliberately
changes answer size separately from candidate count. E5 keeps the answer count
equal across shapes at a given size, but its graph and answer both grow across
sizes. These controls help explain which change is associated with a slowdown.

## Results and interpretation

The [saved E1–E6 tables](results/common-e1-e6-2026-09-20/results.md) list all
51 planned workload cases across all three backends, including timeouts and
unmeasured cases. The freeze note above qualifies incomplete cells.
E1–E5 cells measure one logical operation. E6 cells measure an entire rebuild.
The central statistic is the median of independent trial medians.

**E1 — individual graph reads and genuine mutations**

**Purpose.** E1 measures the elapsed time of one basic graph operation at a
fixed graph size. It separates four reads from five mutations to establish
their individual costs. E2 and E3 examine how those costs change with growth.

**Workload.** Each case starts with the same **1,000-node, 1,000-edge graph**
in one proof. One State node (`n0`) proposes 999 Move nodes through `PROPOSES`
edges. One additional `SUPPORTS` edge connects `n1` to `n2`. Every node initially
has `status=open`; `n0` has `depth=0`, and the Move nodes have `depth=1`.

**Read cases.** `E1_node` retrieves `n1`'s ID, label, and both fields, while
`E1_missing_node` looks up an absent ID and returns `None`. `E1_incoming` returns
the single `PROPOSES` edge from `n0` to `n1`; `E1_outgoing` returns the single
`SUPPORTS` edge from `n1` to `n2`. Each edge answer includes its ID, relationship
type, source, and destination.

**Mutation cases.** `E1_create_node` creates a new Move with `status=open` and
`depth=1`; `E1_insert_field` adds the absent field `score=7` to `n1`;
`E1_overwrite_field` changes `n1.status` from `open` to `leased`;
`E1_add_edge` adds a new `SUPPORTS` edge from `n1` to `n3`; and
`E1_remove_edge` removes the existing `PROPOSES` edge `e1` from `n0` to `n1`.
Each mutation is checked and then reversed outside the timer. The original
graph is restored before the next call, so every measured mutation makes a
real change. Node and edge counts describe the graph before each operation.

**Measurement.** The timer includes operation execution, construction of the
answer, and mutation completion. MORK maintains its forward/reverse atom
representation; PeTTa flushes queued writes; Neo4j includes managed transactions
and transport. Startup, graph loading, benchmark correctness checks, restoration,
and cleanup are excluded. All 27 E1 case/backend combinations completed five
trials, each with three warm-ups followed by 30 measured calls. The table shows
**microseconds per operation**, calculated as the median of the five trial
medians. There are 150 measured calls per cell. These are warm, sequential
operations; 1,000 microseconds equal one millisecond.

| Case | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |
|---|---:|---:|---:|
| E1_node | 49.09 | 139.71 | 2,045.02 |
| E1_missing_node | 14.19 | 41.49 | 2,091.46 |
| E1_incoming | 31.27 | 95.32 | 3,949.54 |
| E1_outgoing | 202.03 | 252.30 | 4,978.72 |
| E1_create_node | 44.66 | 64.63 | 6,058.48 |
| E1_insert_field | 27.26 | 41.25 | 6,817.40 |
| E1_overwrite_field | 59.33 | 124.04 | 7,377.87 |
| E1_add_edge | 43.05 | 64.73 | 8,744.53 |
| E1_remove_edge | 260.23 | 331.48 | 12,168.80 |

**Interpretation.** A small lookup may be dominated by adapter and
transport overhead, while a mutation also maintains the graph representation.
Across the nine measured operations, FFI had the lowest median and Neo4j the
highest. A full node read took **49.09 µs through FFI, 139.71 µs through PeTTa,
and 2,045.02 µs through Neo4j**: PeTTa took 2.85× and Neo4j 41.66× the FFI time.
Creating a node took 44.66, 64.63, and 6,058.48 µs, respectively. The larger
Neo4j costs include its managed transaction, transport, and native commit;
they are not an isolated comparison of in-memory storage operations.

**E2 — target-proof growth.** Compare the same operation from 100 to 10,000
nodes. Read this as a size trend within each implementation before comparing
absolute times between implementations. The selected answers remain identical.
Growing from 100 to 10,000 nodes increased the outgoing-edge lookup from
**55.13 to 1,160.71 µs through FFI (21.06×)** and **119.20 to 1,376.74 µs through
PeTTa (11.55×)**, although both still returned exactly one edge. Incoming reads
remained near their starting costs: FFI changed from 36.46 to 35.56 µs and
PeTTa from 113.98 to 95.79 µs. Neo4j outgoing reads showed no corresponding
growth, changing from 3,350.41 to 2,210.02 µs in this run. These are the
[recorded five-trial summaries](results/common-e1-e6-2026-09-20/summary.json).
The [MORK atom layout](results/common-e1-e6-2026-09-20/measured-source/mork_backend.py) puts an unknown edge ID before the
source in outgoing patterns, while the reverse-edge index puts the bound
destination near the beginning. This suggests a reason incoming queries resist
growth better; it is an inference from the schema, not a cause established by
profiling. The measured size trend alone does not prove an asymptotic complexity.

**E3 — unrelated-proof growth.** Compare the unchanged target proof with no
background data and with 10,000 background nodes. This tests interference from
other stored proofs; it is distinct from making the target proof itself larger.
With the target held at 100 nodes, adding 10,000 background nodes produced
these five-trial median changes. Values are **µs at 0 → 10,000 background nodes**;
parentheses show the final/start ratio.

| Target query | MORK FFI | MORK–PeTTa | Neo4j |
|---|---:|---:|---:|
| Node record | 73.88 → 64.19 (0.87×) | 161.74 → 211.47 (1.31×) | 2,416.04 → 3,688.15 (1.53×) |
| Incoming edges | 36.60 → 36.29 (0.99×) | 106.53 → 109.93 (1.03×) | 3,111.35 → 3,909.34 (1.26×) |
| Outgoing edges | 68.03 → 51.31 (0.75×) | 138.13 → 130.16 (0.94×) | 3,422.97 → 3,636.77 (1.06×) |

The MORK incoming probes stayed close to their starting values; node-record
latency rose by about 31% through PeTTa and 53% through Neo4j. Endpoint ratios
across all nine combinations ranged from 0.75× to 1.53×. This is a bounded
observation from the measured background sizes, not proof of constant-time
lookup; machine variation may also contribute to increases and decreases.

**E4 — frontier.** Compare candidate counts at the same eligibility percentage,
then percentages at the same candidate count. The first comparison grows both
search and output; the second keeps stored size fixed while changing the output.
At **50% eligibility**, the query returns 50, 500, or 5,000 unique move IDs.
The following values are **milliseconds per query**, with each numeric entry
the median of five successful trial medians.

| Candidates | Returned IDs | MORK FFI ms | MORK–PeTTa ms | Neo4j ms |
|---|---:|---:|---:|---:|
| 100 | 50 | 1.09 | 76.61 | 2.55 |
| 1,000 | 500 | 12.88 | 1,008.96 | 6.65 |
| 10,000 | 5,000 | 125.72 | timeout | 43.32 |

At 100 candidates, Neo4j took **2.34×** the FFI time. At 1,000 candidates,
FFI took **1.94×** the Neo4j time; at 10,000 it took **2.90×**. PeTTa took
**70.30×** the FFI time at 100 candidates and **78.35×** at 1,000. Growing
from 100 to 10,000 candidates increased FFI time by **115.37×** and Neo4j
time by **17.00×**. These observations compare the implemented query paths:
FFI joins native MORK matches in Python, PeTTa evaluates the MeTTa frontier
rules, and Neo4j evaluates Cypher. They do not isolate the storage engine
from query evaluation and integration costs.

Holding the graph at **1,000 candidates** gives the following eligibility
comparison, also in **milliseconds per query**:

| Eligible candidates | Returned IDs | MORK FFI ms | MORK–PeTTa ms | Neo4j ms |
|---|---:|---:|---:|---:|
| 10% | 100 | 14.67 | 1,094.18 | 7.15 |
| 50% | 500 | 12.88 | 1,008.96 | 6.65 |
| 90% | 900 | 13.54 | 980.15 | 9.38 |

Returning nine times as many IDs did not produce a ninefold time increase.
The 90%/10% time ratios were **0.92×** for FFI, **0.90×** for PeTTa, and
**1.31×** for Neo4j. Timings were not consistently increasing with eligibility;
the small decreases should not be interpreted as proof that returning more
answers makes queries faster. Changing eligibility changes filtering as well
as output, and trial variation also contributes.

All three PeTTa cases at 10,000 candidates reached the **120-second whole-trial
limit on their first attempt**, so further repeats were stopped. That limit
includes loading, one correctness call, three warm-ups, 30 measured calls, and
validation; it does **not** establish that one frontier query takes more than
120 seconds. These cases have zero successful trials and no accepted latency
or speed ratio. All other E4 cases completed five validated trials. Exact
statistics and trial ranges are in the
[recorded summaries](results/common-e1-e6-2026-09-20/summary.json).

**E5 — dependency impact.** Stars test many direct dependents; chains test
depth; diamonds test deduplication when two paths reach each leaf. At 10,000
claims the chain reaches depth 9,999, while the diamond stays at depth 2.
At 100 claims, each shape returns 99 IDs. PeTTa took **60.07 ms** for the star,
**2,574.39 ms** for the chain, and **116.20 ms** for the diamond: the chain cost
about 42.9 times the star despite the same returned-ID count. FFI took 1.04,
1.15, and 1.18 ms, respectively; Neo4j took 4.57, 4.61, and 2.67 ms. These
numeric cells each have five successful trials. The result exposes sensitivity
to graph shape in the current query implementations, not just answer size.

PeTTa completed the 1,000-claim star (729.70 ms), but its 1,000-claim chain and
diamond and all three 10,000-claim shapes reached the whole-trial deadline.
There is no accepted per-query latency for those five timeout cases. At 10,000
claims, FFI and Neo4j completed five trials for stars and chains. Their diamond
medians, **160.79 ms and 50.83 ms**, each contain only **two of five planned
trials** and remain preliminary in this frozen evaluation.

**E6 — rebuild.** The common history includes creation, overwrites, and removals.
Neo4j uses one managed transaction per journal operation. FFI applies each
operation through its native calls; PeTTa parses and evaluates its generated
operation file, flushing each operation. This measures the agreed replay policy,
not each engine's fastest possible bulk importer.
The following cells are **seconds per complete rebuild**, each based on five
successful trials. They are not seconds per journal operation.

| Created nodes | Journal operations | Final edges | MORK FFI s | MORK–PeTTa s | Neo4j s |
|---|---:|---:|---:|---:|---:|
| 100 | 215 | 95 | 0.00783 | 0.07734 | 1.08329 |
| 1,000 | 2,150 | 950 | 0.10874 | 1.19620 | 15.91607 |
| 10,000 | 21,500 | 9,500 | unmeasured | unmeasured | unmeasured |

PeTTa totals include executable-journal generation and runtime application;
those components remain in the individual trial records. The observed ordering
reflects this operation-by-operation replay policy and the integrations'
different transaction and durability costs. It does not establish the relative
speed of bulk importers or crash recovery.

For any completed matching row, a ratio is simply `time B / time A`. A ratio of
3 means B took three times as long for **that operation and workload**. Compare
matching statistics and units, and keep absolute times beside ratios. Do not
combine the six experiments into one overall speed multiplier or infer the same
multiplier for the complete theorem prover.

## How the measurements were collected

The measured machine was an Intel Core i5-1235U with 12 logical CPUs and about
7.6 GiB of memory, running Linux under WSL2. Python was 3.12.12 and Neo4j was
5.20. The [hardware record](results/common-e1-e6-2026-09-20/hardware.json),
[environment record](results/common-e1-e6-2026-09-20/environment.json), and
[runtime manifest](results/common-e1-e6-2026-09-20/runtime/source-versions.json)
preserve the configuration and native-library identity.

Each completed E1–E5 case/backend has **five independent trials**, with three
warm-up calls followed by 30 measured single calls per trial: 150 measured calls
in total. E6 performs one empty-projection rebuild per trial, without warm-ups.
Backend order rotates between trials. New MORK worker processes isolate native
state; Neo4j uses uniquely owned namespaces and verifies fixture cleanup.

The run began on **2026-09-20 UTC** and was interrupted after 686 recorded
trials. It resumed on **2026-09-21 UTC** with the same workload settings,
measured operation code, and native-library hash. Completed trials were retained;
the unfinished attempt was archived and restarted. Continuation details are
recorded in `environment.json`. Machine conditions may differ between these
execution periods, which limits cross-period scaling comparisons.

Monotonic elapsed-time clocks surround operation evaluation and construction of
the answer. Startup, initial fixture loading, correctness comparison, and cleanup
are excluded. Neo4j includes Bolt transport and managed transactions. PeTTa reads
its clock inside the runtime through a Python bridge; that timer overhead stays
in the result. E6 PeTTa totals add executable-journal generation to runtime
import, parsing, and application; components remain in individual trial metadata.

Every timed mutation changes the graph. Its effect is checked, an inverse
operation restores the original fixture outside timing, and restoration is
checked before the next timed call. Query answers are checked against the
independent oracle. Final snapshots check complete graphs and MORK reverse-edge
indexes, so returning quickly with an incomplete answer is not a passing result.

The deadline is **120 seconds for an entire trial**, including setup and
validation. A timeout is recorded separately from a completed timing and stops
further repetitions of that case/backend. It is not automatically a 120-second
lower bound on one query. Other workloads continue.

## What the comparison establishes

The common logical graph and answer contract make these useful comparisons of
PTPS integrations. The two MORK paths share their atom schema and indexes.
Their algorithms still differ: FFI combines native matches and traverses
dependencies in Python; PeTTa evaluates the existing MeTTa rules; Neo4j uses
equivalent Cypher through the transaction adapter. The isolated PeTTa bridge's
flush registration and conjunction support are recorded in the
[compatibility patch](results/common-e1-e6-2026-09-20/runtime/runtime-compatibility.patch).

For E5, the distinction is concrete: the FFI implementation discovers dependents
together using one traversal from the root, whereas the MeTTa rule asks whether
each claim reaches that root separately. Repeated traversal on chains is a
source-based explanation for higher cost; it is not a measured profiler
breakdown. Neo4j performs the query on the server; its physical execution plan
was not profiled.

The Neo4j benchmark reuses the production transaction machinery with adapted
queries. Its unchanged public frontier method returns proof-wide full records,
whereas this benchmark requires IDs for a specified state. Adapting that query
and the taint root checks is necessary to compare the same requested answers.

Neo4j's native transaction acknowledgement and MORK's in-memory, query-visible
mutation offer different durability guarantees. The write rows describe those
actual costs; they do not rank equivalent durable PTPS commits. Likewise, E6
rebuilds an empty projection from prevalidated history, without testing crashes,
journal discovery, or reopening an already durable database.

The scope is one machine, sequential callers, warm repeated operations, and
controlled synthetic committed graphs. There are no cycle, concurrency, memory,
or theorem-proving-success measurements. E5 affects every non-root claim; the
affected fraction is not independently varied. These limits identify the next
experiments needed before making broader deployment claims.

## Relationship to the earlier benchmarks and reproduction

The original FFI suite's unrelated-proof E1 becomes new E3, its growth E2 stays
E2, and its primitive-operation E3 becomes standardized E1. Its minimal-call E4
contributes the missing-node query to new E1. Frontier and dependency queries
become new E4 and E5 because they measure meaningful PTPS application work.
Original recovery E6 becomes precisely scoped projection rebuild. Original E5
commit-gate latency and E7 memory are deferred until their measurement contracts
are shared. [METHODOLOGY.md](docs/METHODOLOGY.md) explains each choice in detail.

Earlier 2026-09-19 reports used **ordinary PeTTa space**, sometimes Python
dictionaries and different timing boundaries. They are historical exploratory
results and are not evidence for the real MORK–PeTTa column in this evaluation.

Run the same logical configuration in a fresh output directory from the
repository root after following [setup and per-experiment instructions](README.md).
The active runner has been reorganized; its new output must be kept separate
from the frozen evaluation and must retain its own source hashes:

```sh
.venv/bin/python -m mork.bench --backend all \
  --repeats 5 --samples 30 --warmup 3 --timeout 120 \
  --output-dir /tmp/ptps-e1-e6-repeat
```

The [trial records](results/common-e1-e6-2026-09-20/trials.json) contain raw
single-call samples and validation status. The
[summary](results/common-e1-e6-2026-09-20/summary.json) contains medians, pooled
single-call p95, and the range of trial medians. These descriptive statistics
are not confidence intervals; five E6 observations give especially limited
information about tail latency. Exact generated programs and logs remain in
the evaluation's local `artifacts/` directory.

The [measured benchmark sources](results/common-e1-e6-2026-09-20/measured-source/)
match the hashes recorded when the run began. The
[application source record](results/common-e1-e6-2026-09-20/application-source.json)
also identifies the MeTTa rules and Neo4j adapter. The original source filenames
inside these evidence snapshots are intentional. The active code now separates
experiment definitions, execution, reporting, and backends, but that reorganization
does not alter or regenerate the saved measurements. New runs record the current
layout and cannot be appended to this frozen evaluation.
