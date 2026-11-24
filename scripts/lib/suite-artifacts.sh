#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Artifact freezing for resume. The first anonymous resolution is reused after
# an interruption, even if a floating development selector subsequently moves.

suite_chart_lock() {
    printf '%s/chart-%s-%s.lock\n' "$QUICK_ARTIFACT_LOCK_DIR" "$1" "$2"
}

suite_pre_lock() {
    printf '%s/pre-%s.lock\n' "$QUICK_ARTIFACT_LOCK_DIR" "$1"
}

suite_pull_chart_frozen() (
    set -euo pipefail
    local product="$1" selector="$2" lock archive resolved_version digest archive_sha256
    local locked_product locked_selector intent evidence locked_digest
    lock="$(suite_chart_lock "$product" "$selector")"
    if [[ -f "$lock" ]]; then
        # The lock is a mode-0600 operator-state file, never a downloaded file.
        # shellcheck disable=SC1090,SC1091
        source "$lock"
        [[ "$locked_product" == "$product" && "$locked_selector" == "$selector" ]] || {
            echo "Artifact lock identity mismatch: $lock" >&2
            return 1
        }
        intent="$DEPLOY_LOG_ROOT/$product/chart-digest-intent-$selector.txt"
        evidence="$DEPLOY_LOG_ROOT/$product/chart-digest.txt"
        locked_digest="$(_nereid_resolve_digest "$intent" "$evidence" "$selector" \
            "ghcr.io/nereidai/charts/$product" "" "$lock")"
        [[ "$locked_digest" == "$digest" ]] || {
            echo "Artifact lock digest intent mismatch: $lock" >&2
            return 1
        }
        [[ -f "$archive" && ! -L "$archive" ]] || {
            echo "Frozen chart archive is missing or not a regular file: $product" >&2
            return 1
        }
        printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum -c - >&2
        resolved_version="$(helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"')"
        [[ "$resolved_version" == "$LOCKED_RESOLVED_VERSION" ]] || {
            echo "Frozen chart archive version changed: $product" >&2
            return 1
        }
        printf '%s\n' "$archive"
        return 0
    fi

    archive="$(pull_nereid_chart "$product" "$selector")"
    resolved_version="$(helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"')"
    digest="$(cat "$DEPLOY_LOG_ROOT/$product/chart-digest.txt")"
    archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
    locked_product="$product"
    locked_selector="$selector"
    LOCKED_RESOLVED_VERSION="$resolved_version"
    local content
    content="$(printf 'locked_product=%q\nlocked_selector=%q\nLOCKED_RESOLVED_VERSION=%q\ndigest=%q\narchive_sha256=%q\narchive=%q' \
        "$locked_product" "$locked_selector" "$LOCKED_RESOLVED_VERSION" "$digest" "$archive_sha256" "$archive")"
    suite_atomic_write "$lock" "$content"
    printf '%s\n' "$archive"
)

suite_frozen_chart_version() {
    local product="$1" selector="$2" archive
    archive="$(suite_pull_chart_frozen "$product" "$selector")" || return
    helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"'
}

suite_prepare_pre_frozen() {
    local selector="$1" lock content status had_errexit locked_digest
    local locked_selector PRE_ARCHIVE PRE_ARCHIVE_SHA256
    lock="$(suite_pre_lock "$selector")"
    if [[ -f "$lock" ]]; then
        # shellcheck disable=SC1090,SC1091
        source "$lock"
        [[ "$locked_selector" == "$selector" ]] || {
            suite_fail "pre artifact lock identity mismatch: $lock"
            return 1
        }
        locked_digest="$(_nereid_resolve_digest \
            "$PRE_RELEASE_DIR/installer-digest-intent.txt" \
            "$PRE_RELEASE_DIR/installer-digest.txt" "$selector" \
            "ghcr.io/nereidai/pre-nereidforge-installer" "" "$lock")"
        [[ "$locked_digest" == "$PRE_DIGEST" ]] || {
            suite_fail "pre artifact lock digest intent mismatch: $lock"
            return 1
        }
        [[ -d "$PRE_ROOT" && -s "$PRE_ROOT/install-lock.json" ]] || {
            suite_fail "frozen pre installer root is incomplete: $PRE_ROOT"
            return 1
        }
        [[ -f "$PRE_ARCHIVE" && ! -L "$PRE_ARCHIVE" ]] || {
            suite_fail "frozen pre installer archive is missing"
            return 1
        }
        printf '%s  %s\n' "$PRE_ARCHIVE_SHA256" "$PRE_ARCHIVE" | sha256sum -c - >/dev/null || {
            suite_fail "frozen pre installer archive checksum failed"
            return 1
        }
        export PRE_ROOT PRE_RESOLVED_VERSION PRE_SOURCE_COMMIT PRE_DIGEST
        return 0
    fi

    # Capture a failing pull without putting the function call in an ||/if
    # context: Bash would otherwise disable errexit throughout its nested body.
    case $- in
        *e*) had_errexit=1 ;;
        *) had_errexit=0 ;;
    esac
    set +e
    PRE_ROOT="$(pull_pre_nereidforge_installer "$selector")"
    status=$?
    if (( had_errexit )); then set -e; fi
    if (( status != 0 )); then return "$status"; fi
    PRE_RESOLVED_VERSION="$(cat "$PRE_RELEASE_DIR/resolved-version.txt")"
    PRE_SOURCE_COMMIT="$(cat "$PRE_RELEASE_DIR/source-commit.txt")"
    PRE_DIGEST="$(cat "$PRE_RELEASE_DIR/resolved-digest.txt")"
    PRE_ARCHIVE="$PRE_RELEASE_DIR/artifacts/$PRE_RESOLVED_VERSION/pre-nereidforge-installer-$PRE_RESOLVED_VERSION.tar.gz"
    PRE_ARCHIVE_SHA256="$(sha256sum "$PRE_ARCHIVE" | awk '{print $1}')"
    locked_selector="$selector"
    content="$(printf 'locked_selector=%q\nPRE_RESOLVED_VERSION=%q\nPRE_SOURCE_COMMIT=%q\nPRE_DIGEST=%q\nPRE_ARCHIVE_SHA256=%q\nPRE_ARCHIVE=%q\nPRE_ROOT=%q' \
        "$locked_selector" "$PRE_RESOLVED_VERSION" "$PRE_SOURCE_COMMIT" "$PRE_DIGEST" \
        "$PRE_ARCHIVE_SHA256" "$PRE_ARCHIVE" "$PRE_ROOT")"
    suite_atomic_write "$lock" "$content" || return
    export PRE_ROOT PRE_RESOLVED_VERSION PRE_SOURCE_COMMIT PRE_DIGEST
}
