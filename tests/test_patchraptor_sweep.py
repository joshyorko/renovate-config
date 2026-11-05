import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/verify_patchraptor_sweep.py"
TARGETS = ("joshyorko/codex-action-server", "joshyorko/mcp-tunnel-kit")


def healthy(repo):
    return [
        {"repository": repo, "msg": "Dependency extraction complete",
         "stats": {"total": {"fileCount": 2, "depCount": 4}}},
        {"repository": repo, "msg": "Repository finished", "result": "done",
         "cloned": True, "enabled": True, "onboarded": True},
    ]


class TargetSweepTest(unittest.TestCase):
    def verifier(self):
        self.assertTrue(SCRIPT.is_file(), "A successful sweep must verify target outcomes")
        spec = importlib.util.spec_from_file_location("patchraptor_sweep", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.verify_target_records

    def test_completed_targets_require_positive_extraction(self):
        result = self.verifier()(healthy(TARGETS[0]) + healthy(TARGETS[1]))
        self.assertEqual(set(result), set(TARGETS))

    def test_global_success_does_not_hide_a_target_configuration_error(self):
        for repo in TARGETS:
            with self.subTest(repo=repo):
                rows = healthy(TARGETS[0]) + healthy(TARGETS[1])
                rows.append({"repository": repo, "msg": "Repository finished",
                             "result": "config-validation", "cloned": False})
                with self.assertRaises(ValueError):
                    self.verifier()(rows)

    def test_missing_or_unextracted_target_fails_closed(self):
        with self.assertRaises(ValueError):
            self.verifier()(healthy(TARGETS[0]))
        rows = healthy(TARGETS[0]) + healthy(TARGETS[1])
        rows[2]["stats"]["total"]["depCount"] = 0
        with self.assertRaises(ValueError):
            self.verifier()(rows)

    def test_unrelated_repository_errors_do_not_change_existing_writers(self):
        rows = healthy(TARGETS[0]) + healthy(TARGETS[1])
        rows.append({"repository": "joshyorko/review", "msg": "Repository finished",
                     "result": "config-validation"})
        self.assertEqual(set(self.verifier()(rows)), set(TARGETS))

    def test_cached_extraction_and_benign_warnings_remain_valid(self):
        rows = healthy(TARGETS[0]) + healthy(TARGETS[1])
        rows[1]["cloned"] = False
        rows.append({"repository": TARGETS[0], "msg": "Datasource warning"})
        self.assertEqual(set(self.verifier()(rows)), set(TARGETS))


if __name__ == "__main__":
    unittest.main()
