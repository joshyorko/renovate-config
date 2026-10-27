import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/verify-review-qualification.py'


class QualificationReceiptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.commit = 'a' * 40
        self.patches = {
            'OMP_PATCH_SHA256': 'memory-backend-registration.patch',
            'OMP_CLIPBOARD_PATCH_SHA256': 'clipboard-truthful.patch',
            'OMP_SESSION_LIFECYCLE_PATCH_SHA256': 'session-lifecycle.patch',
        }
        patch_dir = self.root / 'patches/omp'
        patch_dir.mkdir(parents=True)
        for path in self.patches.values():
            (patch_dir / path).write_text(path)
        self.original = (f'ARG OMP_SOURCE_COMMIT={self.commit}\n'
                         'ARG OMP_CLIPBOARD_PATCH_SOURCE_COMMIT=old\n'
                         'ARG OMP_SESSION_LIFECYCLE_PATCH_SOURCE_COMMIT=old\n'
                         'ARG OMP_CLIPBOARD_PATCH_PATH=/usr/local/share/review/omp/clipboard-truthful.patch\n'
                         'ARG OMP_SESSION_LIFECYCLE_PATCH_PATH=/usr/local/share/review/omp/session-lifecycle.patch\n'
                         + ''.join(f'ARG {key}=old\n' for key in self.patches)
                         + 'ARG UNRELATED=keep\n')
        self.qualified = self.original.replace('=old\n', f'={self.commit}\n', 2)
        for key, filename in self.patches.items():
            digest = hashlib.sha256((patch_dir / filename).read_bytes()).hexdigest()
            self.qualified = self.qualified.replace(f'ARG {key}=old', f'ARG {key}={digest}')
        (self.root / 'original').write_text(self.original)

    def verify(self, candidate):
        (self.root / 'qualified').write_text(candidate)
        return subprocess.run(['python3', str(SCRIPT), str(self.root), str(self.root / 'original'),
                               str(self.root / 'qualified')], capture_output=True, text=True)

    def test_accepts_only_current_source_and_patch_hashes(self):
        self.assertEqual(self.verify(self.qualified).returncode, 0)

    def test_rejects_wrong_source_hash_and_unrelated_edits(self):
        for candidate in (self.qualified.replace(self.commit, 'b' * 40, 1),
                          self.qualified.replace('ARG UNRELATED=keep', 'ARG UNRELATED=changed'),
                          self.qualified.replace('ARG OMP_PATCH_SHA256=', 'ARG OMP_PATCH_SHA256=bad')):
            with self.subTest(candidate=candidate):
                self.assertNotEqual(self.verify(candidate).returncode, 0)


if __name__ == '__main__':
    unittest.main()
