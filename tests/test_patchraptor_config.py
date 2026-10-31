import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.verify_patchraptor_repository_visibility import (
    REQUIRED_TARGETS,
    missing_targets,
    repository_names,
)


RENOVATE = json.loads((ROOT / "renovate-config.json").read_text())
INHERITED = json.loads((ROOT / "org-inherited-config.json").read_text())
WORKFLOW = (ROOT / ".github/workflows/renovate.yml").read_text()

# Current source from joshyorko/mcp-tunnel-kit/config/deploy-images.json.
DEPLOY_IMAGES = """{
  "version": 1,
  "images": {
    "cas": {
      "repository": "ghcr.io/joshyorko/codex-action-server",
      "digest": "sha256:bda7ef55e9d31574aefbd650ec38bfbe993b5adbbfffc15a49a7ca83e6ba26ca",
      "revision": "54278b1ecc3c67d46ebdb25148971814243f51a6"
    },
    "executor": {
      "repository": "ghcr.io/usefulsoftwareco/executor-selfhost:2.0.0-beta.12",
      "digest": "sha256:89a2b829150d01bc26305f844159ca8064ea8a4ace047490d09b6a3c8bdcf600"
    },
    "schema_proxy": {
      "repository": "ghcr.io/joshyorko/codex-action-server",
      "digest": "sha256:bda7ef55e9d31574aefbd650ec38bfbe993b5adbbfffc15a49a7ca83e6ba26ca",
      "revision": "54278b1ecc3c67d46ebdb25148971814243f51a6"
    },
    "tunnel": {
      "repository": "ghcr.io/openai/tunnel-client:v0.0.15",
      "digest": "sha256:119799b778ba8411a124f53588f9dc837fd62ba03e5fadf77d675123c92ab58e"
    }
  }
}
"""


def render_replacement(template, values):
    for variable in ("newValue", "newDigest"):
        template = re.sub(
            rf"{{{{#if {variable}}}}}(.*?){{{{else}}}}(.*?){{{{/if}}}}",
            lambda match: match.group(1) if values.get(variable) else match.group(2),
            template,
            flags=re.DOTALL,
        )
    return re.sub(
        r"{{{([A-Za-z][A-Za-z0-9_]*)}}}",
        lambda match: values[match.group(1)],
        template,
    )


