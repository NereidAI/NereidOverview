#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).parents[2]
RUNNER = ROOT / "scripts" / "lib" / "suite-runner.sh"


class SuiteRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.logs = self.root / "logs"
        (self.state / "stages").mkdir(parents=True)
        self.logs.mkdir()
        self.calls = self.root / "calls"

    def tearDown(self):
        self.temporary.cleanup()

    def run_bash(self, body, *, expected=0):
        script = f"""
set -euo pipefail
source {shlex.quote(str(RUNNER))}
SUITE_STATE_DIR={shlex.quote(str(self.state))}
SUITE_LOG_DIR={shlex.quote(str(self.logs))}
SUITE_STAGES=(one two)
declare -A SUITE_STAGE_DESCRIPTIONS=([one]="First test stage" [two]="Second test stage")
CALLS={shlex.quote(str(self.calls))}
mkdir -p "$SUITE_STATE_DIR/stages" "$SUITE_LOG_DIR"
{body}
"""
        result = subprocess.run(
            ["bash", "-c", script],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def functions(self):
        return """
record() { printf '%s\n' "$1" >> "$CALLS"; }
install_one() { record install-one; }
verify_one() { record verify-one; }
install_two() { record install-two; }
verify_two() { record verify-two; }
"""

    def test_stage_progress_and_operation_details_are_visible(self):
        result = self.run_bash(
            self.functions()
            + """
suite_run_stage one install_one verify_one NFS_SERVER
"""
        )
        output = result.stdout + result.stderr
        self.assertIn("Suite progress: 0/2 stages complete (0%)", output)
        self.assertIn("Stage 1/2: one", output)
        self.assertIn("Purpose: First test stage", output)
        self.assertIn("Step 1/2: stage action", output)
        self.assertIn("Step 2/2: live verification", output)
        self.assertIn("Stage complete: one", output)
        self.assertIn("Suite progress: 1/2 stages complete (50%)", output)
        self.assertIn("Private log:", output)

    def test_failure_summary_is_useful_without_leaking_log_secrets(self):
        result = self.run_bash(
            self.functions()
            + """
install_one() {
  printf '\\033[0;34m[INFO]\\033[0m Check API...\\n'
  printf 'DIAG_HTTP_CODE=200\\n'
  printf 'DIAG_REMOTE_RESULT=1\\n'
  printf '[INFO] password=do-not-print-password\\n'
  printf 'raw-token=do-not-print-token\\n'
  return 1
}
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        output = result.stdout + result.stderr
        self.assertIn("Recent non-secret activity (one):", output)
        self.assertIn("[INFO] Check API...", output)
        self.assertIn("DIAG_HTTP_CODE=200", output)
        self.assertIn("DIAG_REMOTE_RESULT=1", output)
        self.assertIn("exit 1", output)
        self.assertIn("rerun the same command", output)
        self.assertNotIn("do-not-print-password", output)
        self.assertNotIn("do-not-print-token", output)
        log = (self.logs / "one.log").read_text()
        self.assertIn("do-not-print-password", log)
        self.assertIn("do-not-print-token", log)

    def test_failure_stops_downstream_and_completed_stage_skips_mutation(self):
        self.run_bash(
            self.functions()
            + """
install_one() { record install-one; return 1; }
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(self.calls.read_text().splitlines(), ["install-one"])
        self.assertEqual((self.state / "current").read_text().strip(), "one=failed")

        self.calls.write_text("")
        self.run_bash(
            self.functions()
            + """
export NFS_SERVER=nfs.example.org
suite_run_stage one install_one verify_one NFS_SERVER
suite_run_stage two install_two verify_two NFS_SERVER
"""
        )
        first_calls = self.calls.read_text().splitlines()
        self.assertEqual(
            first_calls,
            ["install-one", "verify-one", "install-two", "verify-two"],
        )

        self.run_bash(
            self.functions()
            + """
export NFS_SERVER=nfs.example.org
suite_run_stage one install_one verify_one NFS_SERVER
suite_run_stage two install_two verify_two NFS_SERVER
"""
        )
        self.assertEqual(self.calls.read_text().splitlines(), first_calls + ["verify-one", "verify-two"])

    def test_install_errexit_failure_skips_continuation_and_verification(self):
        self.run_bash(
            self.functions()
            + """
install_one() (
  set -e
  record install-one
  false
  record UNEXPECTED-CONTINUED
)
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(self.calls.read_text().splitlines(), ["install-one"])
        self.assertFalse((self.state / "stages" / "one").exists())
        self.assertEqual((self.state / "current").read_text().strip(), "one=failed")

    def test_install_verification_errexit_failure_does_not_mark_complete(self):
        self.run_bash(
            self.functions()
            + """
verify_one() (
  set -e
  record verify-one
  false
  record UNEXPECTED-CONTINUED
)
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(self.calls.read_text().splitlines(), ["install-one", "verify-one"])
        self.assertFalse((self.state / "stages" / "one").exists())
        self.assertEqual((self.state / "current").read_text().strip(), "one=failed")

    def test_completed_verification_errexit_failure_reconciles_stage(self):
        self.run_bash(self.functions() + "suite_run_stage one install_one verify_one NFS_SERVER\n")
        self.run_bash(
            self.functions()
            + """
verify_one() (
  set -e
  record verify-one
  false
  record UNEXPECTED-CONTINUED
)
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(
            self.calls.read_text().splitlines(),
            ["install-one", "verify-one", "verify-one", "install-one", "verify-one"],
        )
        self.assertEqual((self.state / "current").read_text().strip(), "one=failed")

    def test_interrupted_stage_is_retried_and_live_failure_reconciles(self):
        body = self.functions() + """
export NFS_SERVER=nfs.example.org
suite_run_stage one install_one verify_one NFS_SERVER
"""
        self.run_bash(body)
        (self.state / "stages" / "one").unlink()
        self.run_bash(body)
        self.assertEqual(
            self.calls.read_text().splitlines(),
            ["install-one", "verify-one", "install-one", "verify-one"],
        )

        self.run_bash(
            self.functions()
            + """
export NFS_SERVER=nfs.example.org
verify_one() { record verify-one; return 1; }
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(
            self.calls.read_text().splitlines()[-3:],
            ["verify-one", "install-one", "verify-one"],
        )

    def test_completed_stage_rejects_changed_inputs(self):
        body = self.functions() + """
export NFS_SERVER=nfs.example.org
suite_run_stage one install_one verify_one NFS_SERVER
"""
        self.run_bash(body)
        self.run_bash(
            self.functions()
            + """
export NFS_SERVER=changed.example.org
suite_run_stage one install_one verify_one NFS_SERVER
"""
            , expected=1
        )
        self.assertEqual(self.calls.read_text().splitlines(), ["install-one", "verify-one"])
        self.assertEqual((self.state / "current").read_text().strip(), "one=blocked-config-change")

    def test_waiting_state_resumes_without_replaying_completed_work(self):
        self.run_bash(
            self.functions()
            + """
export HORIZON_SETUP_CONFIRMED=no
install_one() {
  record install-one
  [[ "$HORIZON_SETUP_CONFIRMED" == yes ]] || return "$SUITE_WAITING"
}
suite_run_stage one install_one verify_one HORIZON_SETUP_CONFIRMED
"""
            , expected=20
        )
        self.assertEqual((self.state / "current").read_text().strip(), "one=waiting")
        self.run_bash(
            self.functions()
            + """
export HORIZON_SETUP_CONFIRMED=yes
install_one() {
  record install-one
  [[ "$HORIZON_SETUP_CONFIRMED" == yes ]] || return "$SUITE_WAITING"
}
suite_run_stage one install_one verify_one HORIZON_SETUP_CONFIRMED
suite_run_stage two install_two verify_two HORIZON_SETUP_CONFIRMED
"""
        )
        self.assertEqual(
            self.calls.read_text().splitlines(),
            ["install-one", "install-one", "verify-one", "install-two", "verify-two"],
        )

    def test_waiting_reason_survives_a_stage_subshell(self):
        result = self.run_bash(
            self.functions()
            + """
install_one() (
  set -e
  suite_wait 'Complete the named external acceptance, then resume.'
)
suite_run_stage one install_one verify_one HORIZON_SETUP_CONFIRMED
"""
            , expected=20
        )
        self.assertIn("Complete the named external acceptance, then resume.", result.stderr)
        self.assertEqual(
            (self.state / "wait-reason").read_text().strip(),
            "Complete the named external acceptance, then resume.",
        )
        self.assertEqual(stat.S_IMODE((self.state / "wait-reason").stat().st_mode), 0o600)

    def test_cluster_identity_is_required_and_foreign_releases_are_not_adopted(self):
        self.run_bash("suite_bind_cluster context-a uid-a ''")
        self.assertEqual((self.state / "cluster-context").read_text().strip(), "context-a")
        self.run_bash("suite_bind_cluster context-a uid-b ''", expected=1)
        self.run_bash("suite_bind_cluster context-b uid-a ''", expected=1)

        foreign = self.root / "foreign"
        (foreign / "stages").mkdir(parents=True)
        script = f"""
set -euo pipefail
source {shlex.quote(str(RUNNER))}
SUITE_STATE_DIR={shlex.quote(str(foreign))}
suite_bind_cluster context-a uid-a nereididentity
"""
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("manual recovery", result.stderr)
        self.assertFalse((foreign / "cluster-context").exists())

    def test_state_files_are_private(self):
        self.run_bash(
            self.functions()
            + """
export NFS_SERVER=nfs.example.org
suite_run_stage one install_one verify_one NFS_SERVER
"""
        )
        for path in (self.state / "current", self.state / "stages" / "one"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
