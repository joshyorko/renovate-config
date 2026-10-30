import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sync-review-omp-pins.py'


class PinSyncTest(unittest.TestCase):
    def load(self):
        spec = importlib.util.spec_from_file_location('pin_sync', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_version_only_bump_refreshes_every_dependent_pin(self):
        module = self.load()
        original = ('ARG OMP_VERSION=18.14.0\nARG OMP_SOURCE_COMMIT=old\n'
                    'ARG OMP_SOURCE_SHA256=old\nARG OMP_NATIVES_VERSION=18.13.3\n'
                    'ARG OMP_NATIVES_X86_64_SHA512=old\nARG OMP_NATIVES_AARCH64_SHA512=old\n'
                    'ARG OMP_PATCH_SHA256=unchanged\nARG OTHER=keep\n')
        pins = {'OMP_SOURCE_COMMIT': 'a' * 40, 'OMP_SOURCE_SHA256': 'b' * 64,
                'OMP_NATIVES_VERSION': '18.14.0', 'OMP_NATIVES_X86_64_SHA512': 'c' * 128,
                'OMP_NATIVES_AARCH64_SHA512': 'd' * 128}
        seen = []
        def resolve(version):
            seen.append(version)
            return pins
        synced = module.synchronize(original, resolve)
        self.assertEqual(seen, ['18.14.0'])
        for key, value in pins.items():
            self.assertIn(f'ARG {key}={value}\n', synced)
        self.assertIn('ARG OMP_PATCH_SHA256=unchanged\nARG OTHER=keep\n', synced)
        self.assertEqual(module.synchronize(synced, resolve), synced)

    def test_lookup_failure_does_not_produce_candidate(self):
        module = self.load()
        def fail(version):
            raise ValueError('native package is not published')
        with self.assertRaisesRegex(ValueError, 'not published'):
            module.synchronize('ARG OMP_VERSION=18.14.0\n', fail)

    def test_file_remains_unchanged_when_published_pin_resolution_fails(self):
        module = self.load()
        with tempfile.TemporaryDirectory() as directory:
            self.assert_file_unchanged_on_failure(module, Path(directory) / 'Containerfile')

    def assert_file_unchanged_on_failure(self, module, candidate):
        original = ('ARG OMP_VERSION=18.14.0\nARG OMP_SOURCE_COMMIT=old\n'
                    'ARG OMP_SOURCE_SHA256=old\nARG OMP_NATIVES_VERSION=18.13.3\n'
                    'ARG OMP_NATIVES_X86_64_SHA512=old\nARG OMP_NATIVES_AARCH64_SHA512=old\n')
        candidate.write_text(original)
        with self.assertRaisesRegex(ValueError, 'not published'):
            module.synchronize_file(candidate, lambda version: (_ for _ in ()).throw(
                ValueError('native package is not published')))
        self.assertEqual(candidate.read_text(), original)

    def test_incomplete_pin_set_is_rejected(self):
        module = self.load()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            module.synchronize('ARG OMP_VERSION=18.14.0\n', lambda version: {'OMP_SOURCE_COMMIT': 'a' * 40})

    def test_missing_or_duplicate_version_is_rejected(self):
        module = self.load()
        for source in ('', 'ARG OMP_VERSION=18.14.0\nARG OMP_VERSION=18.13.3\n'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                module.synchronize(source, lambda version: self.fail('must not resolve'))


if __name__ == '__main__':
    unittest.main()
