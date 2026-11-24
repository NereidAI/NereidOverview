#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).parents[2]
LOADER = ROOT / "scripts" / "load-deployment-env.sh"
VERSION = "0.0.0-dev-abcdef1"
SOURCE_REVISION = "abcdef1" + "a" * 33
SECOND_VERSION = "0.0.0-dev-bbcdef2"
SECOND_SOURCE_REVISION = "bbcdef2" + "b" * 33
DIGEST = "sha256:" + "1" * 64


def make_oras(directory):
    oras = directory / "oras"
    oras.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="$1"
shift
if [[ "$command" == manifest ]]; then
  test "$1" = fetch
  shift
fi
output=""
registry_config=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --registry-config) registry_config="$2"; shift 2 ;;
    *) shift ;;
  esac
done
case "$registry_config" in
  "$DEPLOYMENT_ROOT"/anonymous-registry.*/oras.json) ;;
  *) echo "missing isolated ORAS config: $registry_config" >&2; exit 3 ;;
esac
case "$command" in
  resolve) printf '%s\\n' "$FAKE_DIGEST" ;;
  manifest) cat "$FAKE_REGISTRY/manifest.json" ;;
  pull)
    test -n "$output"
    find "$FAKE_REGISTRY" -maxdepth 1 -type f \
      -name 'pre-nereidforge-*' -exec cp -t "$output" {} +
    ;;
  *) echo "unexpected fake oras command: $command" >&2; exit 2 ;;
esac
"""
    )
    oras.chmod(0o755)


def run_bash(script, environment):
    return subprocess.run(["bash", "-c", script], env=environment, capture_output=True, text=True)


class PersistentEnvironmentTest(unittest.TestCase):
    def test_runbook_environment_restores_resolved_identities_and_helpers(self):
        runbook = (ROOT / "docs" / "deploy" / "install-suite.md").read_text()
        body = runbook.split("cat <<'EOF'\n", 1)[1].split("\nEOF", 1)[0]
        with tempfile.TemporaryDirectory() as temporary:
            deployment = Path(temporary)
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            release.mkdir(parents=True)
            (release / "resolved-version.txt").write_text(VERSION + "\n")
            (release / "source-commit.txt").write_text(SOURCE_REVISION + "\n")
            (release / f"nf-resolved-version-0.0.0-dev.txt").write_text(SECOND_VERSION + "\n")
            (deployment / "deployment.env").write_text(
                f"export DEPLOYMENT_ROOT={shlex.quote(str(deployment))}\n{body}\n"
            )
            script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
test "$PRE_RESOLVED_VERSION" = {VERSION}
test "$NEREIDFORGE_RESOLVED_VERSION" = {SECOND_VERSION}
test "$PRE_ROOT" = "$PRE_RELEASE_DIR/pre-nereidforge-installer-{VERSION}"
type pull_nereid_chart >/dev/null
type pull_pre_nereidforge_installer >/dev/null
type record_nereid_images >/dev/null
"""
            result = run_bash(script, os.environ.copy())
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class PreInstallerHelperTest(unittest.TestCase):
    def make_registry(self, registry, version=VERSION, revision=SOURCE_REVISION):
        registry.mkdir(parents=True)
        archive_name = f"pre-nereidforge-installer-{version}.tar.gz"
        installer_root = registry / "tree" / f"pre-nereidforge-installer-{version}"
        installer_root.mkdir(parents=True)
        (installer_root / "install-lock.json").write_text('{"version": "test"}\n')
        archive = registry / archive_name
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(installer_root, arcname=installer_root.name)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (registry / f"{archive_name}.sha256").write_text(f"{digest}  {archive_name}\n")
        (registry / f"pre-nereidforge-installer-{version}.lock.json").write_text(
            json.dumps({"version": version, "charts": [{}] * 5}) + "\n"
        )
        (registry / f"pre-nereidforge-charts-{version}.txt").write_text("test chart manifest\n")
        (registry / "manifest.json").write_text(
            json.dumps(
                {
                    "annotations": {
                        "org.opencontainers.image.version": version,
                        "org.opencontainers.image.revision": revision,
                    }
                }
            )
        )

    def make_environment(self, deployment):
        (deployment / "deployment.env").write_text(
            "\n".join(
                [
                    f"export DEPLOYMENT_ROOT={shlex.quote(str(deployment))}",
                    'export DEPLOY_VALUES_ROOT="$DEPLOYMENT_ROOT/deploy-values"',
                    'export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"',
                    "export PRE_VERSION=0.0.0-dev",
                    'export PRE_HANDOFF_DIR="$DEPLOY_VALUES_ROOT/nereidforge"',
                    'export PRE_RELEASE_DIR="$DEPLOYMENT_ROOT/pre-nereidforge/$PRE_VERSION"',
                ]
            )
            + "\n"
        )

    def pull(self, deployment, fake_bin, registry, digest):
        script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
