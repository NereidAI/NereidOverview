#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import argparse
from contextlib import redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest

import yaml

MODULE_PATH = Path(__file__).parents[1] / "generate-suite-secrets.py"
SPEC = importlib.util.spec_from_file_location("generate_suite_secrets", MODULE_PATH)
assert SPEC and SPEC.loader
TOOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TOOL)


class GenerateSuiteSecretsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "deployment"
        self.root.mkdir(mode=0o700)
        self.store, generated = TOOL.initialize_store(self.root)
        self.assertEqual(generated, len(TOOL.SECRET_GENERATORS))
        self.generated = json.loads(self.store.read_text())["secrets"]

    def tearDown(self):
        self.temporary.cleanup()

    def site_values(self, product):
        directory = self.root / "deploy-values" / product
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / "site-values.yaml"

    def write_site(self, product, values):
        path = self.site_values(product)
        path.write_text(yaml.safe_dump(values, sort_keys=False))
        return path

    def render(self, product, values, forge=False, force=False):
        source = self.write_site(product, values)
        args = argparse.Namespace(
            deployment_root=self.root,
            input=source,
            output=None,
            product=product,
            force=force,
            forge_credentials=None,
        )
        if forge:
            credentials = self.root / "secret-store" / "forge-seaweedfs.yaml"
            credentials.write_text("accessKey: forge-access\nsecretKey: forge-secret\n")
            credentials.chmod(0o600)
            args.forge_credentials = credentials
        output = TOOL.render_values(args)
        return output, yaml.safe_load(output.read_text())

    def test_initialization_is_private_idempotent_and_unique(self):
        first_bytes = self.store.read_bytes()
        _, generated = TOOL.initialize_store(self.root)
        self.assertEqual(generated, 0)
        self.assertEqual(self.store.read_bytes(), first_bytes)
        self.assertEqual(stat.S_IMODE(self.store.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.store.parent.stat().st_mode), 0o700)
        self.assertEqual(len(set(self.generated.values())), len(self.generated))
        self.assertEqual(len(self.generated["sphere.session_key"].encode()), 32)

    def test_identity_and_sphere_share_exact_credentials(self):
        _, identity = self.render("nereididentity", {})
        sphere_site = {
            "valkey": {"enabled": True},
            "config": {
                "products": [
                    {"id": "forge", "url": "https://forge.example.org"},
                    {"id": "horizon", "url": "https://horizon.example.org"},
                    {"id": "link", "url": "https://link.example.org"},
                ]
            },
        }
        sphere_path, sphere = self.render("nereidsphere", sphere_site)
        self.assertEqual(
            sphere["config"]["oidc"]["clientSecret"],
            identity["identity"]["clients"]["nereidsphere"]["secret"],
        )
        self.assertEqual(
            sphere["config"]["oidc"]["adminClientSecret"],
            identity["identity"]["adminClient"]["secret"],
        )
        tickets = [entry["ssoSecret"] for entry in sphere["config"]["products"]]
        self.assertEqual(len(set(tickets)), 3)
        self.assertEqual(len(sphere["config"]["session"]["secretKey"]), 32)
        self.assertEqual(stat.S_IMODE(sphere_path.stat().st_mode), 0o600)
        original = yaml.safe_load(self.site_values("nereidsphere").read_text())
        self.assertTrue(all("ssoSecret" not in entry for entry in original["config"]["products"]))

    def test_horizon_and_link_consume_matching_ticket_secrets(self):
        sphere_site = {
            "config": {
                "products": [{"id": product} for product in ("forge", "horizon", "link")]
            }
        }
        _, sphere = self.render("nereidsphere", sphere_site)
        sphere_tickets = {entry["id"]: entry["ssoSecret"] for entry in sphere["config"]["products"]}

        _, horizon = self.render(
            "nereidhorizon",
            {"postgres": {"enabled": True}, "ns": {"enabled": True}, "oidc": {"enabled": True}},
        )
        self.assertEqual(horizon["ns"]["clientSecret"], sphere_tickets["horizon"])
        self.assertEqual(
            horizon["oidc"]["clientSecret"], self.generated["identity.client.nereidhorizon"]
        )

        _, link = self.render(
            "nereidlink",
            {"postgresql": {"mode": "bundled"}, "sso": {"enabled": True}},
            forge=True,
        )
        self.assertEqual(link["sso"]["ssoSecret"], sphere_tickets["link"])
        self.assertEqual(link["blob"]["accessKey"], "forge-access")
        self.assertEqual(link["blob"]["secretKey"], "forge-secret")
        self.assertNotIn("forge-access", self.store.read_text())
        self.assertNotIn("forge-secret", self.store.read_text())

    def test_render_preserves_store_and_requires_force_for_output(self):
        before = self.store.read_bytes()
        output, _ = self.render("nereididentity", {})
        with self.assertRaises(TOOL.SecretToolError):
            self.render("nereididentity", {})
        self.render("nereididentity", {}, force=True)
        self.assertTrue(output.exists())
        self.assertEqual(self.store.read_bytes(), before)

    def test_link_requires_real_forge_handoff(self):
        with self.assertRaisesRegex(TOOL.SecretToolError, "forge-credentials"):
            self.render("nereidlink", {})

    def test_forge_handoff_rejects_extra_keys_and_placeholders(self):
        with self.assertRaisesRegex(TOOL.SecretToolError, "exactly accessKey and secretKey"):
            TOOL.render_link(
                {},
                self.generated,
                {"accessKey": "forge-access", "secretKey": "forge-secret", "extra": "unexpected"},
            )
        for key in ("accessKey", "secretKey"):
            with self.subTest(key=key):
                credentials = {"accessKey": "forge-access", "secretKey": "forge-secret"}
                credentials[key] = "<exact-Forge-credential-placeholder>"
                with self.assertRaisesRegex(TOOL.SecretToolError, f"placeholder in {key}"):
                    TOOL.render_link({}, self.generated, credentials)

    def test_malformed_private_yaml_does_not_disclose_source_excerpts(self):
        source = self.write_site("nereidlink", {})
        credentials = self.root / "secret-store" / "forge-seaweedfs.yaml"
        credentials.write_text(
            'accessKey: "actual-forge-access"\nsecretKey: "actual-forge-secret\n'
        )
        credentials.chmod(0o600)
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            exit_code = TOOL.main(
                [
                    "render",
                    "--deployment-root",
                    str(self.root),
                    "--product",
                    "nereidlink",
                    "--input",
                    str(source),
                    "--forge-credentials",
                    str(credentials),
                ]
            )
        self.assertEqual(exit_code, 1)
        self.assertNotIn("actual-forge-access", stderr.getvalue())
        self.assertNotIn("actual-forge-secret", stderr.getvalue())
        self.assertIn("source excerpt suppressed", stderr.getvalue())
        self.assertIn("line", stderr.getvalue())

    def test_group_access_to_secret_store_is_rejected(self):
        self.store.chmod(0o640)
        with self.assertRaisesRegex(TOOL.SecretToolError, "chmod 600"):
            TOOL.initialize_store(self.root)

    def test_sphere_requires_all_ticket_entries(self):
        with self.assertRaisesRegex(TOOL.SecretToolError, "missing id="):
            self.render("nereidsphere", {"config": {"products": [{"id": "horizon"}]}})


if __name__ == "__main__":
    unittest.main()
