import hashlib
import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-review-qualification.py'
VERIFY = importlib.util.spec_from_file_location('verify_qualification', SCRIPT)
VERIFIER = importlib.util.module_from_spec(VERIFY)
VERIFY.loader.exec_module(VERIFIER)


class QualificationReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.commit = 'a' * 40
        self.pins = {'OMP_SOURCE_COMMIT': self.commit,
                     'OMP_SOURCE_SHA256': 'b' * 64,
                     'OMP_NATIVES_VERSION': '18.14.0',
                     'OMP_NATIVES_X86_64_SHA512': 'c' * 128,
                     'OMP_NATIVES_AARCH64_SHA512': 'd' * 128}
        self.patches = {
            'OMP_PATCH_SHA256': 'memory-backend-registration.patch',
            'OMP_CLIPBOARD_PATCH_SHA256': 'clipboard-truthful.patch',
            'OMP_SESSION_LIFECYCLE_PATCH_SHA256': 'session-lifecycle.patch',
        }
        patch_dir = self.root / 'patches/omp'
        patch_dir.mkdir(parents=True)
        for path in self.patches.values():
            (patch_dir / path).write_text(path)
        self.original = ('ARG OMP_VERSION=18.14.0\n'
                         f'ARG OMP_SOURCE_COMMIT={self.commit}\n'
                         'ARG OMP_SOURCE_SHA256=old\n'
                         'ARG OMP_NATIVES_VERSION=18.13.3\n'
                         'ARG OMP_NATIVES_X86_64_SHA512=old\n'
                         'ARG OMP_NATIVES_AARCH64_SHA512=old\n'
                         'ARG OMP_MEMORYD_SHIM=0\n'
                         'ARG OMP_CLIPBOARD_PATCH_SOURCE_COMMIT=old\n'
                         'ARG OMP_SESSION_LIFECYCLE_PATCH_SOURCE_COMMIT=old\n'
                         'ARG OMP_CLIPBOARD_PATCH_PATH=/usr/local/share/review/omp/clipboard-truthful.patch\n'
                         'ARG OMP_SESSION_LIFECYCLE_PATCH_PATH=/usr/local/share/review/omp/session-lifecycle.patch\n'
                         + ''.join(f'ARG {key}=old\n' for key in self.patches)
                         + 'ARG UNRELATED=keep\n')
        self.qualified = self.original.replace('ARG OMP_CLIPBOARD_PATCH_SOURCE_COMMIT=old\n',
                                                f'ARG OMP_CLIPBOARD_PATCH_SOURCE_COMMIT={self.commit}\n')
        self.qualified = self.qualified.replace('ARG OMP_SESSION_LIFECYCLE_PATCH_SOURCE_COMMIT=old\n',
                                                f'ARG OMP_SESSION_LIFECYCLE_PATCH_SOURCE_COMMIT={self.commit}\n')
        for key, value in self.pins.items():
            self.qualified = re.sub(rf'^ARG {key}=.*$', f'ARG {key}={value}', self.qualified, flags=re.MULTILINE)
        for key, filename in self.patches.items():
            if key == 'OMP_PATCH_SHA256':
                continue  # Explicit shim-off mode retains this receipt.
            digest = hashlib.sha256((patch_dir / filename).read_bytes()).hexdigest()
            self.qualified = self.qualified.replace(f'ARG {key}=old', f'ARG {key}={digest}')
        (self.root / 'original').write_text(self.original)

    def verify(self, candidate):
        (self.root / 'qualified').write_text(candidate)
        try:
            VERIFIER.verify(self.root, self.original, candidate, lambda version: self.pins)
            return subprocess.CompletedProcess([], 0, '', '')
        except (OSError, ValueError) as error:
            return subprocess.CompletedProcess([], 1, '', str(error))

    def test_accepts_only_current_source_and_patch_hashes(self):
        self.assertEqual(self.verify(self.qualified).returncode, 0)

    def test_rejects_wrong_source_hash_and_unrelated_edits(self):
        for candidate in (self.qualified.replace(self.commit, 'b' * 40, 1),
                          self.qualified.replace('ARG UNRELATED=keep', 'ARG UNRELATED=changed'),
                          self.qualified.replace('ARG OMP_PATCH_SHA256=', 'ARG OMP_PATCH_SHA256=bad')):
            with self.subTest(candidate=candidate):
                self.assertNotEqual(self.verify(candidate).returncode, 0)

    def test_rejects_mode_change_and_tampered_synchronized_pin(self):
        mode_changed = self.qualified.replace('ARG OMP_MEMORYD_SHIM=0', 'ARG OMP_MEMORYD_SHIM=1')
        source_tampered = self.qualified.replace('ARG OMP_SOURCE_SHA256=' + self.pins['OMP_SOURCE_SHA256'],
                                                  'ARG OMP_SOURCE_SHA256=' + 'e' * 64)
        self.assertNotEqual(self.verify(mode_changed).returncode, 0)
        self.assertNotEqual(self.verify(source_tampered).returncode, 0)

    def test_explicit_memory_shim_off_preserves_memory_patch_receipt(self):
        self.assertEqual(self.verify(self.qualified).returncode, 0)
        memory_hash = hashlib.sha256((self.root / 'patches/omp/memory-backend-registration.patch').read_bytes()).hexdigest()
        memory_updated = self.qualified.replace('ARG OMP_PATCH_SHA256=old', f'ARG OMP_PATCH_SHA256={memory_hash}')
        self.assertNotEqual(self.verify(memory_updated).returncode, 0)

    def test_absent_memory_shim_flag_keeps_legacy_memory_patch_qualification(self):
        original = self.original.replace('ARG OMP_MEMORYD_SHIM=0\n', '')
        memory_hash = hashlib.sha256((self.root / 'patches/omp/memory-backend-registration.patch').read_bytes()).hexdigest()
        qualified = self.qualified.replace('ARG OMP_MEMORYD_SHIM=0\n', '')
        qualified = qualified.replace('ARG OMP_PATCH_SHA256=old', f'ARG OMP_PATCH_SHA256={memory_hash}')
        self.assertEqual(self.verify_from(original, qualified).returncode, 0)

    def verify_from(self, original, candidate):
        try:
            VERIFIER.verify(self.root, original, candidate, lambda version: self.pins)
            return type('Result', (), {'returncode': 0})()
        except (OSError, ValueError):
            return type('Result', (), {'returncode': 1})()


if __name__ == '__main__':
    unittest.main()