PRE_ROOT="$(pull_pre_nereidforge_installer "$PRE_VERSION")"
test -s "$PRE_ROOT/install-lock.json"
printf '%s\\n' "$PRE_ROOT"
"""
        environment = os.environ.copy()
        environment.update(
            PATH=f"{fake_bin}:{environment['PATH']}",
            FAKE_REGISTRY=str(registry),
            FAKE_DIGEST=digest,
        )
        return run_bash(script, environment)

    def test_helper_returns_only_root_and_supports_a_moved_floating_selector(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_registry = root / "registry-one"
            second_registry = root / "registry-two"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(first_registry)
            self.make_registry(second_registry, SECOND_VERSION, SECOND_SOURCE_REVISION)
            make_oras(fake_bin)

            first = self.pull(deployment, fake_bin, first_registry, DIGEST)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            first_root = deployment / "pre-nereidforge" / "0.0.0-dev" / f"pre-nereidforge-installer-{VERSION}"
            self.assertEqual(first.stdout.strip(), str(first_root))
            self.assertEqual(
                (deployment / "pre-nereidforge" / "0.0.0-dev" / "source-commit.txt").read_text().strip(),
                SOURCE_REVISION,
            )

            second = self.pull(deployment, fake_bin, second_registry, "sha256:" + "2" * 64)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            second_root = deployment / "pre-nereidforge" / "0.0.0-dev" / f"pre-nereidforge-installer-{SECOND_VERSION}"
            self.assertEqual(second.stdout.strip(), str(second_root))
            self.assertTrue(first_root.is_dir())
            self.assertTrue(second_root.is_dir())
            artifacts = deployment / "pre-nereidforge" / "0.0.0-dev" / "artifacts"
            self.assertEqual({path.name for path in artifacts.iterdir()}, {VERSION, SECOND_VERSION})
            for version in (VERSION, SECOND_VERSION):
                self.assertEqual(len(list((artifacts / version).iterdir())), 4)
            self.assertEqual(
                (deployment / "pre-nereidforge" / "0.0.0-dev" / "resolved-version.txt").read_text().strip(),
                SECOND_VERSION,
            )

    def test_source_revision_must_match_the_immutable_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry, revision="b" * 40)
            make_oras(fake_bin)
            result = self.pull(deployment, fake_bin, registry, DIGEST)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match source revision", result.stderr)


class ChartHelperTest(unittest.TestCase):
    def make_helm(self, directory):
        helm = directory / "helm"
        helm.write_text(
            """#!/usr/bin/env bash
set -euo pipefail
case "$HELM_REGISTRY_CONFIG" in
  "$DEPLOYMENT_ROOT"/anonymous-registry.*/helm.json) ;;
  *) echo "missing isolated Helm config" >&2; exit 3 ;;
esac
if [[ "$1" == pull ]]; then
  repository="$2"
  shift 2
  selector=""
  destination=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version) selector="$2"; shift 2 ;;
      --destination) destination="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  product="${repository##*/}"
  printf 'archive\\n' > "$destination/${product}-${selector}.tgz"
elif [[ "$1" == show && "$2" == chart ]]; then
  printf 'name: nereidforge-backend\\nversion: %s\\nappVersion: "%s"\\n' \
    "$FAKE_CHART_VERSION" "$FAKE_CHART_VERSION"
else
  echo "unexpected fake helm command: $*" >&2
  exit 2
fi
"""
        )
        helm.chmod(0o755)

    def test_immutable_selector_must_match_the_archive_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            (deployment / "deployment.env").write_text(
                "\n".join(
                    [
                        f"export DEPLOYMENT_ROOT={shlex.quote(str(deployment))}",
                        'export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"',
                        f"export NEREIDFORGE_VERSION={SECOND_VERSION}",
                    ]
                )
                + "\n"
            )
            script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
pull_nereid_chart nereidforge-backend "$NEREIDFORGE_VERSION"
"""
            environment = os.environ.copy()
            environment.update(
                PATH=f"{fake_bin}:{environment['PATH']}",
                FAKE_REGISTRY=str(root),
                FAKE_DIGEST=DIGEST,
                FAKE_CHART_VERSION=VERSION,
            )
            result = run_bash(script, environment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resolved to unexpected version", result.stderr)


if __name__ == "__main__":
    unittest.main()
