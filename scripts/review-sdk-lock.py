#!/usr/bin/env python3
"""Synchronize and verify Review's pinned Dagger SDK lock without candidate scripts."""
import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from pathlib import Path

SDK_PATHS = ('ci/sdk-types/package.json', 'ci/sdk-types/package-lock.json')
CONTAINERFILE = 'image/appliance/Containerfile'
TOOLCHAINS = 'ci/toolchains.json'
EXPECTED_NAME = 'review-ci-sdk-types'
FIXED_DEPENDENCIES = {
    '@types/node': '24.19.2',
    'tsx': '4.21.0',
    'typescript': '5.9.3',
}
VERSION_RE = re.compile(r'^\d+\.\d+\.\d+$')
NODE_IMAGE_RE = re.compile(r'^node:(\d+\.\d+\.\d+)-bookworm-slim@sha256:([0-9a-f]{64})$')


def omp_version(containerfile):
    versions = re.findall(r'^ARG OMP_VERSION=([^\n]+)$', containerfile, re.MULTILINE)
    if len(versions) != 1 or not VERSION_RE.fullmatch(versions[0]):
        raise ValueError('expected one stable OMP_VERSION in trusted/candidate Containerfile')
    return versions[0]


def sdk_lock_enabled(paths):
    present = set(paths) & set(SDK_PATHS)
    if not present:
        return False
    if present != set(SDK_PATHS):
        raise ValueError('trusted Review base has a partial ci/sdk-types manifest/lock pair')
    return True


def validate_changed_paths(paths, sdk_enabled):
    changed = set(paths)
    allowed = {CONTAINERFILE}
    if sdk_enabled:
        allowed.update(SDK_PATHS)
    if CONTAINERFILE not in changed or not changed <= allowed:
        raise ValueError('Review OMP PR changes files outside the trusted qualification allowlist')
    return changed


def toolchain_pins(toolchains_text):
    try:
        verification = json.loads(toolchains_text)['verification']
        image = verification['nodeImage']
        npm_version = verification['sdkLockGeneratorNpm']
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f'{TOOLCHAINS}: missing pinned SDK lock Node/npm toolchain') from error
    match = NODE_IMAGE_RE.fullmatch(image) if isinstance(image, str) else None
    if not match or not VERSION_RE.fullmatch(str(npm_version)):
        raise ValueError(f'{TOOLCHAINS}: SDK lock toolchain must use a digest-pinned Node image and exact npm version')
    return image, str(npm_version)


def validate_locked_packages(lock, label):
    packages = lock.get('packages')
    if not isinstance(packages, dict):
        raise ValueError(f'{label}: missing npm package records')
    for path, record in packages.items():
        if path == '':
            continue
        if not isinstance(record, dict) or record.get('link') is True:
            raise ValueError(f'{label}: invalid or linked npm package record {path}')
        resolved = record.get('resolved')
        parsed = urlsplit(resolved) if isinstance(resolved, str) else None
        if (parsed is None or parsed.scheme != 'https' or parsed.netloc != 'registry.npmjs.org' or
                not parsed.path.endswith('.tgz') or parsed.query or parsed.fragment):
            raise ValueError(f'{label}: package {path} must resolve from registry.npmjs.org')
        integrity = record.get('integrity')
        entries = integrity.split() if isinstance(integrity, str) else ()
        if not entries:
            raise ValueError(f'{label}: package {path} has no valid npm integrity digest')
        for entry in entries:
            match = re.fullmatch(r'(sha512|sha384|sha256|sha1)-([A-Za-z0-9+/]+={0,2})', entry)
            if not match:
                raise ValueError(f'{label}: package {path} has malformed npm integrity metadata')
            try:
                digest = base64.b64decode(match.group(2), validate=True)
            except (ValueError, TypeError) as error:
                raise ValueError(f'{label}: package {path} has malformed npm integrity metadata') from error
            if len(digest) != hashlib.new(match.group(1)).digest_size:
                raise ValueError(f'{label}: package {path} has invalid npm integrity metadata')


def decode_base_sdk(package_text, lock_text, base_containerfile):
    try:
        package = json.loads(package_text)
        lock = json.loads(lock_text)
    except json.JSONDecodeError as error:
        raise ValueError('trusted SDK base package/lock is malformed JSON') from error
    base_version = omp_version(base_containerfile)
    expected_dependencies = {
        '@oh-my-pi/pi-coding-agent': base_version,
        **FIXED_DEPENDENCIES,
    }
    if set(package) != {'name', 'private', 'dependencies'} or package.get('name') != EXPECTED_NAME or package.get('private') is not True:
        raise ValueError('trusted SDK manifest has an unapproved root shape')
    if package.get('dependencies') != expected_dependencies:
        raise ValueError('trusted SDK manifest dependencies do not match the pinned OMP and CI SDK versions')
    if (set(lock) != {'name', 'lockfileVersion', 'requires', 'packages'} or
            lock.get('name') != EXPECTED_NAME or lock.get('lockfileVersion') != 3 or
            lock.get('requires') is not True or not isinstance(lock.get('packages'), dict)):
        raise ValueError('trusted SDK lock has an unapproved root shape or lockfile version')
    root_package = lock['packages'].get('')
    if (not isinstance(root_package, dict) or set(root_package) != {'name', 'dependencies'} or
            root_package.get('name') != EXPECTED_NAME or root_package.get('dependencies') != expected_dependencies):
        raise ValueError('trusted SDK lock root dependencies do not match its manifest')
    validate_locked_packages(lock, f'{SDK_PATHS[1]} trusted base')
    sdk_entry = lock['packages'].get('node_modules/@oh-my-pi/pi-coding-agent')
    if not isinstance(sdk_entry, dict) or sdk_entry.get('version') != base_version:
        raise ValueError('trusted SDK lock OMP entry does not match the trusted Containerfile')
    return package, lock, base_version


