"""Aggregate recorded timings and render result tables; never execute workloads."""
from __future__ import annotations

import math
import statistics
from .experiments import EXPERIMENTS

BACKENDS = ('mork-ffi', 'mork-petta', 'neo4j')


def summarize(samples: list[float]) -> tuple[float, float]:
    if not samples or any(not math.isfinite(x) or x < 0 for x in samples):
        raise ValueError("Missing, negative, or non-finite timing samples")
    ordered = sorted(samples)
    return statistics.median(ordered), ordered[math.ceil(len(ordered) * .95) - 1]


def aggregate(rows):
    groups = {}
    for row in rows:
        groups.setdefault((row['case'], row['backend']), []).append(row)
    result = []
    for (case, backend), trials in groups.items():
        ok = [row for row in trials if row['status'] == 'ok']
        failures = [row for row in trials if row['status'] != 'ok']
        item = {'case': case, 'experiment': trials[0]['experiment'], 'backend': backend,
                'successful_trials': len(ok), 'attempted_trials': len(trials),
                'status': failures[-1]['status'] if failures else 'ok'}
        if ok:
            medians = [r['median_us'] for r in ok]
            samples = [value for r in ok for value in r['samples_us']]
            item.update(median_us=statistics.median(medians),
                        pooled_p95_us=summarize(samples)[1],
                        trial_median_min_us=min(medians), trial_median_max_us=max(medians))
        result.append(item)
    return result


