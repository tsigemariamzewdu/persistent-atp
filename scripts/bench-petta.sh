#!/usr/bin/env bash
# Run MeTTa through PeTTa with the same real MORK library used by the FFI suite.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
petta_root="${BENCH_PETTA_ROOT:-$repo/.bench-runtime/PeTTa}"
export MORK_LIBRARY="${MORK_LIBRARY:-$petta_root/mork_ffi/target/release/libmork_ffi.so}"
if [[ ! -f "$MORK_LIBRARY" || ! -f "$petta_root/mork_ffi/morklib.so" ]]; then
    echo "Missing real MORK runtime: $MORK_LIBRARY (and PeTTa morklib.so). See mork/bench/README.md." >&2
    exit 69
fi
export LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD:}$MORK_LIBRARY"
exec swipl --stack_limit=8g -q -s "$petta_root/src/main.pl" -- "$@" mork