def _generate_lock_with_pinned_npm(package_text, lock_text, node_image, npm_version):
    with tempfile.TemporaryDirectory(prefix='review-sdk-lock-') as directory:
        workspace = Path(directory)
        (workspace / 'package.json').write_text(package_text)
        (workspace / 'package-lock.json').write_text(lock_text)
        (workspace / 'home').mkdir()
        (workspace / 'empty.npmrc').write_text('')
        command = [
            'docker', 'run', '--rm', '--network', 'host',
            '--volume', f'{workspace}:/review-sdk-lock',
            '--workdir', '/review-sdk-lock',
            '--env', 'HOME=/review-sdk-lock/home',
            '--env', 'NPM_CONFIG_USERCONFIG=/review-sdk-lock/empty.npmrc',
            '--env', 'NPM_CONFIG_CACHE=/review-sdk-lock/npm-cache',
        ]
        for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY'):
            if os.environ.get(name):
                command.extend(('--env', name))
        command.extend(('--env', 'expected'))
        command.extend((
            node_image,
            'sh', '-ceu',
            'actual="$(npm --version)"; '
            'test "$actual" = "$expected" || { echo "pinned npm mismatch: expected $expected, found $actual" >&2; exit 1; }; '
            'npm install --package-lock-only --ignore-scripts --no-audit --no-fund',
        ))
        environment = dict(os.environ)
        environment['expected'] = npm_version
        try:
            subprocess.run(command, check=True, capture_output=True, text=True, timeout=600, env=environment)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = getattr(error, 'stderr', None) or str(error)
            raise ValueError(f'trusted OMP SDK lock reproduction failed with npm {npm_version}: {detail.strip()}') from error
        return (workspace / 'package-lock.json').read_text()


def expected_sdk_files(package_text, lock_text, toolchains_text, base_containerfile,
                       candidate_containerfile, generate=_generate_lock_with_pinned_npm):
    package, lock, base_version = decode_base_sdk(package_text, lock_text, base_containerfile)
    version = omp_version(candidate_containerfile)
    image, npm_version = toolchain_pins(toolchains_text)
    package['dependencies']['@oh-my-pi/pi-coding-agent'] = version
    updated_package = f'{json.dumps(package, indent=2)}\n'
    updated_lock_text = generate(updated_package, lock_text, image, npm_version)
    try:
        updated_lock = json.loads(updated_lock_text)
    except json.JSONDecodeError as error:
        raise ValueError('npm lock generator returned malformed JSON') from error
    root = updated_lock.get('packages', {}).get('')
    sdk_entry = updated_lock.get('packages', {}).get('node_modules/@oh-my-pi/pi-coding-agent')
    if (updated_lock.get('name') != EXPECTED_NAME or updated_lock.get('lockfileVersion') != 3 or
            updated_lock.get('requires') is not True or not isinstance(root, dict) or
            root.get('name') != EXPECTED_NAME or root.get('dependencies') != package['dependencies'] or
            not isinstance(sdk_entry, dict) or sdk_entry.get('version') != version):
        raise ValueError(f'{SDK_PATHS[1]}: npm did not resolve the pinned SDK root and OMP version {version}')
    validate_locked_packages(updated_lock, SDK_PATHS[1])
    return updated_package, updated_lock_text


def require_exact_sdk_files(expected, candidate):
    if set(candidate) != set(SDK_PATHS):
        raise ValueError('qualified Review artifact is missing one or more SDK manifest/lock files')
    for path in SDK_PATHS:
        if candidate[path] != expected[SDK_PATHS.index(path)]:
            raise ValueError(f'{path}: qualified artifact differs from the independently generated trusted-base SDK lock')


def git_show(root, revision, path):
    result = subprocess.run(['git', '-C', str(root), 'show', f'{revision}:{path}'],
                            capture_output=True, text=True)
    if result.returncode:
        raise FileNotFoundError(path)
    return result.stdout


def git_entry_mode(root, revision, path):
    result = subprocess.run(
        ['git', '-C', str(root), 'ls-tree', '--full-tree', '--format=%(objectmode):%(objecttype)', revision, '--', path],
        capture_output=True, text=True,
    )
    if result.returncode:
        raise ValueError(f'cannot inspect Git tree entry {revision}:{path}: {result.stderr.strip()}')
    entries = result.stdout.splitlines()
    if len(entries) != 1:
        return None
    return entries[0]


