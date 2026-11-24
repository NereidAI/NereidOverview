#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
INSTALLER = ROOT / "scripts" / "install-suite.sh"
EXAMPLE = ROOT / "docs" / "deploy" / "quick-install.env.example"
GUIDE = ROOT / "docs" / "deploy" / "quick-install.md"


class QuickInstallContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text(encoding="utf-8")
        cls.example = EXAMPLE.read_text(encoding="utf-8")
        cls.guide = GUIDE.read_text(encoding="utf-8")

    def test_stage_order_preserves_all_forge_boundaries(self):
        match = re.search(r"SUITE_STAGES=\(\n(.*?)\n\)", self.script, re.S)
        self.assertIsNotNone(match)
        stages = match.group(1).split()
        self.assertEqual(
            stages,
            [
                "prerequisites",
                "identity",
                "sphere",
                "sphere-acceptance",
                "horizon",
                "horizon-acceptance",
                "pre-artifact",
                "pre-infra",
                "pre-kubeflow",
                "pre-verify",
                "forge",
                "forge-acceptance",
                "link",
            ],
        )
        self.assertLess(stages.index("pre-verify"), stages.index("forge"))
        self.assertLess(stages.index("forge-acceptance"), stages.index("link"))

    def test_pre_and_nf_attestations_are_independent_and_default_closed(self):
        self.assertIn("PRE_GATE_CONFIRMED", self.script)
        self.assertIn("NF_GATE_CONFIRMED", self.script)
        self.assertIn("NF_LIVE_ACCEPTANCE_CONFIRMED", self.script)
        for name in (
            "SPHERE_SSO_ACCEPTANCE_CONFIRMED",
            "HORIZON_SETUP_CONFIRMED",
            "PRE_GATE_CONFIRMED",
            "NF_GATE_CONFIRMED",
            "NF_LIVE_ACCEPTANCE_CONFIRMED",
        ):
            self.assertIn(f'export {name}="no"', self.example)
        self.assertIn("These `yes` values are operator attestations", self.guide)
        self.assertIn("Do not set every attestation preemptively", self.guide)

    def test_all_chart_downloads_pass_through_frozen_artifacts(self):
        self.assertNotRegex(self.script, r"(?m)^\s*(?:[A-Za-z_][A-Za-z0-9_]*=)?\s*pull_nereid_chart ")
        self.assertIn("suite_pull_chart_frozen", self.script)
        self.assertIn("suite_prepare_pre_frozen", self.script)
        self.assertNotIn("registry login", self.script)

    def test_secret_channels_do_not_use_shell_arguments_or_tracing(self):
        self.assertNotIn("set -x", self.script)
        self.assertNotIn("--from-literal", self.script)
        self.assertNotRegex(self.script, r"--set(?:-string)?[^\n]*(?:password|secret|token|key)")
        self.assertIn("--patch-file=", self.script)
        self.assertIn("--from-file=password=", self.script)
        self.assertIn("canonical SeaweedFS Secret", self.script)

    def test_repository_is_explicitly_optional(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("optional quick reference", readme)
        self.assertIn("not a required deployment controller", readme)
        self.assertIn("their own procedures or automation", readme)
        self.assertRegex(self.guide, r"without\s+following this guide")


class QuickInstallStatusTest(unittest.TestCase):
    def make_config(self, root, extra=""):
        deployment = root / "deployment"
        deployment.mkdir(mode=0o700)
        config = deployment / "deployment.env"
        config.write_text(
            "\n".join(
                [
                    f'export DEPLOYMENT_ROOT="{deployment}"',
                    'export KUBECONTEXT="test-context"',
                    'export BASE_DOMAIN="example.org"',
                    'export NFS_SERVER="nfs.example.org"',
                    'export NFS_EXPORT="/srv/nfs/nereidai"',
                    'export LINK_MQTTS_HOST="edge.example.org"',
                    extra,
                ]
            )
            + "\n"
        )
        config.chmod(0o600)
        return config

    def run_installer(self, config, *args):
        return subprocess.run(
            [str(INSTALLER), "--config", str(config), *args],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )

    def test_status_is_offline_and_reports_every_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = self.make_config(Path(temporary))
            result = self.run_installer(config, "status")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Last recorded state: not-started", result.stdout)
            self.assertIn("prerequisites", result.stdout)
            self.assertIn("pre-kubeflow", result.stdout)
            self.assertIn("forge-acceptance", result.stdout)
            self.assertIn("link", result.stdout)
            self.assertNotIn("kubectl", result.stderr)

    def test_secret_canary_is_rejected_without_being_printed(self):
        with tempfile.TemporaryDirectory() as temporary:
            canary = "do-not-print-this-value"
            config = self.make_config(Path(temporary), f'export PG_ADMIN_PASSWORD="{canary}"')
            result = self.run_installer(config, "status")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PG_ADMIN_PASSWORD", result.stderr)
            self.assertNotIn(canary, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
