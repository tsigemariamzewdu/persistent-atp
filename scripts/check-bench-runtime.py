#!/usr/bin/env python3
"""Smoke-test actual MORK through Python FFI and PeTTa using one shared library."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def ffi_probe(library):
    class Buffer(ctypes.Structure):
        _fields_ = [('ptr', ctypes.c_void_p), ('len', ctypes.c_size_t)]
    native = ctypes.CDLL(str(library))
    command = native.rust_mork
    command.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    command.restype = Buffer

    def call(name, payload=''):
        result = command(name.encode(), payload.encode())
        if not result.ptr:
            raise RuntimeError(f'Null reply from {name}')
        return ctypes.string_at(result.ptr, result.len).decode()

    assert call('add-atoms', '(runtime-check key "hello world")') == 'OK: loaded'
    assert call('match', '((runtime-check key $v) $v)') == '"hello world"\n'
    assert call('remove-atoms', '(runtime-check key "hello world")') == 'OK: loaded'
    assert call('match', '((runtime-check key $v) $v)') == ''
    print('FFI_SMOKE_PASS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / '.bench-runtime')
    parser.add_argument('--ffi-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    library = runtime / 'PeTTa/mork_ffi/target/release/libmork_ffi.so'
    if args.ffi_child:
        ffi_probe(library)
        return
    env = dict(os.environ, MORK_LIBRARY=str(library), LD_PRELOAD=str(library),
               BENCH_PETTA_ROOT=str(runtime / 'PeTTa'))
    ffi = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--runtime', str(runtime),
                          '--ffi-child'], env=env, text=True, capture_output=True, check=True)
    if 'FFI_SMOKE_PASS' not in ffi.stdout:
        raise RuntimeError(ffi.stdout + ffi.stderr)
    probe = ROOT / 'mork/bench/runtime/conjunction-tests.metta'
    petta = subprocess.run([str(ROOT / 'scripts/bench-petta.sh'), str(probe), '--silent'],
                           env=env, text=True, capture_output=True, check=True)
    for expected in ('MORK init: done', '(EMPTY (identity))', '(SINGLE ("x" "y"))',
                     '(JOIN (("x" "one") ("x" "two") ("y" "three")))',
                     '(ABSENT ())', '(REVERSE (("p" "x")))'):
        if expected not in petta.stdout:
            raise RuntimeError(f'Missing {expected!r}\n{petta.stdout}\n{petta.stderr}')
    if petta.stderr.strip():
        raise RuntimeError(f'Unexpected PeTTa diagnostic: {petta.stderr}')
    print('PASS: FFI add/match/remove and five PeTTa conjunction cases used real MORK.')
    print(f'Both routes preloaded: {library}')
    print('SHA-256:', hashlib.sha256(library.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
