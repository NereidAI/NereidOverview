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


if __name__ == "__main__":
    unittest.main()