def require_regular_git_blob(root, revision, path):
    if git_entry_mode(root, revision, path) != '100644:blob':
        raise ValueError(f'{path}: expected a regular Git blob with mode 100644 in {revision}')


def require_git_directories(root, revision, paths):
    for path in paths:
        mode = git_entry_mode(root, revision, path)
        if mode is not None and mode != '040000:tree':
            raise ValueError(f'{path}: expected a real Git tree in {revision}')


def base_sdk_files(root, base_ref):
    require_git_directories(root, base_ref, ('ci', 'ci/sdk-types'))
    found = {}
    for path in SDK_PATHS:
        try:
            if git_entry_mode(root, base_ref, path) is None:
                found[path] = None
            else:
                require_regular_git_blob(root, base_ref, path)
                found[path] = git_show(root, base_ref, path)
        except FileNotFoundError:
            found[path] = None
    enabled = sdk_lock_enabled(path for path in SDK_PATHS if found[path] is not None)
    if not enabled:
        return None
    for path in (CONTAINERFILE, TOOLCHAINS):
        try:
            require_regular_git_blob(root, base_ref, path)
            found[path] = git_show(root, base_ref, path)
        except FileNotFoundError as error:
            raise ValueError(f'trusted Review base is missing required file {path}') from error
    return found


def artifact_entry_exists(root, relative_path):
    current = Path(root)
    try:
        root_mode = current.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise ValueError('qualified artifact root must be a real directory')
    parts = Path(relative_path).parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(mode):
            raise ValueError(f'{relative_path}: qualified artifact contains a symlink')
        if index < len(parts) - 1:
            if not stat.S_ISDIR(mode):
                raise ValueError(f'{relative_path}: qualified artifact path parent is not a directory')
        elif not stat.S_ISREG(mode):
            raise ValueError(f'{relative_path}: qualified artifact entry is not a regular non-symlink artifact file')
    return True


def synchronize_from_base(root, base_ref, candidate_containerfile, generate=_generate_lock_with_pinned_npm):
    base = base_sdk_files(root, base_ref)
    if base is None:
        return False
    expected = expected_sdk_files(base[SDK_PATHS[0]], base[SDK_PATHS[1]], base[TOOLCHAINS],
                                  base[CONTAINERFILE], candidate_containerfile, generate=generate)
    for path, content in zip(SDK_PATHS, expected):
        destination = Path(root) / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    return True


def verify_from_base(root, base_ref, candidate_containerfile, artifact_root, generate=_generate_lock_with_pinned_npm):
    artifact_root = Path(artifact_root)
    if not artifact_entry_exists(artifact_root, CONTAINERFILE):
        raise ValueError('qualified artifact is missing the Containerfile')
    if (artifact_root / CONTAINERFILE).read_text() != candidate_containerfile:
        raise ValueError('qualified Containerfile artifact differs from the verified bytes')
    base = base_sdk_files(root, base_ref)
    if base is None:
        if any(artifact_entry_exists(artifact_root, path) for path in SDK_PATHS):
            raise ValueError('legacy Containerfile-only qualification artifact contains untrusted SDK files')
        return False
    expected = expected_sdk_files(base[SDK_PATHS[0]], base[SDK_PATHS[1]], base[TOOLCHAINS],
                                  base[CONTAINERFILE], candidate_containerfile, generate=generate)
    candidate = {path: (artifact_root / path).read_text() for path in SDK_PATHS
                 if artifact_entry_exists(artifact_root, path)}
    require_exact_sdk_files(expected, candidate)
    return True


def validate_git_changes(root, base_ref, head_ref):
    require_regular_git_blob(root, base_ref, CONTAINERFILE)
    base = base_sdk_files(root, base_ref)
    enabled = base is not None
    result = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', f'{base_ref}...{head_ref}'],
                            check=True, capture_output=True, text=True)
    paths = result.stdout.splitlines()
    validate_changed_paths(paths, enabled)
    for path in (CONTAINERFILE, *(SDK_PATHS if enabled else ())):
        require_regular_git_blob(root, head_ref, path)
    return enabled


def main():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command', required=True)
    changes = subparsers.add_parser('check-changes')
    changes.add_argument('root', type=Path)
    changes.add_argument('base_ref')
    changes.add_argument('head_ref')
    sync = subparsers.add_parser('synchronize')
    sync.add_argument('root', type=Path)
    sync.add_argument('base_ref')
    sync.add_argument('containerfile', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'check-changes':
            enabled = validate_git_changes(args.root, args.base_ref, args.head_ref)
            print(f'sdk_lock_enabled={str(enabled).lower()}')
        elif args.command == 'synchronize':
            enabled = synchronize_from_base(args.root, args.base_ref, args.containerfile.read_text())
            print('trusted-base SDK manifest and lock synchronized' if enabled else 'legacy Containerfile-only mode')
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