def report(cases, rows, metadata):
    summaries = aggregate(rows)
    index = {(r['case'], r['backend']): r for r in summaries}
    selected_backends = set(metadata.get('selected_backends',
                                         [r['backend'] for r in rows]))
    out = ['# PTPS graph benchmarks: E1–E6', '',
        'This report evaluates **MORK through Python FFI**, **MORK through PeTTa**, and **Neo4j** using the same logical workloads and output contracts. Ordinary PeTTa space and the Python correctness oracle are not measured backends.', '',
        'The main question is: **How much time does each graph implementation take to perform the operations needed by PTPS, and how does that cost change as the stored graph grows?** '
        'Each implementation receives the same logical graph and must return the same information or produce the same state change. '
        'The two MORK routes share the same native library; their access and evaluation paths differ. Neo4j uses native nodes, properties, and relationships through the project\'s managed transaction adapter.', '',
        'The six experiments cover individual reads and mutations (E1), growth within the queried proof (E2), growth of unrelated proofs (E3), '
        'eligible-move queries (E4), dependency-impact queries (E5), and rebuilding a graph from an operation history (E6). '
        'These controlled, synthetic workloads measure the implemented graph operations. They do not measure the time to prove a theorem or execute the complete PTPS search loop.', '',
        f'Saved runner status: **{metadata["status"]}**. Started {metadata["started_at"]}. '
        'This is the last recorded status, not a live-process check.', '',
        f'Target configuration: {metadata["repeats"]} independent trials per case/backend; '
        f'{metadata["samples"]} measured calls after {metadata["warmup"]} warm-ups per trial; '
        f'{metadata["timeout"]:g} seconds maximum for an entire trial including setup and validation. '
        'E6 runs one empty-projection rebuild per independent trial with no operation warm-up.', '',
        'Tables show **median microseconds per logical operation for E1–E5, and per complete rebuild for E6** (median of trial medians). '
        'A timeout/error has no invented timing and stops further repetitions of that case/backend. '
        'Timeouts bound the complete trial, not necessarily a single query. '
        'A preliminary cell includes its completed/target trial count; pending means a selected workload has no recorded trial yet. '
        'Not selected means that backend was excluded from this run. '
        'Raw single-call timings, pooled p95, and trial ranges are in the JSON artifacts.', '',
        '## Runtime identity and measurement boundary', '',
        f'- Python {metadata["python"]}; platform {metadata["platform"]}.',
        f'- MORK library SHA256: `{metadata.get("library_sha256", "unavailable")}`. Both MORK paths preload this identical binary.',
        '- The isolated PeTTa bridge has documented flush-registration and conjunctive-match compatibility patches. Its ordinary-space fallback is rejected. See [runtime manifest](runtime/source-versions.json) and [patch](runtime/runtime-compatibility.patch).',
        '- Each operation returns a fully materialized common result. Setup, graph loading, checking and restoration are outside the timer. Neo4j includes native managed transaction/transport and commit acknowledgement; MORK mutations include index updates and read-visible completion. These are not equal durable-commit guarantees.',
        '- PeTTa clocks are read through its Python bridge; that timer overhead remains. Timings use monotonic elapsed time, not the historical CPU-time measurements.',
        '- Field/edge mutation fixtures are restored outside timing and checked to prevent duplicate or no-op measurements. New MORK processes isolate the process-wide native space. Neo4j fixtures have unique ownership and proof namespaces and verified cleanup.',
        '- Frontier returns state-scoped unique move IDs with mixed eligibility; taint checks a refuted root and returns unique dependent claim IDs. The two MORK paths use identical node/field/layer/edge/rev-edge atom shapes.',
        '- FFI frontier joins and dependency traversal execute in Python over native MORK matches. PeTTa evaluates the existing MeTTa rules with real MORK lookups. Neo4j uses matching native Cypher through the adapter transaction layer. These are integration implementations, not isolated engine timings.', '',
        '## Results', '']
    for experiment, title in EXPERIMENTS.items():
        selected = [c for c in cases if c.experiment == experiment]
        if not selected:
            continue
        out.extend([f'### {experiment} — {title}', ''])
        if experiment == 'E1':
            size = selected[0].node_count
            out.extend([
                '**Purpose.** E1 establishes the elapsed time of one basic graph operation at a fixed graph size. '
                'It separates four reads from five mutations so their costs can be compared individually; graph-growth effects are examined in E2 and E3.', '',
                f'**Workload.** Every case starts from the same graph containing **{size:,} nodes and {selected[0].edge_count:,} edges** in one proof. '
                f'One State node (`n0`) proposes {size - 1:,} Move nodes through `PROPOSES` edges. '
                'One additional `SUPPORTS` edge connects `n1` to `n2`. Every node initially has `status=open`; '
                '`n0` has `depth=0` and the Move nodes have `depth=1`. The table\'s scale and node/edge counts describe this starting graph.', '',
                '**Read cases.** `E1_node` retrieves `n1`\'s ID, label, and both fields; `E1_missing_node` looks up an absent ID and returns `None`. '
                '`E1_incoming` returns the single `PROPOSES` edge from `n0` to `n1`, and `E1_outgoing` returns the single `SUPPORTS` edge from `n1` to `n2`. '
                'Both edge reads return complete records containing the edge ID, relationship type, source, and destination.', '',
                '**Mutation cases.** `E1_create_node` creates a new Move with `status=open` and `depth=1`; `E1_insert_field` adds the absent field `score=7` to `n1`; '
                '`E1_overwrite_field` changes `n1.status` from `open` to `leased`; `E1_add_edge` creates a new `SUPPORTS` edge from `n1` to `n3`; '
                'and `E1_remove_edge` removes the existing `PROPOSES` edge `e1` from `n0` to `n1`. '
                'After each mutation, its effect is checked and an inverse operation restores the original graph outside the timer. '
                'Each sample therefore performs a real change rather than repeating an insertion or deletion that no longer changes the graph.', '',
                '**Reading the table.** Each value measures one operation on the already loaded graph, including query evaluation and construction of the answer, '
                'or mutation work and completion. MORK edge mutations maintain forward and reverse atoms; PeTTa flushes queued writes; Neo4j includes its managed transaction and transport. '
                'Startup, fixture loading, benchmark correctness checks, restoration, and cleanup are excluded. '
                'These are sequential, warm repeated operations with the repetition counts and median calculation stated above; they do not measure cold-cache access or concurrent throughput.', '',
            ])
        out.extend([
            '| Case | Scale | Nodes / edges | MORK FFI µs | MORK–PeTTa µs | Neo4j µs |',
            '| --- | ---: | ---: | ---: | ---: | ---: |'])
        for case in selected:
            cells = []
            for backend in BACKENDS:
                value = index.get((case.key, backend))
                if value is None:
                    cells.append('pending' if backend in selected_backends else 'not selected')
                elif value['status'] == 'ok':
                    label = f'{value["median_us"]:,.2f}'
                    if value['successful_trials'] < metadata['repeats']:
                        label += f' (preliminary; {value["successful_trials"]}/{metadata["repeats"]} trials)'
                    cells.append(label)
                else:
                    cells.append(value['status'])
            out.append(f'| {case.key} | {case.scale} | {case.node_count:,} / {case.edge_count:,} | ' + ' | '.join(cells) + ' |')
        if experiment == 'E6':
            out.extend(['', 'E6 reports **total rebuild time**, not per-event latency. Journal counts: ' +
                ', '.join(f'{c.scale:,} created nodes → {len(c.journal):,} operations' for c in selected) +
                '. PeTTa total adds generation of its executable journal to runtime import/parse/application time; the components are retained in trial metadata. This is empty-projection rebuild from prevalidated history, not process crash recovery.'])
        out.append('')
    failed = [r for r in rows if r['status'] != 'ok']
    out.extend(['## Validation and limitations', '',
        f'{sum(r["status"] == "ok" for r in rows)} successful, fully checked trials; {len(failed)} unsuccessful trials. '
        'Successful read trials validate returned values against an independent oracle. Successful mutation trials verify changed state and restoration; complete final graphs and MORK reverse indexes are also checked.', '',
        'This is a sequential, warm-operation evaluation on one machine; independent trials do not constitute a hardware population or confidence interval. Frontier result count changes with eligibility. Dependency graphs include direct stars, long chains, and bounded-depth reconvergent DAGs; all non-root claims are affected. Graph sizes and answer sizes are recorded, and the entire workload grid is retained even when a backend fails.', '',
        'Neo4j retains its normal indexes and native durability costs. Other data may exist on that server; this is not isolated-server throughput. Memory reclamation, durable PTPS commits, process restart, concurrent load, and theorem-proving success are not measured.', ''])
    if failed:
        out.extend(['### Unsuccessful trials', '', '| Case | Backend | Status | Detail |', '| --- | --- | --- | --- |'])
        for r in failed:
            detail = str(r.get('error', '')).replace('|', '/').replace('\n', ' ')[:220]
            out.append(f'| {r["case"]} | {r["backend"]} | {r["status"]} | {detail} |')
    out.extend(['', '## Reproduction and evidence', '',
        f"Detailed definitions and per-experiment instructions: [METHODOLOGY.md](<{metadata.get('methodology_path', '../../docs/METHODOLOGY.md')}>).", '',
        '```sh', metadata['command'], '```', '',
        '- [Individual trial records and samples](trials.json)',
        '- [Aggregated medians, pooled p95, and trial ranges](summary.json)',
        '- [Environment, command, source hashes and run status](environment.json)',
        '- [Measured benchmark source](measured-source/) preserves the files identified by the recorded source hashes.',
        '- Generated scripts, case inputs and worker logs are retained locally in `artifacts/` (excluded from Git).', ''])
    return '\n'.join(out)
