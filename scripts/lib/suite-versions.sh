#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Read-only suite channel detection. A checkout exactly on a v* SemVer tag
# resolves to the bare release version (v0.0.1 -> 0.0.1); every other state —
# main, feature branches, detached work, a tarball without .git, or any git
# error — resolves to the rolling dev channel. The manifest lookup then fails
# closed on its own when a release tag has no published matrix, so this
# function never aborts the installer.

suite_resolve_version_channel() {
    local repo_root="${1:?repository root is required}" tag
    tag="$(git -C "$repo_root" describe --tags --exact-match 2>/dev/null || true)"
    if [[ "$tag" =~ ^v([0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?)$ ]]; then
        printf '%s\n' "${BASH_REMATCH[1]}"
    else
        printf 'dev\n'
    fi
}