class PatchraptorTargetConfigTest(unittest.TestCase):
    def test_discovery_is_explicit_and_keeps_existing_repositories(self):
        self.assertTrue(RENOVATE["autodiscover"])
        self.assertEqual(
            RENOVATE["autodiscoverFilter"],
            [
                "joshyorko/camp",
                "joshyorko/codex-action-server",
                "joshyorko/devsy-provider-harvester",
                "joshyorko/dsb-common",
                "joshyorko/dudley-factory",
                "joshyorko/dudley-os",
                "joshyorko/homebrew-tools",
                "joshyorko/mcp-tunnel-kit",
                "joshyorko/rcc",
                "joshyorko/review",
                "joshyorko/room-of-requirement",
            ],
        )
        self.assertNotIn("*", RENOVATE["autodiscoverFilter"])
        self.assertEqual(RENOVATE["requireConfig"], "required")
        self.assertTrue(REQUIRED_TARGETS.issubset(RENOVATE["autodiscoverFilter"]))
        self.assertEqual(
            RENOVATE["allowedCommands"],
            [
                "^node developer/update_dependency_locks\\.mjs$",
                "^node scripts/update-omp-pins\\.mjs$",
                "^node scripts/update-gh-pins\\.mjs$",
                "^node scripts/update-rtk-pins\\.mjs$",
                "^node scripts/update-requirements-ci-hashes\\.mjs$",
                "^node scripts/update-typesafe-pins\\.mjs$",
            ],
        )

    def test_installation_visibility_preflight_is_bounded_and_wired(self):
        self.assertEqual(
            REQUIRED_TARGETS,
            {
                "joshyorko/codex-action-server",
                "joshyorko/mcp-tunnel-kit",
            },
        )
        self.assertEqual(missing_targets([]), tuple(sorted(REQUIRED_TARGETS)))
        self.assertEqual(
            missing_targets(["joshyorko/codex-action-server"]),
            ("joshyorko/mcp-tunnel-kit",),
        )
        self.assertEqual(missing_targets(REQUIRED_TARGETS), ())
        response = [
            {"repositories": [{"full_name": "joshyorko/codex-action-server"}]},
            {"repositories": [{"full_name": "joshyorko/mcp-tunnel-kit"}]},
        ]
        self.assertEqual(set(repository_names(response)), REQUIRED_TARGETS)
        self.assertEqual(missing_targets(repository_names(response)), ())
        with self.assertRaises(ValueError):
            repository_names({"repositories": [{}]})

        missing = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/verify_patchraptor_repository_visibility.py"),
            ],
            input=json.dumps({"repositories": []}),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(missing.returncode, 1)
        self.assertIn("joshyorko/codex-action-server", missing.stderr)
        self.assertIn("joshyorko/mcp-tunnel-kit", missing.stderr)
        self.assertIn("/installation/repositories", WORKFLOW)
        self.assertIn(
            "scripts/verify_patchraptor_repository_visibility.py", WORKFLOW
        )
        self.assertIn("GH_TOKEN: ${{ steps.get-token.outputs.token }}", WORKFLOW)

    def test_sensitive_repositories_override_central_automerge(self):
        self.assertTrue(INHERITED["platformAutomerge"])
        rules = INHERITED["packageRules"]
        central_rules = [rule for rule in rules if not rule.get("matchRepositories")]
        self.assertTrue(
            any(rule.get("automerge") is True for rule in central_rules),
            "existing automerge behavior for other repositories must remain intact",
        )

        repositories = {
            "joshyorko/codex-action-server",
            "joshyorko/mcp-tunnel-kit",
        }
        overrides = [
            rule
            for rule in rules
            if set(rule.get("matchRepositories", [])) == repositories
            and rule.get("automerge") is False
            and rule.get("platformAutomerge") is False
        ]
        self.assertEqual(len(overrides), 1)

        for repo, managers in (
            (
                "joshyorko/codex-action-server",
                {"dockerfile", "github-actions", "pep621", "pip_requirements"},
            ),
            (
                "joshyorko/mcp-tunnel-kit",
                {"custom.regex", "docker-compose", "dockerfile", "github-actions"},
            ),
        ):
            gate = next(
                rule
                for rule in rules
                if rule.get("matchRepositories") == [repo]
                and set(rule.get("matchManagers", [])) == managers
            )
            self.assertTrue(gate["dependencyDashboardApproval"])
            self.assertEqual(gate["prCreation"], "status-success")
            self.assertFalse(gate["automerge"])
            self.assertFalse(gate["platformAutomerge"])

    def test_cas_production_image_is_disabled_for_generic_updates(self):
        rule = next(
            rule
            for rule in INHERITED["packageRules"]
            if rule.get("matchRepositories") == ["joshyorko/mcp-tunnel-kit"]
            and rule.get("matchPackageNames")
            == ["ghcr.io/joshyorko/codex-action-server"]
        )
        self.assertFalse(rule["enabled"])

    def test_manifest_regex_tracks_only_executor_and_tunnel_image_pairs(self):
        managers = INHERITED["customManagers"]
        self.assertEqual(len(managers), 2)
        extracted = []
        for manager in managers:
            path_expression = re.fullmatch(
                r"/(.*)/", manager["managerFilePatterns"][0]
            )
            self.assertIsNotNone(path_expression)
            path_regex = re.compile(path_expression.group(1))
            self.assertRegex("config/deploy-images.json", path_regex)
            self.assertIsNone(path_regex.search("config/other-images.json"))
            self.assertEqual(manager["datasourceTemplate"], "docker")
            self.assertEqual(manager["versioningTemplate"], "docker")
            self.assertEqual(len(manager["matchStrings"]), 1)

            pattern = manager["matchStrings"][0]
            python_pattern = re.sub(
                r"\(\?<([A-Za-z][A-Za-z0-9_]*)>", r"(?P<\1>", pattern
            )
            match = re.search(python_pattern, DEPLOY_IMAGES)
            self.assertIsNotNone(match)
            extracted.append(match.groupdict())

            template = manager["autoReplaceStringTemplate"]
            self.assertIn('"repository":', template)
            self.assertIn('"digest":', template)
            self.assertIn("{{#if newDigest}}", template)
            self.assertIn("{{else}}{{{currentDigest}}}", template)

            replacement_values = {
                **match.groupdict(),
                "newValue": "9.8.7",
                "newDigest": "sha256:" + "0" * 64,
            }
            replacement = render_replacement(template, replacement_values)
            updated_manifest = (
                DEPLOY_IMAGES[: match.start()]
                + replacement
                + DEPLOY_IMAGES[match.end() :]
            )
            updated = json.loads(updated_manifest)["images"]
            image_key = (
                "executor"
                if match.group("depName")
                == "ghcr.io/usefulsoftwareco/executor-selfhost"
                else "tunnel"
            )
            tag_prefix = "v" if image_key == "tunnel" else ""
            self.assertEqual(
                updated[image_key]["repository"],
                f"{match.group('depName')}:{tag_prefix}9.8.7",
            )
            self.assertEqual(
                updated[image_key]["digest"], "sha256:" + "0" * 64
            )
            for cas_key in ("cas", "schema_proxy"):
                self.assertEqual(updated[cas_key], json.loads(DEPLOY_IMAGES)["images"][cas_key])

        self.assertEqual(
            extracted,
            [
                {
                    "depName": "ghcr.io/usefulsoftwareco/executor-selfhost",
                    "currentValue": "2.0.0-beta.12",
                    "currentDigest": "sha256:89a2b829150d01bc26305f844159ca8064ea8a4ace047490d09b6a3c8bdcf600",
                },
                {
                    "depName": "ghcr.io/openai/tunnel-client",
                    "currentValue": "0.0.15",
                    "currentDigest": "sha256:119799b778ba8411a124f53588f9dc837fd62ba03e5fadf77d675123c92ab58e",
                },
            ],
        )

        production_cas_only = json.dumps(
            {
                "cas": json.loads(DEPLOY_IMAGES)["images"]["cas"],
                "schema_proxy": json.loads(DEPLOY_IMAGES)["images"]["schema_proxy"],
            }
        )
        for manager in managers:
            pattern = manager["matchStrings"][0]
            python_pattern = re.sub(
                r"\(\?<([A-Za-z][A-Za-z0-9_]*)>", r"(?P<\1>", pattern
            )
            self.assertIsNone(re.search(python_pattern, production_cas_only))

    def test_package_rules_group_only_non_cas_tunnel_images(self):
        rule = next(
            rule
            for rule in INHERITED["packageRules"]
            if rule.get("groupName") == "Tunnel-kit deployment images"
        )
        self.assertEqual(rule["matchRepositories"], ["joshyorko/mcp-tunnel-kit"])
        self.assertEqual(
            set(rule["matchPackageNames"]),
            {
                "ghcr.io/usefulsoftwareco/executor-selfhost",
                "ghcr.io/openai/tunnel-client",
            },
        )
        self.assertTrue(rule["dependencyDashboardApproval"])
        self.assertEqual(rule["prCreation"], "status-success")
        self.assertFalse(rule["automerge"])
        self.assertFalse(rule["platformAutomerge"])


if __name__ == "__main__":
    unittest.main()
