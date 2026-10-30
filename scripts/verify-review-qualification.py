#!/usr/bin/env python3
"""Accept only independently resolved OMP pins and source-bound receipts."""
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

SYNC_PATH = Path(__file__).with_name('sync-review-omp-pins.py')
SYNC_SPEC = importlib.util.spec_from_file_location('sync_review_omp_pins', SYNC_PATH)
SYNC = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(SYNC)


def value(text, name):
    found = re.findall(rf'^ARG {name}=([^\n]+)$', text, re.MULTILINE)
    if len(found) != 1:
        raise ValueError(f'expected one {name} pin')
    return found[0]


def optional_value(text, name, default):
    found = re.findall(rf'^ARG {name}=([^\n]+)$', text, re.MULTILINE)
    if len(found) > 1:
        raise ValueError(f'expected at most one {name} pin')
    return found[0] if found else default


def verify(root, before, after, resolve=SYNC.published_pins):
    # Resolve again in the writer job. The qualification artifact is not a
    # trusted source of the newly published release and platform digests.
    synchronized = SYNC.synchronize(before, resolve)
    source = value(synchronized, 'OMP_SOURCE_COMMIT')
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('invalid OMP source commit')
    paths = {}
    memory_shim = optional_value(synchronized, 'OMP_MEMORYD_SHIM', '1')
    if memory_shim not in ('0', '1'):
        raise ValueError('invalid OMP_MEMORYD_SHIM mode')
    if memory_shim == '1':
        paths['OMP_PATCH_SHA256'] = root / 'patches/omp/memory-backend-registration.patch'
    for digest, path_key in (
        ('OMP_CLIPBOARD_PATCH_SHA256', 'OMP_CLIPBOARD_PATCH_PATH'),
        ('OMP_SESSION_LIFECYCLE_PATCH_SHA256', 'OMP_SESSION_LIFECYCLE_PATCH_PATH'),
    ):
        path = value(before, path_key)
        if not re.fullmatch(r'/usr/local/share/review/omp/[a-zA-Z0-9_.-]+\.patch', path):
            raise ValueError(f'invalid {path_key}')
        paths[digest] = root / 'patches/omp' / Path(path).name
    expected = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    expected.update({
        'OMP_CLIPBOARD_PATCH_SOURCE_COMMIT': source,
        'OMP_SESSION_LIFECYCLE_PATCH_SOURCE_COMMIT': source,
    })
    result = synchronized
    for name, replacement in expected.items():
        value(synchronized, name)
        result, count = re.subn(rf'^ARG {name}=[^\n]+$', f'ARG {name}={replacement}', result, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'invalid {name} pin')
    if after != result:
        raise ValueError('qualification result changes more than independently resolved OMP pins and patch receipts')


if __name__ == '__main__':
    try:
        if len(sys.argv) != 4:
            raise ValueError('usage: verify-review-qualification.py REVIEW_ROOT BEFORE_CONTAINERFILE AFTER_CONTAINERFILE')
        verify(Path(sys.argv[1]), Path(sys.argv[2]).read_text(), Path(sys.argv[3]).read_text())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
