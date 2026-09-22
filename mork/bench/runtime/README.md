# Reproduce the real MORK runtime

The benchmark uses **one compiled `libmork_ffi.so` for both MORK integrations**.
Python calls `rust_mork` through `ctypes`; PeTTa calls that same symbol through
its SWI-Prolog C bridge. PeTTa rule evaluation and conjunction handling occur
in Prolog. Neither route falls back to ordinary PeTTa space.

`measured-runtime.json` records the source commits, compiler versions, patch
hash, dependency-lock hash, and measured machine's library hash. `Cargo.lock`
pins the FFI crate's Rust dependency resolution. `compatibility.patch` records
the only runtime source changes. The native MORK/PathMap/Rust FFI sources were
not patched.

## Dependencies

Use a Linux build environment with:

- Python 3.10 or newer, Git, GNU patch, GCC, make, CMake, and pkg-config.
- Rust installed through rustup. The measured toolchain is
  `nightly-2026-02-21` (`rustc 1.95.0-nightly`, commit `0376d43d4`).
- SWI-Prolog with `library(janus)`, its development headers, and a working
  `pkg-config swipl` entry. The measured version was **9.3.33**. Janus must be
  able to import Python's `time` module; it provides the monotonic timer.
- Network access for the pinned source checkouts and Cargo dependencies, or
  already cached Cargo dependencies when building with `--offline`.

The selected MORK/PathMap configuration uses nightly Rust features and
jemalloc. Preloading the native library avoids its static-TLS allocation
failure when loaded after Python startup. The launcher handles preloading.

Check prerequisites before building:

```bash
rustup toolchain install nightly-2026-02-21 --profile minimal
swipl --version
pkg-config --cflags --libs swipl
swipl -q -g 'use_module(library(janus)), py_call(time:monotonic_ns(), T), writeln(T), halt'
```

The separate Neo4j service and Python Neo4j driver are described in the main
benchmark README; this directory prepares the two MORK integrations.

## Create a fresh runtime

Run from the repository root:

```bash
python3 scripts/setup-bench-runtime.py
```

The script creates this layout, checks out the exact commits in the manifest,
applies the compatibility patch, copies the committed lockfile, builds the
Rust library with `--release --locked`, and compiles the Prolog C bridge:

```text
.bench-runtime/
├── MORK/
├── PathMap/
└── PeTTa/
    └── mork_ffi/
        ├── morklib.so
        └── target/release/libmork_ffi.so
```

The relative layout is required by the pinned Cargo manifests. The directory
is ignored by Git. The script refuses to overwrite an existing runtime.
To reproduce alongside one already present, use another directory:

```bash
python3 scripts/setup-bench-runtime.py --destination /tmp/ptps-bench-runtime
export BENCH_PETTA_ROOT=/tmp/ptps-bench-runtime/PeTTa
export MORK_LIBRARY="$BENCH_PETTA_ROOT/mork_ffi/target/release/libmork_ffi.so"
```

The build flag is `RUSTFLAGS='-C target-cpu=native'`, matching the measured
build. CPU, compiler, build path, and system dependencies can change the
resulting binary hash. The script records the newly built hashes in that
runtime's `source-versions.json`; the committed manifest preserves the hashes
of the measured build. Do not claim bit-identical reproduction solely from
matching source revisions.

The measured runtime originally used clean Git archives of the existing
local PeTTa, MORK, and PathMap checkouts and a pinned clone of `mork_ffi`.
Fresh setup clones the same commits. Uncommitted changes in those external
working directories were not part of the measured source.

## Why the two compatibility changes are necessary

1. **Register `mork-flush` as a PeTTa function.** The current Rust FFI queues
   PeTTa `add-atom` writes. A flush makes them query-visible. Without function
   registration, `(mork-flush &mork)` would be returned as an unevaluated
   expression. Every timed mutation ends with a real flush, so the measured
   acknowledgement includes applying the write.
2. **Implement comma conjunctions through sequential MORK matches.** The
   native `match` command accepts a single atom pattern. The existing PTPS
   rules use `(, pattern1 pattern2 ...)`. The bridge evaluates each pattern
   through MORK in order, carrying shared variable bindings in Prolog.
   Without this patch, these queries returned no results. This is a host-side
   join, and its cost belongs to the MORK–PeTTa measurements.

These are benchmark-runtime compatibility changes, not MORK engine
optimizations. The report must identify them when describing the evaluated
PeTTa integration.

## Verify before measuring

For the default runtime:

```bash
python3 scripts/setup-bench-runtime.py --check
python3 scripts/check-bench-runtime.py
```

For a custom runtime, add `--destination /tmp/ptps-bench-runtime` to the first
command and `--runtime /tmp/ptps-bench-runtime` to the second.

The first command checks files against the runtime's recorded hashes. The
second launches fresh processes and verifies real FFI add/match/remove,
quoted value handling, and five PeTTa conjunction cases: empty conjunction,
single pattern, several bindings, absent result, and variables bound by an
earlier conjunct. Both processes preload the exact same absolute library
path; the script prints that path and its SHA-256. A successful PeTTa probe
also requires `MORK init: done` and the expected query answers.

The original PTPS application-rule tests can be run directly through the
same launcher:

```bash
scripts/bench-petta.sh "$PWD/mork/rules/tests/test_frontier.metta" --silent
scripts/bench-petta.sh "$PWD/mork/rules/tests/test_dependency_taint.metta" --silent
```

The measured runtime passed 36 frontier assertions and 39 dependency/taint
assertions, with no failed assertions. These are correctness checks, not
performance measurements.

## Run individual MeTTa files

```bash
scripts/bench-petta.sh "$PWD/mork/bench/runtime/probe.metta" --silent
```

For direct Python FFI access outside the benchmark runner, preload before
Python starts:

```bash
export MORK_LIBRARY="$PWD/.bench-runtime/PeTTa/mork_ffi/target/release/libmork_ffi.so"
LD_PRELOAD="$MORK_LIBRARY" python3 your_mork_program.py
```

`morklib.so` is the Prolog bridge; it is **not** the Rust FFI library.
The complete E1–E6 workload and reporting commands are in `../README.md`.
