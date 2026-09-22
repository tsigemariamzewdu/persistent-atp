# Relationship to the original MORK FFI benchmark

This is a redesigned shared comparison suite derived from the original FFI
benchmark, not the unchanged original experiments run on three systems.
Experiment numbers belong to a suite: current E1 is not original E1, and
current E5 does not measure original E5's commit path.

The reference is the local `mork-ffi` branch and matching `upstream/mork-ffi`
reference at commit `20ce55b97a396a384346a33b85493768fde5a89e`. Its source defines
**seven experiments, E1–E7**. This comparison was checked against the code,
including `mork/bench/experiments.py`, `workload.py`, `harness.py`, and
`mork/backend/view.py` at that commit. For example:

```sh
git show 20ce55b97a396a384346a33b85493768fde5a89e:mork/bench/experiments.py
```

## Experiment mapping

| Original experiment | Current counterpart | What is retained or changed |
|---|---|---|
| E1: unrelated proofs versus query time | **E3** | Same question; different target/background sizes and three common graph reads. |
| E2: target-proof growth | **E2** | Same question; fixes the selected node and exact answers, changes sizes, and replaces the revision read with a field overwrite. |
| E3: individual operation costs | **E1** | Same category; common graph contracts, different adapter paths, added reads/removal, and restoration between mutations. |
| E4: minimal native FFI match/add calls | No equivalent full experiment | Current E1 includes a missing-node lookup through each complete integration. It is not a pure FFI-overhead test. |
| E5: `CommitGate.commit()` through MemoryView versus MorkView | **Deferred** | Current E5 is a dependency query. It does not replace commit-gate coverage. |
| E6: journal replay through `CommitGate.catch_up()` | **E6**, adapted | Common operation-history projection rebuild; different execution boundary, history units, and timing units. |
| E7: peak memory during load and removal | **Deferred** | No current memory measurement. |
| No original frontier experiment | **E4**, added | Previously explored as Q1; now varies candidate count and eligibility. |
| No original dependency-impact experiment | **E5**, added | Previously explored as Q2; now includes stars, chains, and reconvergent diamonds. |

## The FFI transport is retained; the graph adapter changed

Current [_ffi_transport.py](../backends/_ffi_transport.py) is byte-for-byte identical to the
original `mork/backend/ffi.py`. However, the current FFI column executes
benchmark-specific [MorkBackend](../backends/mork_ffi.py), not the original `MorkView`.
Calling both columns "MORK FFI" does not make them the same graph adapter.

The following differences affect measured work:

- Original incoming and outgoing reads both queried forward `edge` atoms.
  Current incoming reads use a maintained destination-first `rev-edge` atom.
  Both current MORK integrations use this representation, and timed edge
  mutations maintain both forward and reverse atoms.
- Original node and edge creation used general replacement/upsert paths,
  including lookups before writes. Current create/insert cases have checked
  absent-entity/field preconditions and directly add the required atoms.
- Original edge results included an edge-field dictionary and performed field
  retrieval for each returned edge. The common result contains edge ID,
  relationship type, source, and destination; edge fields are outside its scope.
- Original fixtures used `FormalState` nodes with `description`, `status`, and
  `kind` fields, and seeded random-parent `CHILD_OF` edges. Current fixtures use
  `State`, `Move`, or `Claim` nodes, committed-layer membership, and
  `PROPOSES`, `SUPPORTS`, or `DEPENDS_ON` edges. E1–E3 use `status` and `depth`.

These changes make the current logical workloads comparable across the three
integrations. They also mean the historical and current FFI times are not a
controlled before/after measurement of MORK engine speed. The old and new
reports additionally differ in machine, runtime, and measurement protocol.

## Changes to the retained questions

### Original E1 → current E3: unrelated proofs

| Detail | Original | Current |
|---|---|---|
| Target proof | 50 nodes | 100 nodes |
| Nodes per background proof | 25 | 100 |
| Background nodes | 0 / 500 / 2,500 / 10,000 / 25,000 | 0 / 1,000 / 10,000 |
| Operations | Node, outgoing, incoming, projected revision | Node, outgoing, incoming |
| Fixture progression | Add proofs within one experiment process | Fresh fixture per case/backend/trial |

The question is preserved, but the current sweep covers a smaller maximum
background population. Projected-revision reads are excluded because the shared
contract describes graph operations rather than gate bookkeeping.

### Original E2 → current E2: target-proof growth

Original sizes were 100 / 500 / 2,500 / 10,000 nodes. The selected node changed
to `nodes // 2` at each size. Its identity and incoming answer count were not
held fixed. Current sizes are 100 / 1,000 / 10,000, always querying `n1` with two
fields and exactly one incoming and one outgoing edge. This controls answer
size as well as target identity. Current E2 also substitutes an existing-field
overwrite for the original projected-revision read.

