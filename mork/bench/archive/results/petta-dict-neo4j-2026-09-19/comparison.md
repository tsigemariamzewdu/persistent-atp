# PeTTa / Python dict / Neo4j elapsed-time comparison

Median microseconds per call, from batches. Neo4j includes client sessions, managed transactions, Bolt transport, server execution, and result conversion. PeTTa runs inside its persistent child process; process startup/loading are excluded.

| Experiment | Operation | Scale | PeTTa runtime | PeTTa µs | Dict µs | Neo4j µs | Neo4j / PeTTa | Neo4j / dict |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| E1 | node | 0 | petta-space | 1.273 | 0.117 | 4310.872 | 3386.59× | 36813.59× |
| E1 | incoming-edges | 0 | petta-space | 1.771 | 0.390 | 3512.012 | 1982.65× | 9008.62× |
| E1 | outgoing-edges | 0 | petta-space | 1.500 | 0.101 | 2957.982 | 1972.25× | 29265.22× |
| E1 | node | 250 | petta-space | 1.811 | 0.279 | 2748.700 | 1517.55× | 9836.99× |
| E1 | incoming-edges | 250 | petta-space | 1.551 | 0.153 | 2698.837 | 1739.95× | 17662.54× |
| E1 | outgoing-edges | 250 | petta-space | 1.615 | 0.109 | 2453.182 | 1518.65× | 22429.09× |
| E1 | node | 1000 | petta-space | 1.275 | 0.232 | 2450.353 | 1922.37× | 10574.40× |
| E1 | incoming-edges | 1000 | petta-space | 1.559 | 0.137 | 2891.088 | 1854.48× | 21133.68× |
| E1 | outgoing-edges | 1000 | petta-space | 1.653 | 0.117 | 2080.840 | 1258.50× | 17803.98× |
| E1 | node | 5000 | petta-space | 1.309 | 0.201 | 2879.969 | 2199.71× | 14362.14× |
| E1 | incoming-edges | 5000 | petta-space | 1.545 | 0.279 | 2689.840 | 1741.42× | 9636.68× |
| E1 | outgoing-edges | 5000 | petta-space | 2.606 | 0.115 | 2984.930 | 1145.47× | 25944.63× |
| E2 | node | 50 | petta-space | 1.426 | 0.118 | 2903.889 | 2035.92× | 24583.18× |
| E2 | incoming-edges | 50 | petta-space | 1.725 | 0.269 | 2019.856 | 1170.86× | 7520.64× |
| E2 | outgoing-edges | 50 | petta-space | 3.477 | 0.101 | 2019.811 | 580.90× | 19914.33× |
| E2 | node | 250 | petta-space | 3.442 | 0.244 | 2252.705 | 654.50× | 9250.41× |
| E2 | incoming-edges | 250 | petta-space | 3.376 | 0.134 | 1775.765 | 525.97× | 13279.23× |
| E2 | outgoing-edges | 250 | petta-space | 19.923 | 0.170 | 1770.904 | 88.89× | 10430.89× |
| E2 | node | 1000 | petta-space | 1.320 | 0.160 | 2076.261 | 1572.95× | 13011.19× |
| E2 | incoming-edges | 1000 | petta-space | 1.913 | 0.137 | 1640.191 | 857.50× | 12007.25× |
| E2 | outgoing-edges | 1000 | petta-space | 32.715 | 0.106 | 2689.797 | 82.22× | 25477.59× |
| E4 | empty-match | 0 | petta-space | 350.776 | 0.194 | 2227.344 | 6.35× | 11460.48× |
| E4 | empty-match | 50 | petta-space | 182.464 | 0.225 | 1694.871 | 9.29× | 7522.73× |
| E4 | empty-match | 250 | petta-space | 123.265 | 0.222 | 1631.383 | 13.23× | 7335.36× |
| E4 | empty-match | 1000 | petta-space | 122.415 | 0.272 | 1903.337 | 15.55× | 7003.35× |
| Q1 | frontier-for-state | 50 | petta-space | 544.870 | 13.698 | 4312.044 | 7.91× | 314.79× |
| Q1 | frontier-for-state | 250 | petta-space | 2737.711 | 73.935 | 10585.995 | 3.87× | 143.18× |
| Q1 | frontier-for-state | 1000 | petta-space | 10781.505 | 384.666 | 33634.095 | 3.12× | 87.44× |
| Q2 | taint-cone | 50 | petta-space | 458.274 | 35.774 | 2045.121 | 4.46× | 57.17× |
| Q2 | taint-cone | 250 | petta-space | 2072.507 | 140.064 | 2817.962 | 1.36× | 20.12× |
| Q2 | taint-cone | 1000 | petta-space | 8932.785 | 689.132 | 4012.649 | 0.45× | 5.82× |

Ratios above 1 mean Neo4j took longer; below 1 mean Neo4j was faster. `petta-space` does not measure MORK. All clocks in this report are monotonic elapsed time; do not divide these numbers by the older CPU-time results.

PeTTa reads a monotonic clock through its Python bridge, twice per batch. The loop/bridge/timer overhead is retained and amortized across the batch. Reported p95 values in JSON are percentiles of batch means, not individual-request p95.

Q1 uses the public Neo4jAdapter.eligible_frontier() (proof-wide, sorted full move records); Q2 uses Neo4jAdapter.taint_cone() (IDs). Both match the one-state/refuted-root fixtures, but differ from MeTTa for arbitrary inputs: MeTTa Q1 is state-specific, and MeTTa Q2 checks the root status. Exact fixture result IDs are checked before timing.

Node/edge/empty lookups use equivalent Cypher through the adapter transaction layer because the public adapter has no matching generic Move/edge read API. E4 is an absent node ID in Neo4j, versus an absent atom relation in PeTTa/dict; treat it as an empty-result-path comparison, not identical predicates.

Neo4j stores equivalent logical nodes/relationships using its native property graph and normal schema indexes. Fixture loading is bulk Cypher outside timing. `atoms` in JSON is the common projected-input atom count, not the count of physical Neo4j records; physical fixture node/relationship counts are also saved.

Each Neo4j case uses unique proof IDs plus an ownership tag, then verifies cleanup. Other database contents remain present and may affect performance. Repeated queries are warm-cache measurements. No isolated-server CPU or memory comparison is made.

E3 (atom add/remove/check cycle) and L1 (MeTTa parsing/loading) are omitted because the adapter has no equivalent operation with the same transactional/serialization boundary. Live commit, durability, recovery, generic rule evaluation, and concurrent load are not compared.
