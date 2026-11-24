#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
LOADER = ROOT / "scripts" / "load-deployment-env.sh"
RUNNER = ROOT / "scripts" / "lib" / "suite-runner.sh"
ARTIFACTS = ROOT / "scripts" / "lib" / "suite-artifacts.sh"
SELECTOR = "0.0.0-dev"
VERSION = "0.0.0-dev-abcdef1"
SOURCE_COMMIT = "abcdef1" + "a" * 33
DIGEST = "sha256:" + "1" * 64
SECOND_VERSION = "0.0.0-dev-bbcdef2"
SECOND_SOURCE_COMMIT = "bbcdef2" + "b" * 33
SECOND_DIGEST = "sha256:" + "2" * 64


class FrozenPreInstallerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deployment = self.root / "deployment"
        self.release = self.deployment / "pre-nereidforge" / SELECTOR
        self.locks = self.deployment / "quick-install" / "artifact-locks"
        self.locks.mkdir(parents=True)
        (self.deployment / "deployment.env").write_text(
            f"export DEPLOYMENT_ROOT={shlex.quote(str(self.deployment))}\n"
            'export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"\n'
            f"export PRE_VERSION={shlex.quote(SELECTOR)}\n"
            'export PRE_RELEASE_DIR="$DEPLOYMENT_ROOT/pre-nereidforge/$PRE_VERSION"\n',
            encoding="utf-8",
        )
        self.calls = self.root / "calls"
        self.lock = self.locks / f"pre-{SELECTOR}.lock"

    def tearDown(self):
        self.temporary.cleanup()

    def installer_root(self, version=VERSION):
        return self.release / f"pre-nereidforge-installer-{version}"

    def archive(self, version=VERSION):
        return (
            self.release
            / "artifacts"
            / version
            / f"pre-nereidforge-installer-{version}.tar.gz"
        )

    def script(self, body):
        return f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(self.deployment))}
DEPLOYMENT_ENV_FILE={shlex.quote(str(self.deployment / 'deployment.env'))}
source {shlex.quote(str(LOADER))}
source {shlex.quote(str(RUNNER))}
source {shlex.quote(str(ARTIFACTS))}
PRE_VERSION={shlex.quote(SELECTOR)}
PRE_RELEASE_DIR={shlex.quote(str(self.release))}
QUICK_ARTIFACT_LOCK_DIR={shlex.quote(str(self.locks))}
CALLS={shlex.quote(str(self.calls))}
EXPECTED_ROOT={shlex.quote(str(self.installer_root()))}
EXPECTED_VERSION={shlex.quote(VERSION)}
EXPECTED_SOURCE_COMMIT={shlex.quote(SOURCE_COMMIT)}
EXPECTED_DIGEST={shlex.quote(DIGEST)}
export EXPECTED_ROOT EXPECTED_VERSION EXPECTED_SOURCE_COMMIT EXPECTED_DIGEST
pull_pre_nereidforge_installer() (
  set -euo pipefail
  local selector="$1"
  local version="$FAKE_VERSION"
  local artifact_dir="$PRE_RELEASE_DIR/artifacts/$version"
  local installer_root="$PRE_RELEASE_DIR/pre-nereidforge-installer-$version"
  test "$selector" = "$PRE_VERSION"
  printf '%s\n' "$selector:$version:$FAKE_SOURCE_COMMIT:$FAKE_DIGEST" >> "$CALLS"
  mkdir -p "$artifact_dir" "$installer_root"
  printf '%s\n' "$version" > "$PRE_RELEASE_DIR/resolved-version.txt"
  printf '%s\n' "$FAKE_SOURCE_COMMIT" > "$PRE_RELEASE_DIR/source-commit.txt"
  printf '%s\n' "$FAKE_DIGEST" > "$PRE_RELEASE_DIR/resolved-digest.txt"
  printf '%s\n' "$FAKE_DIGEST" > "$PRE_RELEASE_DIR/installer-digest.txt"
  printf 'selector=%s\ndigest=%s\n' "$selector" "$FAKE_DIGEST" \
    > "$PRE_RELEASE_DIR/installer-digest-intent.txt"
  printf 'fake pre installer archive for %s\n' "$version" \
    > "$artifact_dir/pre-nereidforge-installer-$version.tar.gz"
  printf '{{"version": "%s"}}\n' "$version" > "$installer_root/install-lock.json"
  printf '%s\n' "$installer_root"
)
{body}
"""

    def run_bash(
        self,
        body,
        *,
        version=VERSION,
        source_commit=SOURCE_COMMIT,
        digest=DIGEST,
        expected=0,
    ):
        environment = os.environ.copy()
        environment.update(
            FAKE_VERSION=version,
            FAKE_SOURCE_COMMIT=source_commit,
            FAKE_DIGEST=digest,
        )
        result = subprocess.run(
            ["bash", "-c", self.script(body)],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def freeze(self):
        return self.run_bash('suite_prepare_pre_frozen "$PRE_VERSION"\n')

    def assert_no_second_download(self):
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertFalse(self.installer_root(SECOND_VERSION).exists())

    def test_first_resolution_records_immutable_identity_and_artifact(self):
        self.freeze()

        archive = self.archive()
        archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(
            self.lock.read_text().splitlines(),
            [
                f"locked_selector={SELECTOR}",
                f"PRE_RESOLVED_VERSION={VERSION}",
                f"PRE_SOURCE_COMMIT={SOURCE_COMMIT}",
                f"PRE_DIGEST={DIGEST}",
                f"PRE_ARCHIVE_SHA256={archive_sha256}",
                f"PRE_ARCHIVE={archive}",
                f"PRE_ROOT={self.installer_root()}",
            ],
        )
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o600)
        self.assertTrue((self.installer_root() / "install-lock.json").is_file())
        self.assertEqual(
            self.calls.read_text().splitlines(),
            [f"{SELECTOR}:{VERSION}:{SOURCE_COMMIT}:{DIGEST}"],
        )

    def test_resume_reuses_original_root_after_floating_selector_moves(self):
        self.freeze()
        original_lock = self.lock.read_bytes()
        original_archive = self.archive().read_bytes()

        resumed = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\nprintf "%s\\n" "$PRE_ROOT"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
        )

        self.assertEqual(resumed.stdout.strip(), str(self.installer_root()))
        self.assertEqual(self.lock.read_bytes(), original_lock)
        self.assertEqual(self.archive().read_bytes(), original_archive)
        self.assert_no_second_download()

    def test_missing_digest_intent_invalidates_an_existing_frozen_lock(self):
        self.freeze()
        (self.release / "installer-digest-intent.txt").unlink()

        result = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
            expected=1,
        )

        self.assertIn("digest intent", result.stderr)
        self.assert_no_second_download()

    def test_corrupt_archive_fails_closed_without_downloading(self):
        self.freeze()
        archive = self.archive()
        archive.write_text("corrupt\n")

        result = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
            expected=1,
        )

        self.assertIn("frozen pre installer archive checksum failed", result.stderr)
        self.assertEqual(archive.read_text(), "corrupt\n")
        self.assert_no_second_download()

    def test_missing_archive_fails_closed_without_downloading(self):
        self.freeze()
        self.archive().unlink()

        result = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
            expected=1,
        )

        self.assertIn("frozen pre installer archive is missing", result.stderr)
        self.assert_no_second_download()

    def test_incomplete_extracted_root_fails_closed_without_downloading(self):
        self.freeze()
        (self.installer_root() / "install-lock.json").unlink()

        result = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
            expected=1,
        )

        self.assertIn("frozen pre installer root is incomplete", result.stderr)
        self.assert_no_second_download()

    def test_lock_identity_mismatch_fails_closed_without_downloading(self):
        self.freeze()
        content = self.lock.read_text()
        self.lock.write_text(
            content.replace(
                f"locked_selector={SELECTOR}\n",
                "locked_selector=0.0.0-dev-other\n",
                1,
            )
        )

        result = self.run_bash(
            'suite_prepare_pre_frozen "$PRE_VERSION"\n',
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
            expected=1,
        )

        self.assertIn("pre artifact lock identity mismatch", result.stderr)
        self.assert_no_second_download()

    def test_initial_values_are_exported_for_prepare_pre_runtime_consumers(self):
        body = """
