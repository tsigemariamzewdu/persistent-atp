# Neo4j adapter

The adapter projects proof graphs into Neo4j and provides graph operations,
frontier queries, dependency queries, and taint propagation. Connection settings
come from `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE` in the
environment or repository `.env` file.

## Performance benchmarks

The [shared E1–E6 benchmark](../mork/bench/README.md) compares **MORK FFI,
MORK through PeTTa, and Neo4j** using identical logical graphs and answer
contracts. From the repository root, after preparing both MORK integrations
and the Neo4j service:

```sh
PYTHONPATH=src:. .venv/bin/python -m mork.bench --backend all \
  --repeats 5 --samples 30 --warmup 3 --timeout 120 \
  --output-dir /tmp/ptps-e1-e6
```

See the [frozen partial results report](../mork/bench/results.md) and
[methodology](../mork/bench/docs/METHODOLOGY.md) for timings and interpretation.
Neo4j uses equivalent native Cypher through the production adapter's managed
transaction layer, including transport and transaction acknowledgement. Its
normal indexes remain enabled. E6 uses one transaction per journal operation.

The runner creates uniquely owned fixture namespaces and verifies their cleanup.
Other database data remains present. E1–E6 cover reads, genuine mutations, growth,
frontier, dependency impact, and projection rebuild. They do not compare equivalent
durable PTPS commit protocols or memory use.

The [2026-09-19 exploratory report](../mork/bench/archive/results/petta-dict-neo4j-2026-09-19/README.md)
compared ordinary PeTTa space, indexed dictionaries, and Neo4j under older
definitions. It is retained as historical evidence, separate from the current
real-MORK evaluation.
