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
RUNNER = ROOT / "scripts" / "lib" / "suite-runner.sh"
ARTIFACTS = ROOT / "scripts" / "lib" / "suite-artifacts.sh"
VERSION = "0.0.0-dev-abcdef1"
SOURCE_REVISION = "abcdef1" + "a" * 33
SECOND_VERSION = "0.0.0-dev-bbcdef2"
SECOND_SOURCE_REVISION = "bbcdef2" + "b" * 33
DIGEST = "sha256:" + "1" * 64
SECOND_DIGEST = "sha256:" + "2" * 64


def make_oras(directory):
    oras = directory / "oras"
    oras.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
command="$1"
shift
if [[ "$command" == manifest || "$command" == blob ]]; then
  test "$1" = fetch
  shift
fi
output=""
registry_config=""
reference=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) output="$2"; shift 2 ;;
    --registry-config) registry_config="$2"; shift 2 ;;
    *) reference="$1"; shift ;;
  esac
done
case "$registry_config" in
  "$DEPLOYMENT_ROOT"/anonymous-registry.*/oras.json) ;;
  *) echo "missing isolated ORAS config: $registry_config" >&2; exit 3 ;;
esac
if [[ -n "${FAKE_CALLS:-}" ]]; then
  printf '%s %s\\n' "$command" "$reference" >> "$FAKE_CALLS"
fi
if [[ "$command" == resolve && "${FAKE_FAIL_RESOLVE:-0}" == 1 ]]; then
  echo "simulated registry resolve failure" >&2
  exit 42
