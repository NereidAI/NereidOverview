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

    def test_pre_inputs_and_tools_are_validated_before_the_ordered_stages(self):
        pre_section = self.section.split("### 7.2", 1)[1].split("### 7.3", 1)[0]
        self.assertIn("DEX_STATIC_EMAIL=admin@nereidforge.local", pre_section)
        self.assertNotIn("DEX_STATIC_EMAIL=admin@example.org", pre_section)
        self.assertNotIn('admin@$BASE_DOMAIN', pre_section)
        for variable in (
            "PG_ADMIN_PASSWORD",
            "SEAWEEDFS_S3_ACCESS_KEY",
            "SEAWEEDFS_S3_SECRET_KEY",
            "DEX_STATIC_PASSWORD",
            "DEX_STATIC_PASSWORD_HASH",
        ):
            self.assertIn(variable, pre_section)
        self.assertIn("command -v envsubst", pre_section)
        self.assertIn("command -v htpasswd", pre_section)
        self.assertIn("import boto3", pre_section)
        self.assertIn("helm repo add cloudnative-pg", pre_section)
        self.assertIn(
            "Current pre-NereidForge does not read or populate "
            "`secret-store/suite-secrets.json`",
            pre_section,
        )

    def test_pre_secret_recovery_preserves_live_identities_and_checks_dex_pair(self):
        pre_section = self.section.split("### 7.2", 1)[1].split("### 7.3", 1)[0]
        self.assertIn('pg-${PG_CLUSTER_NAME}-credentials', pre_section)
        self.assertIn("SITE_VS_SECRET", pre_section)
        self.assertIn("DB_VS_SECRET", pre_section)
        self.assertIn("seaweedfs-s3-credentials", pre_section)
        self.assertIn("Password for user dex correct", pre_section)
        self.assertIn("DEX_CREDENTIALS=MISMATCH", pre_section)
        self.assertIn("genuine first installation", pre_section)
        preflight = next(
            block for block in bash_blocks(pre_section) if "PRE_PREFLIGHT=PASS" in block
        )
        self.assertTrue(preflight.startswith("(\n  set -euo pipefail\n"), preflight)
        self.assertIn("missing+=(PG_ADMIN_PASSWORD)", preflight)
        self.assertIn("secret:seaweedfs-s3-config", preflight)
        self.assertIn("configmap:seaweedfs-s3-config", preflight)
        self.assertIn('Error from server (NotFound):', preflight)
        self.assertNotIn('*"not found"*', preflight)
        self.assertIn('(( status == 1 )) || exit "$status"', preflight)
        self.assertNotIn("PG_CLUSTER_NAME PG_DB_NAME PG_DB_USER PG_ADMIN_PASSWORD", preflight)

    def test_nf_admin_secret_creation_requires_explicit_not_found(self):
        nf_secrets = self.section.split("### 7.3", 1)[1].split("### 7.4", 1)[0]
        admin = next(
            block for block in bash_blocks(nf_secrets)
            if "create secret generic nereidforge-admin-credentials" in block
        )
        self.assertIn("Error from server (NotFound):", admin)
        self.assertIn("Could not query secret/nereidforge-admin-credentials", admin)
        self.assertNotIn("if ! kubectl -n nereidforge get secret nereidforge-admin-credentials", admin)

    def test_nf_install_block_stops_before_helm_after_any_failed_prerequisite(self):
        nf_section = self.section.split("### 7.4", 1)[1].split("### 7.5", 1)[0]
        install = next(
            block for block in bash_blocks(nf_section)
            if "helm upgrade --install nereidforge-backend" in block
        )
        self.assertTrue(install.startswith("(\n  set -euo pipefail\n"), install)
        self.assertTrue(install.rstrip().endswith(")"), install)
        self.assertIn("return to §7.1", nf_section)
        self.assertIn("Do not authenticate", nf_section)
        acceptance = self.section.split("### 7.5", 1)[1].split("## 8.", 1)[0]
        self.assertIn(
            'NEREIDFORGE_RESOLVED_VERSION="$(cat "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt")"',
            acceptance,
        )

    def test_pre_only_and_nf_artifact_gates_are_independent(self):
        gate = self.section.split("### 7.1", 1)[1].split("### 7.2", 1)[0]
        self.assertIn("Section 7.2 requires only the pre publication gate", gate)
        self.assertIn("Sections 7.3–7.5 additionally require the complete selected-profile NF gate", gate)
        self.assertIn("image_profile=full", gate)
        self.assertRegex(gate, r"all 23 NF-owned\s+images")
        self.assertIn("image_profile=cpu-xpu", gate)
        self.assertIn("18 core/CPU/Intel-XPU", gate)
        self.assertIn("every Intel\nXPU image remains required", gate)
        self.assertIn("exactly four NF OCI charts", gate)
        self.assertIn("do not start Link", gate)


if __name__ == "__main__":
    unittest.main()
