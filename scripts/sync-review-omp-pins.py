#!/usr/bin/env python3
"""Resolve a version-only OMP bump using trusted registry metadata, before qualification."""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

API = 'https://api.github.com/repos/can1357/oh-my-pi'
PIN_FIELDS = (
    'OMP_SOURCE_COMMIT', 'OMP_SOURCE_SHA256', 'OMP_NATIVES_VERSION',
    'OMP_NATIVES_X86_64_SHA512', 'OMP_NATIVES_AARCH64_SHA512',
)


def get(url):
    headers = {'User-Agent': 'patchraptor-review-qualification'}
    # Never forward the GitHub credential to npm or archive redirect hosts.
    if url.startswith(API + '/') and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        return response.read()


def published_pins(version):
    release = json.loads(get(f'{API}/releases/tags/v{version}'))
    if release.get('draft') or release.get('prerelease') or release.get('tag_name') != f'v{version}':
        raise ValueError(f'OMP {version} is not a published stable release')
    commit = json.loads(get(f'{API}/commits/v{version}')).get('sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('OMP release tag has no valid source commit')
    archive = get(f'https://github.com/can1357/oh-my-pi/archive/{commit}.tar.gz')
    pins = {'OMP_SOURCE_COMMIT': commit, 'OMP_SOURCE_SHA256': hashlib.sha256(archive).hexdigest(),
            'OMP_NATIVES_VERSION': version}
    for arch, key in (('x64', 'OMP_NATIVES_X86_64_SHA512'), ('arm64', 'OMP_NATIVES_AARCH64_SHA512')):
        package = f'@oh-my-pi/pi-natives-linux-{arch}'
        metadata = json.loads(get(f'https://registry.npmjs.org/{package}/{version}'))
        if metadata.get('name') != package or metadata.get('version') != version:
            raise ValueError(f'{package}@{version}: registry identity mismatch')
        integrity = metadata.get('dist', {}).get('integrity', '')
        if not integrity.startswith('sha512-'):
            raise ValueError(f'{package}@{version}: missing SHA-512 integrity')
        digest = base64.b64decode(integrity[7:], validate=True)
        if len(digest) != 64:
            raise ValueError(f'{package}@{version}: invalid SHA-512 integrity')
        pins[key] = digest.hex()
    return pins


def synchronize(source, resolve=published_pins):
    versions = re.findall(r'^ARG OMP_VERSION=([^\n]+)$', source, re.MULTILINE)
    if len(versions) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+', versions[0]):
        raise ValueError('expected one stable OMP_VERSION pin')
    pins = resolve(versions[0])
    if set(pins) != set(PIN_FIELDS):
        raise ValueError('resolver returned an incomplete or unexpected OMP pin set')
    for name, value in pins.items():
        source, count = re.subn(rf'^ARG {name}=[^\n]+$', f'ARG {name}={value}', source, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f'expected one {name} pin')
    return source


def synchronize_file(path, resolve=published_pins):
    source = path.read_text()
    updated = synchronize(source, resolve)
    path.write_text(updated)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('usage: sync-review-omp-pins.py CONTAINERFILE')
        path = Path(sys.argv[1])
        synchronize_file(path)
        print('OMP source/archive/native pins synchronized; patch qualification is still required.')
    except Exception as error:
        sys.exit(f'OMP pin synchronization failed: {error}')
