#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
HELPER = ROOT / "scripts" / "lib" / "suite_versions.py"
CHANNEL_LIB = ROOT / "scripts" / "lib" / "suite-versions.sh"

MANIFEST = """\
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
schemaVersion: 1
channels:
  dev:
    nereididentity: 0.0.0-dev
    nereidsphere: 0.0.0-dev
    nereidhorizon: 0.0.0-dev
    pre: 0.0.0-dev
    nereidforge: 0.0.0-dev
    nereidlink: 0.0.0-dev
releases:
  0.0.1:
    nereididentity: 0.0.1
    nereidsphere: 0.0.1
    nereidhorizon: 0.0.1
    pre: 0.0.1
    nereidforge: 0.0.1
    nereidlink: 0.0.1
"""

EXPECTED_VARS = {
    "nereididentity": "NEREIDIDENTITY_VERSION",
    "nereidsphere": "NEREIDSPHERE_VERSION",
    "nereidhorizon": "NEREIDHORIZON_VERSION",
    "pre": "PRE_VERSION",
    "nereidforge": "NEREIDFORGE_VERSION",
    "nereidlink": "NEREIDLINK_VERSION",
}


class SuiteVersionsTest(unittest.TestCase):
    def run_helper(self, manifest_text: str, channel: str):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "suite-versions.yaml"
            manifest.write_text(manifest_text, encoding="utf-8")
            return subprocess.run(
                [
                    "python3",
                    str(HELPER),
                    "--manifest",
                    str(manifest),
                    "--channel",
                    channel,
                ],
                capture_output=True,
                text=True,
            )

    def test_dev_channel_emits_shell_assignments_for_every_product(self):
        result = self.run_helper(MANIFEST, "dev")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        for variable in EXPECTED_VARS.values():
            self.assertEqual(lines[f"SUITE_DEFAULT_{variable}"], "0.0.0-dev")
        self.assertEqual(lines["SUITE_VERSION_CHANNEL"], "dev")

    def test_release_channel_pins_the_tagged_matrix(self):
        result = self.run_helper(MANIFEST, "0.0.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = dict(
            line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
        )
        self.assertEqual(lines["SUITE_VERSION_CHANNEL"], "0.0.1")
        for variable in EXPECTED_VARS.values():
            self.assertEqual(lines[f"SUITE_DEFAULT_{variable}"], "0.0.1")
        # Shell-safe output: single-quoted values with no quote injection.
        for line in result.stdout.splitlines():
            self.assertNotIn("\n", line)

    def test_unknown_release_channel_fails_closed(self):
        result = self.run_helper(MANIFEST, "9.9.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("no release matrix", result.stderr)

    def test_missing_product_entry_fails_closed(self):
        broken = MANIFEST.replace("    nereidlink: 0.0.1\n", "")
        result = self.run_helper(broken, "0.0.1")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("nereidlink", result.stderr)

    def test_malformed_selector_is_rejected(self):
        broken = MANIFEST.replace(
            "    nereidlink: 0.0.1\n", "    nereidlink: '0.0.1; rm -rf /'\n"
        )
        result = self.run_helper(broken, "0.0.1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid version selector", result.stderr)

    def test_missing_manifest_fails_closed(self):
        result = subprocess.run(
            [
                "python3",
                str(HELPER),
                "--manifest",
                "/nonexistent/suite-versions.yaml",
                "--channel",
                "dev",
            ],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class SuiteChannelDetectionTest(unittest.TestCase):
    def bash(self, script: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", "-c", f"source {CHANNEL_LIB}\n{script}"],
            capture_output=True,
            text=True,
        )

    def init_repo(self, directory: Path) -> Path:
        subprocess.run(["git", "init", "-b", "main", str(directory)], check=True,
                       capture_output=True)
        subprocess.run(
            ["git", "-C", str(directory), "config", "user.email", "test@example.org"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(directory), "config", "user.name", "Test"], check=True
        )
        (directory / "README").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(directory), "add", "README"], check=True)
        subprocess.run(
            ["git", "-C", str(directory), "commit", "-m", "seed"],
            check=True,
            capture_output=True,
        )
        return directory

    def test_main_checkout_resolves_to_dev_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_repo(Path(temporary) / "repo")
            result = self.bash(f"suite_resolve_version_channel {repo}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "dev")

    def test_exact_semver_tag_resolves_to_release_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_repo(Path(temporary) / "repo")
            subprocess.run(
                ["git", "-C", str(repo), "tag", "-a", "v0.0.1", "-m", "v0.0.1"],
                check=True,
            )
            result = self.bash(f"suite_resolve_version_channel {repo}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "0.0.1")

    def test_malformed_tag_falls_back_to_dev(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = self.init_repo(Path(temporary) / "repo")
            subprocess.run(
                ["git", "-C", str(repo), "tag", "-a", "release-1", "-m", "x"],
                check=True,
            )
            result = self.bash(f"suite_resolve_version_channel {repo}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "dev")

    def test_non_git_directory_falls_back_to_dev(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = self.bash(f"suite_resolve_version_channel {temporary}")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "dev")


if __name__ == "__main__":
    unittest.main()
