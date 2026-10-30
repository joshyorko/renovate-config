import importlib.util
import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/review-sdk-lock.py'
SPEC = importlib.util.spec_from_file_location('review_sdk_lock', SCRIPT)
SDK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SDK)


class ReviewSdkLockTest(unittest.TestCase):
    def setUp(self):
        self.dependencies = {
            '@oh-my-pi/pi-coding-agent': '18.13.3',
            '@types/node': '24.19.2',
            'tsx': '4.21.0',
            'typescript': '5.9.3',
        }
        self.package = json.dumps({
            'name': 'review-ci-sdk-types',
            'private': True,
            'dependencies': self.dependencies,
        }) + '\n'
        self.lock = json.dumps({
            'name': 'review-ci-sdk-types',
            'lockfileVersion': 3,
            'requires': True,
            'packages': {
                '': {'name': 'review-ci-sdk-types', 'dependencies': self.dependencies},
                'node_modules/@oh-my-pi/pi-coding-agent': {
                    'version': '18.13.3',
                    'resolved': 'https://registry.npmjs.org/@oh-my-pi/pi-coding-agent/-/pi-coding-agent-18.13.3.tgz',
                    'integrity': 'sha512-' + base64.b64encode(b'x' * 64).decode(),
                },
            },
        }) + '\n'
        self.toolchains = json.dumps({'verification': {
            'nodeImage': 'node:26.13.0-bookworm-slim@sha256:' + 'a' * 64,
            'sdkLockGeneratorNpm': '11.20.0',
        }})
        self.base_containerfile = 'ARG OMP_VERSION=18.13.3\n'
        self.candidate_containerfile = 'ARG OMP_VERSION=18.14.0\n'

    def generator(self, package_text, lock_text, node_image, npm_version):
        self.assertEqual(node_image, 'node:26.13.0-bookworm-slim@sha256:' + 'a' * 64)
        self.assertEqual(npm_version, '11.20.0')
        package = json.loads(package_text)
        lock = json.loads(lock_text)
        version = package['dependencies']['@oh-my-pi/pi-coding-agent']
        lock['packages']['']['dependencies'] = package['dependencies']
        entry = lock['packages']['node_modules/@oh-my-pi/pi-coding-agent']
        entry['version'] = version
        entry['resolved'] = f'https://registry.npmjs.org/@oh-my-pi/pi-coding-agent/-/pi-coding-agent-{version}.tgz'
        return json.dumps(lock) + '\n'

    def expected(self, package=None, lock=None, toolchains=None, generate=None):
        return SDK.expected_sdk_files(
            package or self.package,
            lock or self.lock,
            toolchains or self.toolchains,
            self.base_containerfile,
            self.candidate_containerfile,
            generate=generate or self.generator,
        )

    def test_regenerates_only_the_omp_sdk_pin_from_trusted_base(self):
        manifest, lock = self.expected()
        self.assertEqual(json.loads(manifest)['dependencies'], {
            **self.dependencies,
            '@oh-my-pi/pi-coding-agent': '18.14.0',
        })
        self.assertEqual(json.loads(lock)['packages']['']['dependencies'], json.loads(manifest)['dependencies'])
        self.assertEqual(json.loads(lock)['packages']['node_modules/@oh-my-pi/pi-coding-agent']['version'], '18.14.0')

    def test_rejects_unapproved_manifest_fields_and_dependencies(self):
        for transform in (
            lambda value: {**value, 'scripts': {'postinstall': 'echo unsafe'}},
            lambda value: {**value, 'dependencies': {**value['dependencies'], 'left-pad': '1.3.0'}},
            lambda value: {**value, 'dependencies': {**value['dependencies'], 'tsx': 'file:../tsx'}},
        ):
            package = json.loads(self.package)
            with self.subTest(package=transform(package)), self.assertRaises(ValueError):
                self.expected(package=json.dumps(transform(package)))

    def test_rejects_malformed_trusted_lock_root_and_sdk_seed(self):
        bad_root = json.loads(self.lock)
        bad_root['packages']['']['dependencies']['tsx'] = '4.0.0'
        bad_sdk = json.loads(self.lock)
        bad_sdk['packages']['node_modules/@oh-my-pi/pi-coding-agent']['version'] = '18.12.0'
        for lock in (bad_root, bad_sdk):
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                self.expected(lock=json.dumps(lock))

    def test_rejects_nonregistry_sources_and_missing_integrity(self):
        for edit in (
            lambda entry: entry.update(resolved='https://example.invalid/sdk.tgz'),
            lambda entry: entry.pop('integrity'),
            lambda entry: entry.update(resolved='file:../sdk.tgz'),
            lambda entry: entry.update(integrity=entry['integrity'] + ' sha999-invalid'),
        ):
            lock = json.loads(self.lock)
            edit(lock['packages']['node_modules/@oh-my-pi/pi-coding-agent'])
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                self.expected(lock=json.dumps(lock))

    def test_rejects_unpinned_toolchains_and_wrong_generator_result(self):
        bad_toolchains = json.dumps({'verification': {'nodeImage': 'node:latest', 'sdkLockGeneratorNpm': '11.20.0'}})
        with self.assertRaises(ValueError):
            self.expected(toolchains=bad_toolchains)
        with self.assertRaisesRegex(ValueError, 'not resolve'):
            self.expected(generate=lambda *args: self.lock)

    def test_legacy_and_sdk_base_paths_are_all_or_none(self):
        self.assertFalse(SDK.sdk_lock_enabled(set()))
        self.assertTrue(SDK.sdk_lock_enabled({'ci/sdk-types/package.json', 'ci/sdk-types/package-lock.json'}))
        with self.assertRaisesRegex(ValueError, 'partial'):
            SDK.sdk_lock_enabled({'ci/sdk-types/package.json'})

    def test_change_scope_is_base_mode_specific(self):
        containerfile = 'image/appliance/Containerfile'
        manifest = 'ci/sdk-types/package.json'
        lock = 'ci/sdk-types/package-lock.json'
        self.assertEqual(SDK.validate_changed_paths({containerfile}, sdk_enabled=False), {containerfile})
        self.assertEqual(SDK.validate_changed_paths({containerfile, manifest, lock}, sdk_enabled=True),
                         {containerfile, manifest, lock})
        for paths, sdk_enabled in (
            ({containerfile, 'scripts/update-omp-pins.mjs'}, True),
            ({containerfile, manifest}, False),
        ):
            with self.subTest(paths=paths, sdk_enabled=sdk_enabled), self.assertRaises(ValueError):
                SDK.validate_changed_paths(paths, sdk_enabled=sdk_enabled)

    def test_candidate_sdk_artifact_must_match_independent_lock_reproduction(self):
        expected = self.expected()
        SDK.require_exact_sdk_files(expected, dict(zip(SDK.SDK_PATHS, expected)))
        tampered_lock = json.loads(expected[1])
        tampered_lock['packages']['node_modules/@oh-my-pi/pi-coding-agent']['version'] = '18.13.3'
        with self.assertRaisesRegex(ValueError, 'independently generated'):
            SDK.require_exact_sdk_files(expected, {SDK.SDK_PATHS[0]: expected[0],
                                                   SDK.SDK_PATHS[1]: json.dumps(tampered_lock) + '\n'})

    def git_base(self, sdk_paths=None, include_toolchains=True):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        files = {
            'image/appliance/Containerfile': self.base_containerfile,
        }
        if include_toolchains:
            files['ci/toolchains.json'] = self.toolchains
        if sdk_paths is None:
            sdk_paths = SDK.SDK_PATHS
        sdk_contents = {SDK.SDK_PATHS[0]: self.package, SDK.SDK_PATHS[1]: self.lock}
        files.update({path: sdk_contents[path] for path in sdk_paths})
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'Test'], check=True)
        subprocess.run(['git', '-C', str(root), 'config', 'user.email', 'test@example.invalid'], check=True)
        subprocess.run(['git', '-C', str(root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(root), 'commit', '-qm', 'trusted SDK base'], check=True)
        revision = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                                  check=True, capture_output=True, text=True).stdout.strip()
        return root, revision

    def test_sync_uses_trusted_base_and_heals_stale_sdk_files(self):
        root, revision = self.git_base()
        (root / SDK.SDK_PATHS[0]).write_text('{"name":"candidate-controlled"}\n')
        (root / SDK.SDK_PATHS[1]).write_text('{"tampered":true}\n')
        enabled = SDK.synchronize_from_base(root, revision, self.candidate_containerfile, self.generator)
        self.assertTrue(enabled)
        expected = self.expected()
        self.assertEqual((root / SDK.SDK_PATHS[0]).read_text(), expected[0])
        self.assertEqual((root / SDK.SDK_PATHS[1]).read_text(), expected[1])

    def test_failed_regeneration_leaves_candidate_sdk_files_untouched(self):
        root, revision = self.git_base()
        before = {path: (root / path).read_text() for path in SDK.SDK_PATHS}

        def fail(*args):
            raise ValueError('registry resolution changed')

        with self.assertRaisesRegex(ValueError, 'registry resolution changed'):
            SDK.synchronize_from_base(root, revision, self.candidate_containerfile, fail)
        self.assertEqual({path: (root / path).read_text() for path in SDK.SDK_PATHS}, before)

    def test_git_base_keeps_legacy_pair_absence_and_rejects_partial_pair(self):
        root, revision = self.git_base(sdk_paths=(), include_toolchains=False)
        self.assertIsNone(SDK.base_sdk_files(root, revision))
        for path in SDK.SDK_PATHS:
            root, revision = self.git_base(sdk_paths=(path,))
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'partial'):
                SDK.base_sdk_files(root, revision)

    def test_writer_verifier_reproduces_candidate_sdk_artifact(self):
        root, revision = self.git_base()
        expected = self.expected()
        artifact = root / 'qualified'
        for path, content in zip(SDK.SDK_PATHS, expected):
            destination = artifact / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content)
        self.assertTrue(SDK.verify_from_base(root, revision, self.candidate_containerfile, artifact, self.generator))
        (artifact / SDK.SDK_PATHS[1]).write_text(self.lock)
        with self.assertRaisesRegex(ValueError, 'independently generated'):
            SDK.verify_from_base(root, revision, self.candidate_containerfile, artifact, self.generator)


if __name__ == '__main__':
    unittest.main()
