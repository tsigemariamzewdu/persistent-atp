#!/usr/bin/env python3
"""Recreate the pinned MORK/PeTTa benchmark runtime without modifying other checkouts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'mork' / 'bench' / 'runtime'
REFERENCE = json.loads((ASSETS / 'measured-runtime.json').read_text())


def run(*args, cwd=None, env=None):
    print('+', ' '.join(str(arg) for arg in args), flush=True)
    return subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(runtime):
    """Check recorded artifacts; this does not run performance workloads."""
    manifest = json.loads((runtime / 'source-versions.json').read_text())
    for relative, expected in manifest['files_sha256'].items():
        actual = sha256(runtime / relative)
        if actual != expected:
            raise SystemExit(f'Runtime artifact changed: {relative}')
    library = runtime / 'PeTTa/mork_ffi/target/release/libmork_ffi.so'
    print('Recorded runtime hashes match.')
    print(f'MORK_LIBRARY={library}')
    print(f'libmork_ffi.so SHA-256: {sha256(library)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / '.bench-runtime')
    parser.add_argument('--toolchain', default=REFERENCE['rust_toolchain'],
                        help='Installed rustup toolchain (default: pinned measurement toolchain)')
    parser.add_argument('--offline', action='store_true',
                        help='Build with cached Cargo dependencies; source clones still need network')
    parser.add_argument('--check', action='store_true', help='Verify an existing runtime without rebuilding')
    args = parser.parse_args()
    runtime = args.destination.resolve()
    if args.check:
        check(runtime)
        return
    if runtime.exists() and any(runtime.iterdir()):
        raise SystemExit(f'{runtime} is not empty. Use --check, or choose a new --destination.')
    for executable in ('git', 'patch', 'cargo', 'rustc', 'gcc', 'pkg-config', 'cmake', 'make', 'swipl'):
        if shutil.which(executable) is None:
            raise SystemExit(f'Missing dependency: {executable}. See mork/bench/runtime/README.md.')
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ('MORK', 'PathMap', 'PeTTa', 'mork_ffi'):
        path = runtime / ('PeTTa/mork_ffi' if name == 'mork_ffi' else name)
        run('git', 'clone', '--no-checkout', REFERENCE['source_repositories'][name], path)
        run('git', '-C', path, 'checkout', '--detach', REFERENCE[name])
        actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != REFERENCE[name]:
            raise SystemExit(f'Wrong pinned commit for {name}: {actual}')
    shutil.copyfile(ASSETS / 'compatibility.patch', runtime / 'runtime-compatibility.patch')
    run('patch', '--batch', '-p1', '-i', runtime / 'runtime-compatibility.patch', cwd=runtime)
    ffi = runtime / 'PeTTa/mork_ffi'
    shutil.copyfile(ASSETS / 'Cargo.lock', ffi / 'Cargo.lock')
    # The lockfile fixes Cargo crates/git revisions; Rust and source revisions
    # are separately pinned above. target-cpu=native deliberately targets the host.
    env = dict(os.environ, RUSTFLAGS='-C target-cpu=native')
    build = ['cargo', '+' + args.toolchain, 'build', '--manifest-path', ffi / 'Cargo.toml',
             '--release', '--locked']
    if args.offline:
        build.append('--offline')
    run(*build, env=env)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'swipl'], text=True).split()
    run('gcc', '-shared', '-fPIC', '-o', ffi / 'morklib.so', ffi / 'mork.c', *flags)
    manifest = dict(REFERENCE)
    manifest['source_note'] = 'Fresh upstream clones at pinned commits; compatibility patch applied.'
    manifest['rust_toolchain'] = args.toolchain
    manifest['build_command'] = 'RUSTFLAGS="-C target-cpu=native" ' + ' '.join(map(str, build))
    manifest['rustc'] = subprocess.check_output(['rustc', '+' + args.toolchain, '--version'], text=True).strip()
    manifest['cargo'] = subprocess.check_output(['cargo', '+' + args.toolchain, '--version'], text=True).strip()
    manifest['swipl'] = subprocess.check_output(['swipl', '--version'], text=True).strip()
    manifest['files_sha256'] = {name: sha256(runtime / name) for name in REFERENCE['files_sha256']}
    manifest['validation'] = {'status': 'not yet run; follow runtime README smoke checks'}
    (runtime / 'source-versions.json').write_text(json.dumps(manifest, indent=2) + '\n')
    check(runtime)


if __name__ == '__main__':
    main()
