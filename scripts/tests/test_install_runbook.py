#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import re
import unittest

RUNBOOK = Path(__file__).parents[2] / "docs" / "deploy" / "install-suite.md"


def bash_blocks(text):
    return re.findall(r"```bash\n(.*?)```", text, re.S)


class InstallRunbookSecretSequenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")

    def test_secret_policy_does_not_render_before_site_values_exist(self):
        section = self.text.split("## 3. Secret generation and policy", 1)[1].split("## 4.", 1)[0]
        blocks = bash_blocks(section)
        self.assertTrue(any("generate-suite-secrets.py init" in block for block in blocks))
        for block in blocks:
            self.assertNotIn("generate-suite-secrets.py render", block)

    def test_identity_has_a_separate_edit_stop_before_rendering(self):
        section = self.text.split("## 5. Phase 1", 1)[1].split("## 6.", 1)[0]
        creation = [block for block in bash_blocks(section) if "values-k3s-example.yaml" in block]
        self.assertEqual(len(creation), 1)
        self.assertNotIn("generate-suite-secrets.py render", creation[0])
        rendering = [block for block in bash_blocks(section) if "generate-suite-secrets.py render" in block]
        self.assertEqual(len(rendering), 1)
        self.assertIn("site-values.yaml", rendering[0])

    def test_nfs_storage_reuses_bootstrap_server_and_export(self):
        self.assertIn('--set-string "nfs.nfs.server=${NFS_SERVER}"', self.text)
        self.assertIn('--set-string "nfs.nfs.share=${NFS_EXPORT}"', self.text)
        self.assertNotIn("--set nfs.nfs.share=/export/nereidai", self.text)


class ForgeDevelopmentRunbookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = RUNBOOK.read_text(encoding="utf-8")
        cls.section = cls.text.split("## 7. Phase 3", 1)[1].split("## 8.", 1)[0]

    def test_forge_uses_development_artifacts_instead_of_formal_release_downloads(self):
        self.assertIn("PRE_VERSION=0.0.0-dev", self.text)
        self.assertIn("NEREIDFORGE_VERSION=0.0.0-dev", self.text)
        self.assertNotIn("Formal publication gate", self.section)
        self.assertNotIn("<verified-pre-version>", self.section)
        self.assertNotIn("<verified-nf-version>", self.section)
        self.assertNotIn("releases/download", self.section)
        self.assertNotIn('branch "v$NEREIDFORGE_VERSION"', self.section)

    def test_pre_installer_and_nf_charts_use_the_shared_download_helpers(self):
        pre_section = self.section.split("### 7.2", 1)[1].split("### 7.3", 1)[0]
        nf_section = self.section.split("### 7.4", 1)[1].split("### 7.5", 1)[0]
        loader = (RUNBOOK.parents[2] / "scripts" / "load-deployment-env.sh").read_text(encoding="utf-8")
        self.assertIn('PRE_ROOT="$(pull_pre_nereidforge_installer "$PRE_VERSION")"', pre_section)
        self.assertIn("oras pull", loader)
        self.assertNotIn("curl", pre_section)
        self.assertNotIn("PRE_DOWNLOAD", pre_section)
        for chart in ("nereidforge-backend", "nereidforge-frontend", "nereidforge-ml-backend"):
            self.assertIn(f'pull_nereid_chart {chart} "$NEREIDFORGE_VERSION"', nf_section)
        self.assertEqual(nf_section.count("pull_nereid_chart "), 3)
        self.assertNotIn("oci://", nf_section)
        self.assertNotIn("nereidforge-tenant-check", nf_section)

    def test_persistent_environment_is_preserved_and_restored_after_reconnect(self):
        operator_section = self.text.split("## 2. Operator environment", 1)[1].split("## 3.", 1)[0]
        self.assertIn('if [[ ! -e "$DEPLOYMENT_ROOT/deployment.env" ]]', operator_section)
        self.assertIn("source scripts/load-deployment-env.sh", operator_section)
        self.assertIn("including after a disconnect", operator_section)
        self.assertNotRegex(self.section, r"(?m)^export ")


if __name__ == "__main__":
    unittest.main()