fi
case "$command" in
  resolve) printf '%s\\n' "${FAKE_RESOLVE_DIGEST:-$FAKE_DIGEST}" ;;
  manifest)
    [[ "$reference" == *@"$FAKE_DIGEST" ]] || {
      echo "manifest was not retrieved by retained digest: $reference" >&2; exit 4;
    }
    if [[ "$reference" == *pre-nereidforge-installer@* ]]; then
      cat "$FAKE_REGISTRY/manifest.json"
    else
      cat "$FAKE_REGISTRY/chart-manifest.json"
    fi
    ;;
  pull)
    test -n "$output"
    [[ "$reference" == *@"$FAKE_DIGEST" ]] || {
      echo "pre archive was not retrieved by retained digest: $reference" >&2; exit 4;
    }
    if [[ "${FAKE_FAIL_PULL:-0}" == 1 ]]; then
      echo "simulated interrupted pre pull" >&2; exit 42
    fi
    find "$FAKE_REGISTRY" -maxdepth 1 -type f \
      -name 'pre-nereidforge-*' -exec cp -t "$output" {} +
    ;;
  blob)
    test -n "$output"
    [[ "$reference" == *@"$FAKE_LAYER_DIGEST" ]] || {
      echo "chart blob was not retrieved by layer digest: $reference" >&2; exit 4;
    }
    if [[ "${FAKE_FAIL_BLOB:-0}" == 1 ]]; then
      echo "simulated interrupted chart blob fetch" >&2; exit 42
    fi
    if [[ "${FAKE_CORRUPT_BLOB:-0}" == 1 ]]; then
      printf 'corrupt chart blob\\n' > "$output"
    else
      cp "$FAKE_REGISTRY/chart-archive.tgz" "$output"
    fi
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

    def test_explicit_environment_file_can_live_outside_the_default_root_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            deployment = root / "deployment"
            deployment.mkdir()
            custom = root / "custom.env"
            custom.write_text(
                f"export DEPLOYMENT_ROOT={shlex.quote(str(deployment))}\n"
                "export NEREIDFORGE_VERSION=0.0.0-dev\n"
            )
            script = f"""
set -euo pipefail
DEPLOYMENT_ENV_FILE={shlex.quote(str(custom))}
source {shlex.quote(str(LOADER))}
test "$NEREIDFORGE_VERSION" = 0.0.0-dev
type pull_nereid_chart >/dev/null
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

    def pre_environment(self, deployment, fake_bin, registry, digest, overrides=None):
        environment = os.environ.copy()
        environment.update(
            PATH=f"{fake_bin}:{environment['PATH']}",
            FAKE_REGISTRY=str(registry),
            FAKE_DIGEST=digest,
            FAKE_CALLS=str(deployment / "oras-calls"),
        )
        if overrides:
            environment.update(overrides)
        return environment

    def pull(self, deployment, fake_bin, registry, digest, overrides=None):
        script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
PRE_ROOT="$(pull_pre_nereidforge_installer "$PRE_VERSION")"
test -s "$PRE_ROOT/install-lock.json"
printf '%s\\n' "$PRE_ROOT"
"""
        environment = self.pre_environment(deployment, fake_bin, registry, digest, overrides)
        return run_bash(script, environment)

    def test_helper_returns_only_root_and_reuses_completion_after_selector_moves(self):
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
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            first_root = release / f"pre-nereidforge-installer-{VERSION}"
            self.assertEqual(first.stdout.strip(), str(first_root))
            self.assertEqual((release / "source-commit.txt").read_text().strip(), SOURCE_REVISION)
            calls_after_first = (deployment / "oras-calls").read_bytes()

            second = self.pull(deployment, fake_bin, second_registry, SECOND_DIGEST)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(second.stdout.strip(), str(first_root))
            self.assertFalse((release / f"pre-nereidforge-installer-{SECOND_VERSION}").exists())
            artifacts = release / "artifacts"
            self.assertEqual({path.name for path in artifacts.iterdir()}, {VERSION})
            self.assertEqual(len(list((artifacts / VERSION).iterdir())), 4)
            self.assertEqual((release / "resolved-version.txt").read_text().strip(), VERSION)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls_after_first)

    def test_interrupted_pre_pull_resumes_intent_without_a_second_resolve(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)

            interrupted = self.pull(
                deployment, fake_bin, registry, DIGEST, {"FAKE_FAIL_PULL": "1"}
            )
            self.assertNotEqual(interrupted.returncode, 0)
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            self.assertIn(DIGEST, (release / "installer-digest-intent.txt").read_text())
            self.assertFalse((release / "installer-complete.env").exists())

            resumed = self.pull(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                {"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            calls = (deployment / "oras-calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("resolve ") for line in calls), 1)
            self.assertTrue(all(DIGEST in line for line in calls if line.startswith(("manifest ", "pull "))))
            self.assertTrue((release / f"pre-nereidforge-installer-{VERSION}").is_dir())
            self.assertFalse((release / f"pre-nereidforge-installer-{SECOND_VERSION}").exists())

    def test_stage_resolve_failure_preserves_error_and_cleans_exit_traps(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            locks = deployment / "quick-install" / "artifact-locks"
            state = deployment / "quick-install" / "state"
            logs = deployment / "deploy-logs" / "quick-install"
            fake_bin.mkdir()
            deployment.mkdir()
            locks.mkdir(parents=True)
            (state / "stages").mkdir(parents=True)
            logs.mkdir(parents=True)
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
source {shlex.quote(str(RUNNER))}
source {shlex.quote(str(ARTIFACTS))}
QUICK_ARTIFACT_LOCK_DIR={shlex.quote(str(locks))}
SUITE_STATE_DIR={shlex.quote(str(state))}
SUITE_LOG_DIR={shlex.quote(str(logs))}
install_stage() (
  set -euo pipefail
  suite_prepare_pre_frozen "$PRE_VERSION"
)
verify_stage() {{ return 0; }}
suite_run_stage pre-artifact install_stage verify_stage PRE_VERSION
"""
            result = run_bash(
                script,
                self.pre_environment(
                    deployment,
                    fake_bin,
                    registry,
                    DIGEST,
                    {"FAKE_FAIL_RESOLVE": "1"},
                ),
            )
            log = (logs / "pre-artifact.log").read_text()
            combined = result.stdout + result.stderr + log

            self.assertEqual(result.returncode, 42, combined)
            self.assertIn("simulated registry resolve failure", log)
            self.assertNotIn("unbound variable", combined)
            self.assertEqual((state / "current").read_text(), "pre-artifact=failed\n")
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            self.assertFalse(list(deployment.glob("anonymous-registry.*")))
            self.assertFalse(list(release.glob("installer-digest-intent.txt.resolve.*")))
            self.assertFalse((release / "installer-digest-intent.txt").exists())
            self.assertFalse((release / "installer-digest.txt").exists())

    def test_completed_pre_artifact_before_suite_lock_does_not_resolve_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            locks = deployment / "quick-install" / "artifact-locks"
            fake_bin.mkdir()
            deployment.mkdir()
            locks.mkdir(parents=True)
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            first = self.pull(deployment, fake_bin, registry, DIGEST)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            calls_after_artifact = (deployment / "oras-calls").read_bytes()

            script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
source {shlex.quote(str(RUNNER))}
source {shlex.quote(str(ARTIFACTS))}
QUICK_ARTIFACT_LOCK_DIR={shlex.quote(str(locks))}
suite_prepare_pre_frozen "$PRE_VERSION"
printf '%s\\n' "$PRE_ROOT"
"""
            environment = self.pre_environment(
                deployment,
                fake_bin,
                registry,
                SECOND_DIGEST,
                {"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            locked = run_bash(script, environment)
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            self.assertEqual(locked.stdout.strip(), first.stdout.strip())
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls_after_artifact)
            self.assertTrue((locks / "pre-0.0.0-dev.lock").is_file())

    def test_pre_artifact_without_completion_reuses_archive_and_extracted_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            first = self.pull(deployment, fake_bin, registry, DIGEST)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            (release / "installer-complete.env").unlink()

            recovered = self.pull(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                {"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertEqual(recovered.stdout, first.stdout)
            calls = (deployment / "oras-calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("resolve ") for line in calls), 1)
            self.assertEqual(sum(line.startswith("manifest ") for line in calls), 2)
            self.assertEqual(sum(line.startswith("pull ") for line in calls), 1)

    def test_completed_pre_checksum_mismatch_fails_closed_without_registry_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            first = self.pull(deployment, fake_bin, registry, DIGEST)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            archive = (
                deployment
                / "pre-nereidforge"
                / "0.0.0-dev"
                / "artifacts"
                / VERSION
                / f"pre-nereidforge-installer-{VERSION}.tar.gz"
            )
            archive.write_bytes(b"corrupt")
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull(deployment, fake_bin, registry, SECOND_DIGEST)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive digest mismatch", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)
            self.assertEqual(archive.read_bytes(), b"corrupt")

    def test_corrupt_pre_intent_fails_closed_without_registry_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            interrupted = self.pull(
                deployment, fake_bin, registry, DIGEST, {"FAKE_FAIL_PULL": "1"}
            )
            self.assertNotEqual(interrupted.returncode, 0)
            intent = deployment / "pre-nereidforge" / "0.0.0-dev" / "installer-digest-intent.txt"
            intent.write_text("selector=0.0.0-dev\ndigest=not-a-digest\n")
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull(deployment, fake_bin, registry, SECOND_DIGEST)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid OCI digest intent", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)

    def test_missing_pre_intent_with_completion_never_resolves_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry"
            fake_bin = root / "bin"
            deployment = root / "deployment"
            fake_bin.mkdir()
            deployment.mkdir()
            self.make_environment(deployment)
            self.make_registry(registry)
            make_oras(fake_bin)
            first = self.pull(deployment, fake_bin, registry, DIGEST)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            release = deployment / "pre-nereidforge" / "0.0.0-dev"
            (release / "installer-digest-intent.txt").unlink()
            complete = release / "installer-complete.env"
            retained = complete.read_bytes()
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull(deployment, fake_bin, registry, SECOND_DIGEST)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing OCI digest intent", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)
            self.assertEqual(complete.read_bytes(), retained)

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
if [[ "$1" == show && "$2" == chart ]]; then
  version="$(awk '/^version:/ {print $2; exit}' "$3")"
  printf 'name: nereidforge\\nversion: %s\\nappVersion: "%s"\\n' "$version" "$version"
else
  echo "unexpected fake helm command (floating pulls are forbidden): $*" >&2
  exit 2
fi
"""
        )
        helm.chmod(0o755)

    def make_chart_registry(self, registry, version=VERSION):
        registry.mkdir(parents=True)
        archive = registry / "chart-archive.tgz"
        archive.write_text(f"version: {version}\n")
        layer_digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
        (registry / "chart-manifest.json").write_text(
            json.dumps(
                {
                    "layers": [
                        {
                            "mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
                            "digest": layer_digest,
                        }
                    ]
                }
            )
        )
        return layer_digest

    def make_environment(self, deployment):
        (deployment / "deployment.env").write_text(
            f"export DEPLOYMENT_ROOT={shlex.quote(str(deployment))}\n"
            'export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"\n'
        )

    def chart_environment(
        self, deployment, fake_bin, registry, digest, layer_digest, overrides=None
    ):
        environment = os.environ.copy()
        environment.update(
            PATH=f"{fake_bin}:{environment['PATH']}",
            FAKE_REGISTRY=str(registry),
            FAKE_DIGEST=digest,
            FAKE_LAYER_DIGEST=layer_digest,
            FAKE_CALLS=str(deployment / "oras-calls"),
        )
        if overrides:
            environment.update(overrides)
        return environment

    def pull_chart(
        self, deployment, fake_bin, registry, digest, layer_digest, selector="0.0.0-dev", overrides=None
    ):
        script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
pull_nereid_chart nereidforge {shlex.quote(selector)}
"""
        environment = self.chart_environment(
            deployment, fake_bin, registry, digest, layer_digest, overrides
        )
        return run_bash(script, environment)

    def test_release_selector_pulls_a_bare_semver_chart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry, version="0.0.1")
            result = self.pull_chart(
                deployment, fake_bin, registry, DIGEST, layer_digest, selector="0.0.1"
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = deployment / "chart-archives" / "nereidforge-0.0.1.tgz"
            self.assertTrue(archive.is_file())
            evidence = deployment / "deploy-logs" / "nereidforge"
            self.assertEqual(
                (evidence / "chart-resolved-version.txt").read_text().strip(), "0.0.1"
            )

    def test_unsupported_selector_shape_is_rejected_before_registry_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            result = self.pull_chart(
                deployment, fake_bin, registry, DIGEST, layer_digest, selector="latest"
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("development or release chart selector", result.stderr)
            calls = deployment / "oras-calls"
            if calls.exists():
                self.assertEqual(calls.read_text(), "")

    def test_immutable_selector_must_match_the_archive_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            result = self.pull_chart(
                deployment, fake_bin, registry, DIGEST, layer_digest, selector=SECOND_VERSION
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("resolved to unexpected version", result.stderr)

    def test_interrupted_chart_blob_fetch_resumes_intent_without_a_second_resolve(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)

            interrupted = self.pull_chart(
                deployment, fake_bin, registry, DIGEST, layer_digest, overrides={"FAKE_FAIL_BLOB": "1"}
            )
            self.assertNotEqual(interrupted.returncode, 0)
            evidence = deployment / "deploy-logs" / "nereidforge"
            self.assertIn(DIGEST, (evidence / "chart-digest-intent-0.0.0-dev.txt").read_text())
            self.assertFalse((evidence / "chart-complete-0.0.0-dev.env").exists())

            resumed = self.pull_chart(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                layer_digest,
                overrides={"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            calls = (deployment / "oras-calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("resolve ") for line in calls), 1)
            self.assertTrue(all(DIGEST in line for line in calls if line.startswith("manifest ")))
            self.assertTrue(all(layer_digest in line for line in calls if line.startswith("blob ")))
            archive = deployment / "chart-archives" / f"nereidforge-{VERSION}.tgz"
            self.assertEqual(resumed.stdout.strip(), str(archive))
            self.assertFalse((deployment / "chart-archives" / f"nereidforge-{SECOND_VERSION}.tgz").exists())

    def test_completed_chart_before_suite_lock_does_not_resolve_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            locks = deployment / "quick-install" / "artifact-locks"
            fake_bin.mkdir()
            deployment.mkdir()
            locks.mkdir(parents=True)
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            first = self.pull_chart(deployment, fake_bin, registry, DIGEST, layer_digest)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            calls_after_artifact = (deployment / "oras-calls").read_bytes()

            script = f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(deployment))}
source {shlex.quote(str(LOADER))}
source {shlex.quote(str(RUNNER))}
source {shlex.quote(str(ARTIFACTS))}
QUICK_ARTIFACT_LOCK_DIR={shlex.quote(str(locks))}
suite_pull_chart_frozen nereidforge 0.0.0-dev
"""
            environment = self.chart_environment(
                deployment,
                fake_bin,
                registry,
                SECOND_DIGEST,
                layer_digest,
                {"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            locked = run_bash(script, environment)
            self.assertEqual(locked.returncode, 0, locked.stdout + locked.stderr)
            self.assertEqual(locked.stdout.strip(), first.stdout.strip())
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls_after_artifact)
            self.assertTrue((locks / "chart-nereidforge-0.0.0-dev.lock").is_file())

    def test_chart_archive_without_completion_is_reused_by_layer_digest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            first = self.pull_chart(deployment, fake_bin, registry, DIGEST, layer_digest)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            evidence = deployment / "deploy-logs" / "nereidforge"
            (evidence / "chart-complete-0.0.0-dev.env").unlink()

            recovered = self.pull_chart(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                layer_digest,
                overrides={"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
            self.assertEqual(recovered.stdout, first.stdout)
            calls = (deployment / "oras-calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("resolve ") for line in calls), 1)
            self.assertEqual(sum(line.startswith("manifest ") for line in calls), 2)
            self.assertEqual(sum(line.startswith("blob ") for line in calls), 1)

    def test_chart_blob_digest_mismatch_fails_then_resumes_same_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            mismatch = self.pull_chart(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                layer_digest,
                overrides={"FAKE_CORRUPT_BLOB": "1"},
            )
            self.assertNotEqual(mismatch.returncode, 0)
            self.assertIn("chart blob digest mismatch", mismatch.stderr)

            resumed = self.pull_chart(
                deployment,
                fake_bin,
                registry,
                DIGEST,
                layer_digest,
                overrides={"FAKE_RESOLVE_DIGEST": SECOND_DIGEST},
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
            calls = (deployment / "oras-calls").read_text().splitlines()
            self.assertEqual(sum(line.startswith("resolve ") for line in calls), 1)

    def test_completed_chart_digest_mismatch_fails_closed_without_registry_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            first = self.pull_chart(deployment, fake_bin, registry, DIGEST, layer_digest)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            archive = Path(first.stdout.strip())
            archive.write_bytes(b"corrupt")
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull_chart(deployment, fake_bin, registry, SECOND_DIGEST, layer_digest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive digest mismatch", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)
            self.assertEqual(archive.read_bytes(), b"corrupt")

    def test_missing_chart_intent_with_completion_never_resolves_a_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            first = self.pull_chart(deployment, fake_bin, registry, DIGEST, layer_digest)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            evidence = deployment / "deploy-logs" / "nereidforge"
            (evidence / "chart-digest-intent-0.0.0-dev.txt").unlink()
            complete = evidence / "chart-complete-0.0.0-dev.env"
            retained = complete.read_bytes()
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull_chart(deployment, fake_bin, registry, SECOND_DIGEST, layer_digest)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing OCI digest intent", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)
            self.assertEqual(complete.read_bytes(), retained)

    def test_chart_digest_evidence_mismatch_fails_closed_without_registry_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_bin = root / "bin"
            deployment = root / "deployment"
            registry = root / "registry"
            fake_bin.mkdir()
            deployment.mkdir()
            make_oras(fake_bin)
            self.make_helm(fake_bin)
            self.make_environment(deployment)
            layer_digest = self.make_chart_registry(registry)
            interrupted = self.pull_chart(
                deployment, fake_bin, registry, DIGEST, layer_digest, overrides={"FAKE_FAIL_BLOB": "1"}
            )
            self.assertNotEqual(interrupted.returncode, 0)
            evidence = deployment / "deploy-logs" / "nereidforge" / "chart-digest.txt"
            evidence.write_text(SECOND_DIGEST + "\n")
            calls = (deployment / "oras-calls").read_bytes()

            result = self.pull_chart(deployment, fake_bin, registry, DIGEST, layer_digest)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid OCI digest evidence", result.stderr)
            self.assertEqual((deployment / "oras-calls").read_bytes(), calls)


if __name__ == "__main__":
    unittest.main()