prepare_pre_runtime() {
  suite_prepare_pre_frozen "$PRE_VERSION"
  SOURCE_COMMIT="$PRE_SOURCE_COMMIT"
  export SOURCE_COMMIT
  bash -c '
    test "$PRE_ROOT" = "$EXPECTED_ROOT"
    test "$PRE_RESOLVED_VERSION" = "$EXPECTED_VERSION"
    test "$PRE_SOURCE_COMMIT" = "$EXPECTED_SOURCE_COMMIT"
    test "$PRE_DIGEST" = "$EXPECTED_DIGEST"
    test "$SOURCE_COMMIT" = "$EXPECTED_SOURCE_COMMIT"
  '
}
prepare_pre_runtime
"""
        self.run_bash(body)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)

    def test_retained_values_are_exported_for_prepare_pre_runtime_consumers(self):
        self.freeze()
        body = """
prepare_pre_runtime() {
  suite_prepare_pre_frozen "$PRE_VERSION"
  SOURCE_COMMIT="$PRE_SOURCE_COMMIT"
  export SOURCE_COMMIT
  bash -c '
    test "$PRE_ROOT" = "$EXPECTED_ROOT"
    test "$PRE_RESOLVED_VERSION" = "$EXPECTED_VERSION"
    test "$PRE_SOURCE_COMMIT" = "$EXPECTED_SOURCE_COMMIT"
    test "$PRE_DIGEST" = "$EXPECTED_DIGEST"
    test "$SOURCE_COMMIT" = "$EXPECTED_SOURCE_COMMIT"
  '
}
prepare_pre_runtime
"""
        self.run_bash(
            body,
            version=SECOND_VERSION,
            source_commit=SECOND_SOURCE_COMMIT,
            digest=SECOND_DIGEST,
        )
        self.assert_no_second_download()

    def test_nested_pull_failure_is_not_hidden_by_conditional_errexit(self):
        body = """
pull_pre_nereidforge_installer() (
  set -euo pipefail
  printf 'entered\\n' >> "$CALLS"
  false
  printf 'continued-after-failure\\n' >> "$CALLS"
  printf '%s\\n' "$EXPECTED_ROOT"
)
suite_prepare_pre_frozen "$PRE_VERSION"
"""
        self.run_bash(body, expected=1)
        self.assertEqual(self.calls.read_text().splitlines(), ["entered"])
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
