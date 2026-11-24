#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock

import yaml

MODULE_PATH = Path(__file__).parents[1] / "render-suite-site-values.py"
SPEC = importlib.util.spec_from_file_location("render_suite_site_values", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)

SECRET_VALUE_KEYS = {
    "accessKey",
    "adminClientSecret",
    "apiKey",
    "clientSecret",
    "externalDSN",
    "jwtSecret",
    "password",
    "passwordBcrypt",
    "secret",
    "secretKey",
    "ssoSecret",
}


class RenderSuiteSiteValuesTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = {
            "BASE_DOMAIN": "example.org",
            "STORAGE_CLASS": "nfs-csi",
            "LOCAL_STORAGE_CLASS": "local-path",
            "INGRESS_CLASS": "traefik",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, product, output, environment):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, environment, clear=True):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = TOOL.main(["--product", product, "--output", str(output)])
        return status, stdout.getvalue(), stderr.getvalue()

    def render(self, product, environment=None, output=None):
        output = output or self.root / product / "site-values.yaml"
        environment = self.environment if environment is None else environment
        status, stdout, stderr = self.invoke(product, output, environment)
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        values = yaml.safe_load(output.read_text(encoding="utf-8"))
        self.assert_no_secret_values(values)
        return output, values

    def assert_no_secret_values(self, values):
        def visit(node, path=""):
            if isinstance(node, dict):
                for key, value in node.items():
                    location = f"{path}.{key}" if path else key
                    if key in SECRET_VALUE_KEYS and value not in (None, ""):
                        self.fail(f"secret value rendered at {location}")
                    visit(value, location)
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    visit(value, f"{path}[{index}]")

        visit(values)

    def test_identity_has_actual_ingress_clients_admin_and_storage(self):
        _, values = self.render("nereididentity")
        ingress = values["keycloak"]["ingress"]
        self.assertEqual(ingress["ingressClassName"], "traefik")
        self.assertEqual(
            ingress["rules"],
            [{"host": "sso.example.org", "paths": [{"path": "/auth/", "pathType": "Prefix"}]}],
        )
        self.assertEqual(ingress["tls"], [{"hosts": ["sso.example.org"], "secretName": "keycloak-tls"}])

        identity = values["identity"]
        self.assertFalse(identity["seedUsers"])
        self.assertEqual(
            identity["suiteAdmin"],
            {
                "username": "admin",
                "email": "admin@nereidai.local",
                "firstName": "Admin",
                "lastName": "User",
            },
        )
        expected_callbacks = {
            "nereidsphere": ["/auth/callback"],
            "nereidhorizon": ["/api/oidc/callback"],
            "nereidforge": ["/auth/callback"],
            "nereidlink": ["/v1/auth/oidc/callback", "/auth/callback"],
        }
        for product, callbacks in expected_callbacks.items():
            with self.subTest(product=product):
                origin = f"https://{product}.example.org"
                self.assertEqual(
                    identity["clients"][product]["redirectUris"],
                    [origin + callback for callback in callbacks],
                )
                self.assertEqual(identity["clients"][product]["webOrigins"], [origin])
        self.assertEqual(values["postgresql"]["cluster"]["storage"]["storageClass"], "nfs-csi")

    def test_identity_admin_fields_can_be_overridden(self):
        environment = self.environment | {
            "SUITE_ADMIN_USERNAME": "suite-operator",
            "SUITE_ADMIN_EMAIL": "operator@example.org",
            "SUITE_ADMIN_FIRST_NAME": "Suite",
            "SUITE_ADMIN_LAST_NAME": "Operator",
        }
        _, values = self.render("nereididentity", environment)
        self.assertEqual(
            values["identity"]["suiteAdmin"],
            {
                "username": "suite-operator",
                "email": "operator@example.org",
                "firstName": "Suite",
                "lastName": "Operator",
            },
        )

    def test_sphere_single_replica_uses_memory_and_disables_pdb(self):
        _, values = self.render("nereidsphere")
        self.assertEqual(values["replicaCount"], 1)
        self.assertEqual(values["valkey"], {"enabled": False})
        self.assertEqual(values["tickets"], {"replayStore": "memory"})
        self.assertFalse(values["podDisruptionBudget"]["enabled"])
        self.assert_sphere_contract(values)

    def test_sphere_multiple_replicas_use_valkey_and_enable_pdb(self):
        environment = self.environment | {"SPHERE_REPLICAS": "3"}
        _, values = self.render("nereidsphere", environment)
        self.assertEqual(values["replicaCount"], 3)
        self.assertEqual(values["valkey"], {"enabled": True})
        self.assertEqual(values["tickets"], {"replayStore": "valkey"})
        self.assertTrue(values["podDisruptionBudget"]["enabled"])
        self.assert_sphere_contract(values)

    def assert_sphere_contract(self, values):
        self.assertEqual(values["config"]["server"]["baseUrl"], "https://nereidsphere.example.org")
        self.assertEqual(
            values["config"]["oidc"],
            {
                "issuer": "https://sso.example.org/auth/realms/nereidai",
                "clientId": "nereidsphere",
                "adminClientId": "nereidsphere-admin",
                "caBundleSecret": "nereid-internal-ca-tls",
            },
        )
        self.assertEqual(
            values["config"]["products"],
            [
                {
                    "id": "forge",
                    "name": "NereidForge",
                    "description": "Model factory",
                    "url": "https://nereidforge.example.org",
                    "mode": "ns",
                    "oidcClientId": "nereidforge",
                    "tenantsPath": "/v1/integration/ns/tenants",
                },
                {
                    "id": "horizon",
                    "name": "NereidHorizon",
                    "description": "Edge distribution",
                    "url": "https://nereidhorizon.example.org",
                    "mode": "ns",
                    "oidcClientId": "nereidhorizon",
                    "tenantsPath": "/v1/integration/ns/tenants",
                },
                {
                    "id": "link",
                    "name": "NereidLink",
                    "description": "IoT platform",
                    "url": "https://nereidlink.example.org",
                    "mode": "ns",
                    "oidcClientId": "nereidlink",
                    "tenantsPath": "/v1/integration/ns/tenants",
                },
            ],
        )
        self.assertEqual(values["ingress"]["hosts"][0]["host"], "nereidsphere.example.org")
        self.assertEqual(values["ingress"]["tls"][0]["secretName"], "nereidsphere-tls")

    def test_horizon_uses_local_postgres_sphere_and_actual_ingress(self):
        _, values = self.render("nereidhorizon")
        self.assertEqual(values["global"], {"imagePullSecrets": []})
        self.assertEqual(values["postgres"]["persistence"]["storageClass"], "local-path")
        self.assertEqual(
            values["ns"],
            {
                "enabled": True,
                "baseUrl": "https://nereidsphere.example.org",
                "productId": "horizon",
                "callbackPath": "/auth/ns-callback",
                "caBundleSecret": "nereid-internal-ca-tls",
                "caBundleKey": "ca.crt",
            },
        )
        self.assertEqual(values["ingress"]["host"], "nereidhorizon.example.org")
        self.assertEqual(
            values["ingress"]["tls"], {"enabled": True, "secretName": "nereidhorizon-tls"}
        )

    def test_link_has_single_tiers_storage_forge_sso_and_mqtt_sans(self):
        environment = self.environment | {"LINK_MQTTS_HOST": "mqtt.example.org"}
        _, values = self.render("nereidlink", environment)
        self.assertEqual(values["replicaCount"], 1)
        self.assertEqual(values["frontend"]["replicaCount"], 1)
        self.assertEqual(values["imagePullSecrets"], [])
        self.assertEqual(values["registryCredentials"], {"create": False})
        self.assertEqual(values["ingress"]["host"], "nereidlink.example.org")
        self.assertEqual(values["postgresql"], {"mode": "bundled", "storageClass": "local-path"})
        self.assertEqual(
            values["nats"],
            {"enabled": True, "replicas": 1, "jetstreamReplicas": 1, "storageClass": "local-path"},
        )
        self.assertEqual(values["persistence"], {"storageClass": "nfs-csi"})
        self.assertEqual(
            values["blob"],
            {
                "endpoint": "seaweedfs-s3.nereidforge.svc.cluster.local:8333",
                "publicEndpoint": "seaweedfs-s3.nereidforge.example.org:443",
                "bucket": "nereidlink",
                "secure": False,
                "publicSecure": True,
            },
        )
        self.assertEqual(values["sso"]["nsBaseURL"], "https://nereidsphere.example.org")
        self.assertEqual(values["sso"]["clientID"], "link")
        self.assertEqual(values["sso"]["caBundleSecret"], "nereid-internal-ca-tls")
        self.assertEqual(
            values["pki"]["serverHosts"],
            [
                "localhost",
                "127.0.0.1",
                "nereidlink",
                "nereidlink.nereidlink.svc.cluster.local",
                "nereidlink.example.org",
                "mqtt.example.org",
            ],
        )

    def test_deterministic_rerun_preserves_inode_when_unchanged(self):
        output, _ = self.render("nereididentity")
        first_bytes = output.read_bytes()
        first_inode = output.stat().st_ino
        second_output, _ = self.render("nereididentity", output=output)
        self.assertEqual(second_output.read_bytes(), first_bytes)
        self.assertEqual(second_output.stat().st_ino, first_inode)

    def test_output_is_regular_and_private_with_private_parent(self):
        output, _ = self.render("nereidhorizon")
        self.assertTrue(stat.S_ISREG(output.stat().st_mode))
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(output.parent.stat().st_mode), 0o700)

    def test_link_requires_mqtts_host_without_disclosing_environment(self):
        output = self.root / "missing-host" / "site-values.yaml"
        status, stdout, stderr = self.invoke("nereidlink", output, self.environment)
        self.assertEqual(status, 1)
        self.assertEqual(stdout, "")
        self.assertIn("LINK_MQTTS_HOST", stderr)
        self.assertNotIn("example.org", stderr)
        self.assertNotIn("nfs-csi", stderr)
        self.assertFalse(output.exists())

    def test_invalid_sphere_replicas_names_variable(self):
        for replicas in ("0", "not-an-integer"):
            with self.subTest(replicas=replicas):
                environment = self.environment | {"SPHERE_REPLICAS": replicas}
                output = self.root / replicas / "site-values.yaml"
                status, stdout, stderr = self.invoke("nereidsphere", output, environment)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, "")
                self.assertIn("SPHERE_REPLICAS", stderr)
                self.assertNotIn(replicas, stderr)
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
