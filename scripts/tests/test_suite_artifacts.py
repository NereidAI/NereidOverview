#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

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


class FrozenChartTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.deployment = self.root / "deployment"
        self.archives = self.deployment / "chart-archives"
        self.logs = self.deployment / "deploy-logs" / "nereididentity"
        self.locks = self.deployment / "locks"
        self.state = self.deployment / "state"
        self.archives.mkdir(parents=True)
        self.logs.mkdir(parents=True)
        self.locks.mkdir()
        self.state.mkdir()
        (self.deployment / "deployment.env").write_text(
            f"export DEPLOYMENT_ROOT={shlex.quote(str(self.deployment))}\n"
            'export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"\n',
            encoding="utf-8",
        )
        self.calls = self.root / "calls"

    def tearDown(self):
        self.temporary.cleanup()

    def script(self, body):
        return f"""
set -euo pipefail
DEPLOYMENT_ROOT={shlex.quote(str(self.deployment))}
DEPLOYMENT_ENV_FILE={shlex.quote(str(self.deployment / 'deployment.env'))}
source {shlex.quote(str(LOADER))}
source {shlex.quote(str(RUNNER))}
source {shlex.quote(str(ARTIFACTS))}
DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"
QUICK_ARTIFACT_LOCK_DIR={shlex.quote(str(self.locks))}
SUITE_STATE_DIR={shlex.quote(str(self.state))}
CALLS={shlex.quote(str(self.calls))}
FAKE_VERSION="${{FAKE_VERSION:-0.0.0-dev-abcdef1}}"
pull_nereid_chart() {{
  printf '%s\n' "$1:$2:$FAKE_VERSION" >> "$CALLS"
  local archive="$DEPLOYMENT_ROOT/chart-archives/$1-$FAKE_VERSION.tgz"
  printf 'fake archive for %s\n' "$FAKE_VERSION" > "$archive"
  mkdir -p "$DEPLOY_LOG_ROOT/$1"
  printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
    > "$DEPLOY_LOG_ROOT/$1/chart-digest.txt"
  printf 'selector=%s\ndigest=%s\n' "$2" 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
    > "$DEPLOY_LOG_ROOT/$1/chart-digest-intent-$2.txt"
  printf '%s\n' "$archive"
}}
helm() {{
  if [[ "$1 $2" == 'show chart' ]]; then
    local base
    base="$(basename "$3" .tgz)"
    printf 'version: %s\n' "${{base#nereididentity-}}"
  else
    return 2
  fi
}}
{body}
"""

    def run_bash(self, body, *, version="0.0.0-dev-abcdef1", expected=0):
        environment = os.environ.copy()
        environment["FAKE_VERSION"] = version
        result = subprocess.run(
            ["bash", "-c", self.script(body)],
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_resume_reuses_first_archive_after_floating_selector_moves(self):
        body = 'suite_pull_chart_frozen nereididentity 0.0.0-dev\n'
        first = self.run_bash(body)
        first_archive = Path(first.stdout.strip())
        first_checksum = first_archive.read_bytes()
        second = self.run_bash(body, version="0.0.0-dev-bbcdef2")
        self.assertEqual(second.stdout.strip(), str(first_archive))
        self.assertEqual(self.calls.read_text().splitlines(), ["nereididentity:0.0.0-dev:0.0.0-dev-abcdef1"])
        self.assertEqual(first_archive.read_bytes(), first_checksum)
        self.assertIn("0.0.0-dev-abcdef1", (self.locks / "chart-nereididentity-0.0.0-dev.lock").read_text())

    def test_missing_digest_intent_invalidates_an_existing_frozen_lock(self):
        body = 'suite_pull_chart_frozen nereididentity 0.0.0-dev\n'
        archive = Path(self.run_bash(body).stdout.strip())
        (self.logs / "chart-digest-intent-0.0.0-dev.txt").unlink()

        result = self.run_bash(body, version="0.0.0-dev-bbcdef2", expected=1)

        self.assertIn("digest intent", result.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertTrue(archive.is_file())

    def test_frozen_version_read_also_requires_the_retained_digest_intent(self):
        self.run_bash('suite_pull_chart_frozen nereididentity 0.0.0-dev\n')
        (self.logs / "chart-digest-intent-0.0.0-dev.txt").unlink()

        result = self.run_bash(
            'suite_frozen_chart_version nereididentity 0.0.0-dev\n',
            version="0.0.0-dev-bbcdef2",
            expected=1,
        )

        self.assertIn("digest intent", result.stderr)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)

    def test_corrupt_frozen_archive_fails_without_downloading_a_replacement(self):
        body = 'suite_pull_chart_frozen nereididentity 0.0.0-dev\n'
        archive = Path(self.run_bash(body).stdout.strip())
        archive.write_text("corrupt")
        self.run_bash(body, version="0.0.0-dev-bbcdef2", expected=1)
        self.assertEqual(len(self.calls.read_text().splitlines()), 1)
        self.assertEqual(archive.read_text(), "corrupt")

    def test_floating_bare_version_chart_freezes_just_like_an_immutable_one(self):
        # NereidForge development charts keep the bare 0.0.0-dev identity; the
        # lock and evidence machinery must accept that resolved version shape.
        body = 'suite_pull_chart_frozen nereididentity 0.0.0-dev\n'
        first = self.run_bash(body, version="0.0.0-dev")
        archive = Path(first.stdout.strip())
        self.assertEqual(archive.name, "nereididentity-0.0.0-dev.tgz")
        lock = (self.locks / "chart-nereididentity-0.0.0-dev.lock").read_text()
        self.assertIn("LOCKED_RESOLVED_VERSION=0.0.0-dev", lock)

        # The second run reuses the frozen archive even if the registry side
        # would now resolve a different generation.
        second = self.run_bash(body, version="0.0.0-dev")
        self.assertEqual(second.stdout.strip(), str(archive))
        self.assertEqual(
            self.calls.read_text().splitlines(),
            ["nereididentity:0.0.0-dev:0.0.0-dev"],
        )


if __name__ == "__main__":
    unittest.main()
