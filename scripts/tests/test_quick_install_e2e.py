#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).parents[2]
INSTALLER = ROOT / "scripts" / "install-suite.sh"
FAKE_HOST = ROOT / "scripts" / "tests" / "fixtures" / "fake_suite_host.py"
class QuickInstallFakeEndToEndTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deployment = self.root / "deployment"
        self.deployment.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for tool in ("helm", "oras", "kubectl", "git", "curl", "getent", "openssl", "python3"):
            (self.bin / tool).symlink_to(FAKE_HOST)
        self.calls = self.root / "calls"
        self.calls.write_text("", encoding="utf-8")
        self.cluster = self.root / "cluster.json"
        self.write_cluster({
            "context": "test-context",
            "cluster_uid": "cluster-uid-a",
            "namespaces": ["kube-system", "cert-manager"],
            "secrets": {
                "cert-manager/nereid-internal-ca-tls": {"ca.crt": "fake-internal-ca"},
            },
            "releases": [],
            "pending_releases": [],
            "chart_version": "0.0.0-dev-abcdef1",
            "pre_version": "0.0.0-dev-abcdef1",
            "storage_class": "nfs-csi",
            "local_storage_class": "local-path",
            "nfs_server": "nfs.nereid.test",
            "nfs_export": "/srv/nfs/nereidai",
            "storage_smoke_owners": {},
        })
        modules = self.root / "modules"
        modules.mkdir()
        (modules / "boto3.py").write_text(
            textwrap.dedent(
                """
                import json
                import os
                from pathlib import Path

                def client(service, **kwargs):
                    assert service == "s3"
                    state = json.loads(Path(os.environ["FAKE_SUITE_CLUSTER"]).read_text(encoding="utf-8"))
                    canonical = state["secrets"]["nereidforge/seaweedfs-s3-credentials"]
                    if kwargs["aws_access_key_id"] != canonical["accessKey"] or kwargs["aws_secret_access_key"] != canonical["secretKey"]:
                        raise PermissionError("fake credentials do not match the canonical Secret")
                    if not kwargs["verify"] or not kwargs["endpoint_url"].startswith("https://"):
                        raise ValueError("fake S3 client requires the retained CA and HTTPS")

                    class FakeS3:
                        def head_bucket(self, *, Bucket):
                            if Bucket != "nereidlink" or not state.get("link_bucket"):
                                raise FileNotFoundError("fake Link bucket is absent")

                        def list_objects_v2(self, *, Bucket, MaxKeys):
                            if Bucket != "nereidlink" or MaxKeys != 1 or not state.get("link_bucket"):
                                raise FileNotFoundError("fake Link bucket is not listable")
                            return {"KeyCount": 0}

                    return FakeS3()
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        self.environment = os.environ.copy()
        self.environment.pop("KUBECONFIG", None)
        self.environment.update({
            "PATH": f"{self.bin}{os.pathsep}{self.environment['PATH']}",
            "HOME": str(self.root),
            "PYTHONPATH": str(modules),
            "FAKE_SUITE_CLUSTER": str(self.cluster),
            "FAKE_SUITE_CALLS": str(self.calls),
        })
        self.config = self.deployment / "deployment.env"
        self.write_config()

    def tearDown(self):
        self.temporary.cleanup()

    def read_cluster(self):
        return json.loads(self.cluster.read_text(encoding="utf-8"))

    def write_cluster(self, state):
        self.cluster.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
        self.cluster.chmod(0o600)

    def write_config(self, **updates):
        values = {
            "DEPLOYMENT_ROOT": str(self.deployment),
            "KUBECONTEXT": "test-context",
            "BASE_DOMAIN": "nereid.test",
            "NFS_SERVER": "nfs.nereid.test",
            "NFS_EXPORT": "/srv/nfs/nereidai",
            "LINK_MQTTS_HOST": "edge.nereid.test",
            "SPHERE_SSO_ACCEPTANCE_CONFIRMED": "yes",
            "HORIZON_SETUP_CONFIRMED": "yes",
            "PRE_GATE_CONFIRMED": "yes",
            "NF_GATE_CONFIRMED": "yes",
            "NF_LIVE_ACCEPTANCE_CONFIRMED": "no",
            **updates,
        }
        self.config.write_text(
            "".join(f'export {name}="{value}"\n' for name, value in values.items()),
            encoding="utf-8",
        )
        self.config.chmod(0o600)

    def run_installer(self, *, expected=0, environment=None):
        env = self.environment.copy()
        if environment:
            env.update(environment)
        result = subprocess.run(
            [str(INSTALLER), "--config", str(self.config)],
            env=env,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if expected is not None:
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def call_lines(self):
        return self.calls.read_text(encoding="utf-8").splitlines()

    def count_calls(self, prefix):
        return sum(line.startswith(prefix) for line in self.call_lines())

    def current_state(self):
        return (self.deployment / "quick-install" / "state" / "current").read_text().strip()

    def marker(self, stage):
        return self.deployment / "quick-install" / "state" / "stages" / stage

    def pre_environment(self):
        return self.deployment / "deploy-values" / "nereidforge" / "site.env"

    def canonical_identities(self):
        secrets = self.read_cluster()["secrets"]
        return {
            key: value
            for key, value in secrets.items()
            if key in {
                "nereidforge/pg-nereidforge-pg-credentials",
                "nereidforge/seaweedfs-s3-credentials",
                "nereidforge/nereidforge-service-credentials",
                "nereidforge/nereidforge-admin-credentials",
            }
        }

    def test_failure_resume_preserves_infrastructure_and_canonical_secrets(self):
        self.run_installer(expected=1, environment={"FAKE_FAIL_PRE_KUBEFLOW": "yes"})
        self.assertEqual(self.current_state(), "pre-kubeflow=failed")
        self.assertEqual(self.count_calls("pre\t10_infra"), 1)
        self.assertEqual(self.count_calls("pre\t30_install-kubeflow"), 1)
        self.assertNotIn("nereidforge-backend", self.read_cluster()["releases"])
        self.assertNotIn("nereidlink", self.read_cluster()["releases"])
        self.assertFalse(any("UNEXPECTED-CONTINUED" in line for line in self.call_lines()))
        canonical = self.canonical_identities()
        retained_pre = self.pre_environment().read_bytes()

        # A lost local copy must not turn an existing canonical identity into a
        # newly generated one, even if the artifact-stage marker is missing.
        self.marker("pre-artifact").unlink()
        lines = self.pre_environment().read_text().splitlines()
        secret_names = ("PG_ADMIN_PASSWORD=", "SEAWEEDFS_S3_ACCESS_KEY=", "SEAWEEDFS_S3_SECRET_KEY=")
        self.pre_environment().write_text(
            "\n".join(line for line in lines if not line.startswith(secret_names)) + "\n",
            encoding="utf-8",
        )
        result = self.run_installer(expected=1)
        self.assertIn("Restore PG_ADMIN_PASSWORD", result.stderr + (self.deployment / "deploy-logs" / "quick-install" / "pre-artifact.log").read_text())
        self.assertEqual(self.canonical_identities(), canonical)
        self.assertNotIn("PG_ADMIN_PASSWORD=", self.pre_environment().read_text())
        self.assertEqual(self.count_calls("pre\t10_infra"), 1)

        self.pre_environment().write_bytes(retained_pre)
        self.pre_environment().chmod(0o600)
        result = self.run_installer(expected=20)
        self.assertIn("NF_LIVE_ACCEPTANCE_CONFIRMED=yes", result.stderr)
        self.assertEqual(self.current_state(), "forge-acceptance=waiting")
        self.assertEqual(self.count_calls("pre\t10_infra"), 1)
        self.assertEqual(self.count_calls("pre\t30_install-kubeflow"), 2)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereididentity\t"), 1)
        current_identities = self.canonical_identities()
        for key, value in canonical.items():
            self.assertEqual(current_identities[key], value)
        self.assertIn("nereidforge/nereidforge-service-credentials", current_identities)
        self.assertIn("nereidforge/nereidforge-admin-credentials", current_identities)
        self.assertNotIn("nereidlink", self.read_cluster()["releases"])

        runtime_before = self.canonical_identities()
        self.marker("forge").unlink()
        secret_dir = self.deployment / "secrets" / "nereidforge"
        (secret_dir / "jwt").unlink()
        (secret_dir / "admin-password").unlink()
        self.run_installer(expected=20)
        self.assertEqual(self.canonical_identities(), runtime_before)
        runtime = runtime_before["nereidforge/nereidforge-service-credentials"]
        admin = runtime_before["nereidforge/nereidforge-admin-credentials"]
        self.assertEqual((secret_dir / "jwt").read_text(), runtime["NEREIDFORGE_AUTH_JWT_SECRET"])
        self.assertEqual((secret_dir / "admin-password").read_text(), admin["password"])

        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer()
        self.assertEqual(self.current_state(), "link=complete")
        self.assertIn("nereidlink", self.read_cluster()["releases"])
        self.assertEqual(self.canonical_identities(), runtime_before)
        self.assertEqual(self.count_calls("pre\t10_infra"), 1)
        self.assertEqual(self.count_calls("pre\t30_install-kubeflow"), 2)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereididentity\t"), 1)
        handoff = self.deployment / "deploy-values" / "nereidforge" / "seaweedfs-credentials.yaml"
        self.assertEqual(stat.S_IMODE(handoff.stat().st_mode), 0o600)

    def test_sphere_sso_wait_blocks_horizon_and_preserves_reason(self):
        self.write_config(SPHERE_SSO_ACCEPTANCE_CONFIRMED="no")
        result = self.run_installer(expected=20)
        self.assertIn("SPHERE_SSO_ACCEPTANCE_CONFIRMED=yes", result.stderr)
        self.assertEqual(self.current_state(), "sphere-acceptance=waiting")
        self.assertNotIn("nereidhorizon", self.read_cluster()["releases"])
        self.assertIn(
            "SPHERE_SSO_ACCEPTANCE_CONFIRMED=yes",
            (self.deployment / "quick-install" / "state" / "wait-reason").read_text(),
        )

    def test_secret_query_error_never_generates_replacement_credentials(self):
        result = self.run_installer(
            expected=2,
            environment={"FAKE_KUBECTL_QUERY_ERROR": "secret:pg-nereidforge-pg-credentials"},
        )
        log = (self.deployment / "deploy-logs" / "quick-install" / "pre-artifact.log").read_text()
        self.assertIn("Could not query secret/pg-nereidforge-pg-credentials", log)
        self.assertNotIn("PG_ADMIN_PASSWORD=", self.pre_environment().read_text())
        self.assertNotIn("SEAWEEDFS_S3_ACCESS_KEY=", self.pre_environment().read_text())
        self.assertEqual(self.count_calls("pre\t10_infra"), 0)
        self.assertNotIn("nereidforge-backend", self.read_cluster()["releases"])
        self.assertNotIn("nereidlink", self.read_cluster()["releases"])
        self.assertEqual(self.current_state(), "pre-artifact=failed")

    def test_pre_query_failure_before_generation_can_retry_bootstrap(self):
        self.run_installer(
            expected=2,
            environment={"FAKE_KUBECTL_QUERY_ERROR": "secret:pg-nereidforge-pg-credentials"},
        )
        self.assertNotIn("PG_ADMIN_PASSWORD=", self.pre_environment().read_text())
        marker = (
            self.deployment / "quick-install" / "state" / "identity-initializations" / "pre-artifact"
        )
        self.assertFalse(marker.exists())

        self.run_installer(expected=20)

        self.assertEqual(self.current_state(), "forge-acceptance=waiting")
        self.assertIn("PG_ADMIN_PASSWORD=", self.pre_environment().read_text())
        self.assertTrue(marker.is_file())

    def test_pending_foreign_release_is_rejected_before_mutation(self):
        state = self.read_cluster()
        state["pending_releases"] = ["nereidsphere"]
        self.write_cluster(state)
        result = self.run_installer(expected=1)
        self.assertIn("existing NereidAI product releases", result.stderr)
        self.assertIn("helm\tlist\t-A\t--all\t-o\tjson", self.call_lines())
        self.assertEqual(self.count_calls("helm\tupgrade\t--install"), 0)
        self.assertFalse((self.deployment / "quick-install" / "state" / "cluster-context").exists())

    def test_existing_product_namespace_is_rejected_before_mutation(self):
        state = self.read_cluster()
        state["namespaces"].append("nereidhorizon")
        self.write_cluster(state)
        result = self.run_installer(expected=1)
        self.assertIn("namespace/nereidhorizon", result.stderr)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install"), 0)

    def assert_storage_smoke_refusal(self, *, query_error=False):
        if query_error:
            environment = {"FAKE_KUBECTL_QUERY_ERROR": "pvc:nereidai-quick-nfs-smoke"}
            expected_message = "Could not verify storage-smoke ownership"
        else:
            state = self.read_cluster()
            state["storage_smoke_owners"]["pvc"] = ""
            self.write_cluster(state)
            environment = None
            expected_message = "unlabeled or foreign"
        result = self.run_installer(expected=1, environment=environment)
        log = (self.deployment / "deploy-logs" / "quick-install" / "prerequisites.log").read_text()
        self.assertIn(expected_message, log)
        self.assertEqual(self.count_calls("kubectl\t-n\tdefault\tdelete"), 0)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereididentity\t"), 0)
        self.assertEqual(self.current_state(), "prerequisites=failed")

    def test_unlabeled_storage_smoke_resource_is_not_deleted(self):
        self.assert_storage_smoke_refusal()

    def test_storage_smoke_query_error_is_not_treated_as_absence(self):
        self.assert_storage_smoke_refusal(query_error=True)

    def test_private_kubeconfig_survives_shared_context_switch(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer(environment={"FAKE_SWITCH_SHARED_CONTEXT": "yes"})
        self.assertEqual(self.read_cluster()["shared_context"], "other-context")
        private = self.deployment / "quick-install" / "kubeconfig"
        self.assertIn("current-context: test-context", private.read_text())
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
        self.assertEqual(self.current_state(), "link=complete")

    def test_malformed_link_handoff_does_not_leak_source_into_logs(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer()
        handoff = self.deployment / "deploy-values" / "nereidforge" / "seaweedfs-credentials.yaml"
        canary = "do-not-print-this-handoff-line"
        handoff.write_text(f"accessKey: [unclosed\nsecretKey: {canary}\n", encoding="utf-8")
        handoff.chmod(0o600)

        self.run_installer()
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge-acceptance.log").read_text()
        self.assertIn("source content suppressed", log)
        self.assertNotIn(canary, log)
        self.assertEqual(self.current_state(), "link=complete")

    def test_link_completion_requires_migration_and_authenticated_bucket(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer(expected=1, environment={"FAKE_LINK_MIGRATION_COMPLETE": "no"})
        self.assertEqual(self.current_state(), "link=failed")
        self.assertFalse(self.marker("link").exists())

        self.run_installer(expected=1, environment={"FAKE_SKIP_LINK_BUCKET": "yes"})
        self.assertEqual(self.current_state(), "link=failed")
        self.assertFalse(self.marker("link").exists())
        log = (self.deployment / "deploy-logs" / "quick-install" / "link.log").read_text()
        self.assertIn("authenticated Link SeaweedFS bucket verification failed", log)

        self.run_installer()
        self.assertEqual(self.current_state(), "link=complete")
        self.assertTrue(self.marker("link").exists())

    def test_incomplete_secret_store_fails_closed_without_replacement(self):
        self.write_config(SPHERE_SSO_ACCEPTANCE_CONFIRMED="no")
        self.run_installer(expected=20)
        store = self.deployment / "secret-store" / "suite-secrets.json"
        document = json.loads(store.read_text(encoding="utf-8"))
        removed = document["secrets"].pop("identity.client.nereidsphere")
        self.assertTrue(removed)
        store.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        store.chmod(0o600)
        incomplete = store.read_bytes()
        self.marker("prerequisites").unlink()
        identity_calls = self.count_calls("helm\tupgrade\t--install\tnereididentity\t")

        result = self.run_installer(expected=1)

        self.assertEqual(store.read_bytes(), incomplete)
        self.assertEqual(
            self.count_calls("helm\tupgrade\t--install\tnereididentity\t"),
            identity_calls,
        )
        self.assertEqual(self.current_state(), "prerequisites=failed")
        log = (self.deployment / "deploy-logs" / "quick-install" / "prerequisites.log").read_text()
        self.assertIn("secret store is incomplete", log)
        self.assertIn("identity.client.nereidsphere", log)
        self.assertNotIn(removed, result.stdout + result.stderr + log)

    def test_missing_secret_store_on_resume_is_not_recreated(self):
        self.write_config(SPHERE_SSO_ACCEPTANCE_CONFIRMED="no")
        self.run_installer(expected=20)
        store = self.deployment / "secret-store" / "suite-secrets.json"
        original = store.read_bytes()
        self.marker("prerequisites").unlink()
        store.unlink()
        identity_calls = self.count_calls("helm\tupgrade\t--install\tnereididentity\t")

        result = self.run_installer(expected=1)

        self.assertFalse(store.exists())
        self.assertNotEqual(original, b"")
        self.assertEqual(
            self.count_calls("helm\tupgrade\t--install\tnereididentity\t"),
            identity_calls,
        )
        self.assertEqual(self.current_state(), "prerequisites=failed")
        log = (self.deployment / "deploy-logs" / "quick-install" / "prerequisites.log").read_text()
        self.assertIn("restore the canonical suite secret store", log)
        self.assertNotIn("Generated", result.stdout + result.stderr + log)

    def test_pre_identity_is_not_generated_after_initialized_state_loses_both_copies(self):
        self.run_installer(expected=1, environment={"FAKE_FAIL_PRE_KUBEFLOW": "yes"})
        state = self.read_cluster()
        state["secrets"].pop("nereidforge/pg-nereidforge-pg-credentials")
        self.write_cluster(state)
        self.marker("pre-artifact").unlink()
        lines = self.pre_environment().read_text().splitlines()
        self.pre_environment().write_text(
            "\n".join(line for line in lines if not line.startswith("PG_ADMIN_PASSWORD=")) + "\n",
            encoding="utf-8",
        )
        retained = self.pre_environment().read_bytes()
        infra_calls = self.count_calls("pre\t10_infra")

        result = self.run_installer(expected=1)

        self.assertEqual(self.pre_environment().read_bytes(), retained)
        self.assertNotIn("nereidforge/pg-nereidforge-pg-credentials", self.read_cluster()["secrets"])
        self.assertEqual(self.count_calls("pre\t10_infra"), infra_calls)
        self.assertEqual(self.current_state(), "pre-artifact=failed")
        log = (self.deployment / "deploy-logs" / "quick-install" / "pre-artifact.log").read_text()
        self.assertIn("restore pg_admin_password", log.lower())
        self.assertNotIn("Generated", result.stdout + result.stderr + log)

    def test_forge_initializes_missing_nf_sso_on_pre_owned_runtime_secret(self):
        result = self.run_installer(
            expected=20,
            environment={"FAKE_PRE_RUNTIME_WITHOUT_NF_SSO": "yes"},
        )

        self.assertEqual(self.current_state(), "forge-acceptance=waiting")
        self.assertIn("NF_LIVE_ACCEPTANCE_CONFIRMED=yes", result.stderr)
        runtime = self.read_cluster()["secrets"]["nereidforge/nereidforge-service-credentials"]
        store = json.loads(
            (self.deployment / "secret-store" / "suite-secrets.json").read_text()
        )
        expected_sso = store["secrets"]["sphere.ticket.forge"]
        self.assertEqual(runtime["NEREIDFORGE_SSO_NS_CLIENT_SECRET"], expected_sso)
        self.assertEqual(runtime["NEREIDFORGE_LABELSTUDIO_TOKEN"], "fake-pre-labelstudio-token")
        self.assertEqual(runtime["NEREIDFORGE_CVAT_TOKEN"], "fake-pre-cvat-token")
        self.assertTrue(runtime["NEREIDFORGE_AUTH_JWT_SECRET"])
        secret_dir = self.deployment / "secrets" / "nereidforge"
        self.assertEqual((secret_dir / "sso-client").read_text(), expected_sso)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t"), 1)

    def test_forge_rejects_a_different_existing_nf_sso_without_replacing_it(self):
        mismatched = "fake-different-forge-sso"
        result = self.run_installer(
            expected=1,
            environment={"FAKE_PRE_RUNTIME_SSO_OVERRIDE": mismatched},
        )

        self.assertEqual(self.current_state(), "forge=failed")
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge.log").read_text()
        self.assertIn("Forge runtime SSO identity differs from Sphere", log)
        runtime = self.read_cluster()["secrets"]["nereidforge/nereidforge-service-credentials"]
        self.assertEqual(runtime["NEREIDFORGE_SSO_NS_CLIENT_SECRET"], mismatched)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t"), 0)
        secret_dir = self.deployment / "secrets" / "nereidforge"
        self.assertFalse((secret_dir / "sso-client").exists())
        self.assertFalse((secret_dir / "jwt").exists())

    def test_nf_identity_is_not_generated_after_initialized_state_loses_both_copies(self):
        self.run_installer(expected=20)
        state = self.read_cluster()
        runtime = state["secrets"]["nereidforge/nereidforge-service-credentials"]
        runtime.pop("NEREIDFORGE_AUTH_JWT_SECRET")
        self.write_cluster(state)
        self.marker("forge").unlink()
        (self.deployment / "secrets" / "nereidforge" / "jwt").unlink()
        backend_calls = self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t")

        result = self.run_installer(expected=1)

        runtime_after = self.read_cluster()["secrets"]["nereidforge/nereidforge-service-credentials"]
        self.assertNotIn("NEREIDFORGE_AUTH_JWT_SECRET", runtime_after)
        self.assertEqual(
            self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t"),
            backend_calls,
        )
        self.assertEqual(self.current_state(), "forge=failed")
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge.log").read_text()
        self.assertIn("restore jwt", log.lower())
        self.assertNotIn("Generated", result.stdout + result.stderr + log)

    def test_nf_initialization_history_survives_later_early_stage_failure(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer(expected=1, environment={"FAKE_SKIP_PRE_RUNTIME_SECRET": "yes"})
        self.assertEqual(self.current_state(), "forge=failed")
        jwt = self.deployment / "secrets" / "nereidforge" / "jwt"
        self.assertTrue(jwt.is_file())
        self.assertFalse(self.marker("forge").exists())

        self.run_installer(
            expected=2,
            environment={"FAKE_KUBECTL_QUERY_ERROR": "crd:clusters.postgresql.cnpg.io"},
        )
        self.assertEqual(self.current_state(), "prerequisites=failed")
        jwt.unlink()

        self.run_installer(expected=1)

        self.assertEqual(self.current_state(), "forge=failed")
        self.assertFalse(jwt.exists())
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge.log").read_text()
        self.assertIn("restore jwt", log.lower())
        self.assertEqual(log.count("Retained NF secret inputs are ready"), 1)

    def test_resume_before_pre_stage_still_allows_first_identity_bootstrap(self):
        self.write_config(SPHERE_SSO_ACCEPTANCE_CONFIRMED="no")
        self.run_installer(expected=20)
        self.assertFalse(self.pre_environment().exists())

        self.write_config(SPHERE_SSO_ACCEPTANCE_CONFIRMED="yes", NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer()

        self.assertEqual(self.current_state(), "link=complete")
        self.assertIn("PG_ADMIN_PASSWORD=", self.pre_environment().read_text())
        self.assertTrue((self.deployment / "secrets" / "nereidforge" / "jwt").is_file())

    def test_not_found_substring_in_cnpg_query_error_is_not_absence(self):
        result = self.run_installer(
            expected=2,
            environment={
                "FAKE_KUBECTL_QUERY_ERROR": "crd:clusters.postgresql.cnpg.io",
                "FAKE_KUBECTL_QUERY_ERROR_MESSAGE": "executable credential-plugin not found",
            },
        )

        self.assertEqual(self.current_state(), "prerequisites=failed")
        self.assertEqual(self.count_calls("helm\tpull\tcloudnative-pg\t"), 0)
        self.assertEqual(self.count_calls("kubectl\tapply\t--server-side\t"), 0)
        self.assertNotIn("credential-plugin", result.stdout + result.stderr)

    def test_not_found_substring_in_storage_query_error_is_not_absence(self):
        self.run_installer(
            expected=1,
            environment={
                "FAKE_KUBECTL_QUERY_ERROR": "pvc:nereidai-quick-nfs-smoke",
                "FAKE_KUBECTL_QUERY_ERROR_MESSAGE": "executable credential-plugin not found",
            },
        )

        self.assertEqual(self.current_state(), "prerequisites=failed")
        self.assertEqual(self.count_calls("kubectl\t-n\tdefault\tdelete"), 0)
        log = (self.deployment / "deploy-logs" / "quick-install" / "prerequisites.log").read_text()
        self.assertIn("Could not verify storage-smoke ownership", log)

    def test_not_found_substring_in_nf_secret_query_error_stops_before_helm(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")

        self.run_installer(
            expected=1,
            environment={
                "FAKE_KUBECTL_QUERY_ERROR": "secret:nereidforge-service-credentials",
                "FAKE_KUBECTL_QUERY_ERROR_MESSAGE": "executable credential-plugin not found",
            },
        )

        self.assertEqual(self.current_state(), "forge=failed")
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t"), 0)
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge.log").read_text()
        self.assertIn("could not query retained Secret", log)

    def test_cnpg_query_error_never_enters_the_mutation_path(self):
        result = self.run_installer(
            expected=2,
            environment={"FAKE_KUBECTL_QUERY_ERROR": "crd:clusters.postgresql.cnpg.io"},
        )

        self.assertEqual(self.current_state(), "prerequisites=failed")
        self.assertEqual(self.count_calls("helm\tpull\tcloudnative-pg\t"), 0)
        self.assertEqual(self.count_calls("kubectl\tapply\t--server-side\t"), 0)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereididentity\t"), 0)
        log = (self.deployment / "deploy-logs" / "quick-install" / "prerequisites.log").read_text()
        self.assertIn("Could not query crd/clusters.postgresql.cnpg.io", log)
        self.assertNotIn("simulated Kubernetes API query failure", result.stdout)

    def test_colon_separated_kubeconfig_files_are_accepted(self):
        first = self.root / "kubeconfig-context.yaml"
        second = self.root / "kubeconfig-cluster.yaml"
        first.write_text(textwrap.dedent(
            """
            apiVersion: v1
            current-context: unrelated-context
            contexts:
              - name: test-context
                context:
                  cluster: test-cluster
                  user: test-user
            """
        ).lstrip(), encoding="utf-8")
        second.write_text(textwrap.dedent(
            """
            apiVersion: v1
            clusters:
              - name: test-cluster
                cluster:
                  server: https://cluster.invalid
            users:
              - name: test-user
                user: {}
            """
        ).lstrip(), encoding="utf-8")
        self.write_config(
            NF_LIVE_ACCEPTANCE_CONFIRMED="yes",
            KUBECONFIG=f"{first}{os.pathsep}{second}",
        )

        self.run_installer()

        private = self.deployment / "quick-install" / "kubeconfig"
        self.assertIn("current-context: test-context", private.read_text())
        self.assertEqual(self.current_state(), "link=complete")

    def test_verifier_override_uses_immutable_commit_without_changing_chart(self):
        verifier_ref = "abcdef1" + "a" * 33
        self.write_config(NF_VERIFIER_REF=verifier_ref)

        self.run_installer(expected=20)

        self.assertEqual(self.current_state(), "forge-acceptance=waiting")
        verifier = self.deployment / "verifiers" / (
            f"nereidforge-0.0.0-dev-abcdef1-verifier-{verifier_ref}"
        )
        self.assertTrue((verifier / "scripts" / "60_verify" / "nf-check.sh").is_file())
        self.assertTrue(any(
            line.startswith("git\t-C\t")
            and line.endswith(f"\tcheckout\t--detach\t{verifier_ref}")
            for line in self.call_lines()
        ))
        self.assertFalse(
            (self.deployment / "verifiers" / "nereidforge-0.0.0-dev-abcdef1").exists()
        )
        self.assertEqual(self.read_cluster()["chart_version"], "0.0.0-dev-abcdef1")

    def test_verifier_override_rejects_mutable_or_malformed_references(self):
        for verifier_ref in ("main", "abcdef1", "A" * 40, "g" * 40, "a" * 41):
            with self.subTest(verifier_ref=verifier_ref):
                self.write_config(NF_VERIFIER_REF=verifier_ref)
                result = self.run_installer(expected=1)
                self.assertIn("NF_VERIFIER_REF", result.stderr)
                self.assertIn("40", result.stderr)
        self.assertEqual(self.count_calls("git\tclone\t"), 0)
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\t"), 0)

    def test_completed_acceptance_rejects_changed_verifier_ref(self):
        verifier_ref = "abcdef1" + "a" * 33
        self.write_config(
            NF_VERIFIER_REF=verifier_ref,
            NF_LIVE_ACCEPTANCE_CONFIRMED="yes",
        )
        self.run_installer()
        self.assertEqual(self.current_state(), "link=complete")
        self.assertEqual(self.count_calls("git\tclone\t"), 1)

        self.write_config(
            NF_VERIFIER_REF="abcdef1" + "b" * 33,
            NF_LIVE_ACCEPTANCE_CONFIRMED="yes",
        )
        result = self.run_installer(expected=1)

        self.assertEqual(self.current_state(), "forge-acceptance=blocked-config-change")
        self.assertIn("completed with different inputs", result.stderr)
        self.assertEqual(self.count_calls("git\tclone\t"), 1)

    def test_interrupted_verifier_clone_is_fetched_and_resumed(self):
        verifier = self.deployment / "verifiers" / "nereidforge-0.0.0-dev-abcdef1"
        (verifier / ".git").mkdir(parents=True)

        self.run_installer(expected=20)

        self.assertEqual(self.current_state(), "forge-acceptance=waiting")
        self.assertEqual(self.count_calls("git\tclone\t"), 0)
        self.assertEqual(self.count_calls(f"git\t-C\t{verifier}\tfetch\t"), 1)
        self.assertEqual(self.count_calls("nf\t60_verify/nf-check"), 1)
        self.assertTrue((verifier / "scripts" / "60_verify" / "nf-check.sh").is_file())

        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")
        self.run_installer()
        self.assertEqual(self.current_state(), "link=complete")
        self.assertEqual(self.count_calls(f"git\t-C\t{verifier}\tfetch\t"), 1)

    def test_link_migration_ignores_failed_old_revision(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")

        self.run_installer(environment={"FAKE_LINK_OLD_FAILED_MIGRATION": "yes"})

        self.assertEqual(self.current_state(), "link=complete")
        self.assertTrue(self.marker("link").exists())

    def test_link_migration_rejects_current_revision_without_migration(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")

        self.run_installer(
            expected=1,
            environment={"FAKE_LINK_OLD_SUCCESS_CURRENT_WITHOUT_MIGRATION": "yes"},
        )

        self.assertEqual(self.current_state(), "link=failed")
        self.assertFalse(self.marker("link").exists())
        log = (self.deployment / "deploy-logs" / "quick-install" / "link.log").read_text()
        self.assertIn("current Link Deployment", log)

    def test_missing_pre_runtime_secret_stops_before_forge_helm(self):
        self.write_config(NF_LIVE_ACCEPTANCE_CONFIRMED="yes")

        self.run_installer(expected=1, environment={"FAKE_SKIP_PRE_RUNTIME_SECRET": "yes"})

        self.assertEqual(self.current_state(), "forge=failed")
        self.assertEqual(self.count_calls("helm\tupgrade\t--install\tnereidforge-backend\t"), 0)
        self.assertNotIn("nereidforge/nereidforge-service-credentials", self.read_cluster()["secrets"])
        log = (self.deployment / "deploy-logs" / "quick-install" / "forge.log").read_text()
        self.assertIn("NotFound", log)


if __name__ == "__main__":
    unittest.main()
