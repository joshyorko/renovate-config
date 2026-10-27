#!/usr/bin/env python3
"""Accept only the source-bound receipt changes produced by Review qualification."""
import hashlib
import re
import sys
from pathlib import Path


def value(text, name):
    found = re.findall(rf'^ARG {name}=([^\n]+)$', text, re.MULTILINE)
    if len(found) != 1:
        raise ValueError(f'expected one {name} pin')
    return found[0]


def verify(root, before, after):
    source = value(before, 'OMP_SOURCE_COMMIT')
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise ValueError('invalid OMP source commit')
    paths = {
        'OMP_PATCH_SHA256': root / 'patches/omp/memory-backend-registration.patch',
    }
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
    result = before
    for name, replacement in expected.items():
        value(before, name)
        result, count = re.subn(rf'^ARG {name}=[^\n]+$', f'ARG {name}={replacement}', result, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'invalid {name} pin')
    if after != result:
        raise ValueError('qualification result changes more than the expected source and patch receipts')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]), Path(sys.argv[2]).read_text(), Path(sys.argv[3]).read_text())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