### Original E3 → current E1: individual operations

Original E3 began with 2,000 nodes and measured eight operations: node read,
outgoing read, node creation, field insertion, field overwrite, edge insertion,
projected-revision read, and projected-revision write. Current E1 begins with
1,000 nodes. It retains six graph-operation categories, adds missing-node,
incoming-edge, and edge-removal cases, and excludes both revision operations.

**The old mutations were already genuine.** They used unique IDs, unique field
names, and changing counter values. Their fixtures grew as mutations ran.
Current mutations are checked and reversed outside timing, keeping the starting
graph fixed for each sample. This is a change in workload control, not a claim
that original E3 accidentally measured repeated no-ops. Original E4's repeated
identical-atom add was an intentional low-level boundary/deduplication probe.

### Original E6 → current E6: replay versus projection rebuild

Original E6 populated `JournalStore(":memory:")` through legal proposals, then
timed `CommitGate.catch_up()` at 100 / 1,000 / 5,000 journal events. It collected
one observation per size and reported milliseconds per replayed event, with
total replay time in a note. An event can contain multiple graph operations.
Despite its recovery title, it did not kill and restart a process or measure
disk-journal recovery.

Current E6 applies a common list of node creations, edge additions, field
overwrites, and edge removals to an empty graph. The cases contain
215 / 2,150 / 21,500 logical operations, creating 100 / 1,000 / 10,000 nodes.
It plans five fresh trials per backend and reports **microseconds per complete
rebuild**. PeTTa includes executable-journal generation and runtime
parsing/application; the timing components are retained in trial metadata.

Current E6 does not execute `CommitGate.catch_up()`, proposal validation,
journal append, leases/fencing, or projected-revision advancement. It does not
test crashes or durable recovery. It retains the broad question of rebuilding
queryable graph state, with a deliberately narrower shared boundary.

## Coverage added and coverage deferred

Current E4 finds eligible moves for a specified state. It varies candidate
count and 10% / 50% / 90% eligibility. Current E5 finds claims affected by a
refuted dependency root. It varies claim count and graph shape: star, chain,
and bounded-depth reconvergent diamond. Both return unique IDs and measure
queries, not execution of moves or writing taint status.

Original E5 is still useful: it exercised the full commit gate with the same
proposal sequence against dictionaries and MORK, including validation, leases,
journal operations, projection, and revision handling. Its in-memory journal
did not measure disk durability. Restoring that question across all three
integrations requires a common commit path and acknowledgement boundary. The
current Python dictionary model checks correctness only; its performance is
not included in the three-backend tables.

Original E7 is also a coverage gap. A comparable memory study must account for
the Neo4j server as well as client/runtime processes and distinguish current
memory from peak RSS. Peak RSS does not fall after deletion, so that statistic
alone cannot establish reclamation or absence of a long-term memory leak.

Deferring these experiments keeps the shared graph contract explicit. It does
not make commit latency, FFI diagnostics, or memory measurements obsolete.

## Measurement protocol changes

| Detail | Original suite | Current shared suite |
|---|---|---|
| Isolation | Worker process per experiment; size sweeps share it | Worker per case/backend/trial |
| Usual read/operation repetitions | Five warm-ups, 50 timed calls | One preflight, three warm-ups, 30 timed calls, five trials |
| Reported central statistic | Median of calls in one run | Median of trial medians |
| Correctness | Generic timer discards returned values; some experiments check their own outcomes | Common oracle, exact answers, mutation readback/restoration, full final graph/index checks |
| Failures and unfinished work | Original experiment reporting | Explicit timeout/error, pending, and preliminary result labels |

Original E4 used 100 measured calls in its full configuration; E5 used 300
proposals per backend, including 10 warm-ups; E6 had one observation per size;
E7 reported memory. Current E6 separately uses one rebuild per trial without
operation warm-ups. Both suites use elapsed-time clocks for their native FFI
measurements; the original FFI report must not be confused with the intermediate
ordinary-PeTTa CPU-time reports retained in [the archive](../archive/README.md).

## How to describe the change in a report or PR

> This work derives a shared graph-operation benchmark from the original MORK
> FFI suite. It retains the questions of primitive operation cost, growth within
> a proof, and growth of unrelated proofs; adds frontier and dependency-impact
> queries; and adapts journal replay into a common projection-rebuild workload.
> Commit-gate latency and memory remain separate follow-up work. Experiment IDs,
> fixtures, adapter paths, indexes, and timing boundaries have changed, so the
> historical numbers are not direct before/after comparisons.

The current [results report](../results.md) describes a frozen partial evaluation.
The original benchmark remains available at the pinned Git revision. The
[archived exploratory runner](../archive/README.md) is the intermediate PeTTa
runner, not an exact copy of the original FFI suite.
