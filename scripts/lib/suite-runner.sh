#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Reusable execution journal for the optional suite installer. This file is
# sourced by install-suite.sh and by offline tests; it performs no work itself.

SUITE_WAITING=20
SUITE_PREVIOUS_FINGERPRINT=""

suite_fail() {
    printf 'ERROR: %s\n' "$*" >&2
    return 1
}

suite_wait() {
    local reason="$1"
    SUITE_WAIT_REASON="$reason"
    if [[ -n "${SUITE_WAIT_REASON_FILE:-}" ]]; then
        suite_atomic_write "$SUITE_WAIT_REASON_FILE" "$reason" || return
    fi
    return "$SUITE_WAITING"
}

suite_atomic_write() {
    local destination="$1" content="$2" temporary
    temporary="${destination}.tmp.$$"
    printf '%s\n' "$content" > "$temporary" || return
    chmod 600 "$temporary" || {
        rm -f "$temporary"
        return 1
    }
    mv -f "$temporary" "$destination" || {
        rm -f "$temporary"
        return 1
    }
}

suite_set_run_state() {
    local stage="$1" status="$2"
    suite_atomic_write "$SUITE_STATE_DIR/current" "$stage=$status"
}

suite_stage_fingerprint() {
    local stage="$1" previous="$2" name
    shift 2
    {
        printf 'schema=suite-install-stage/v1\0stage=%s\0previous=%s\0' "$stage" "$previous"
        for name in "$@"; do
            [[ "$name" =~ ^[A-Z][A-Z0-9_]*$ ]] || {
                printf 'Invalid fingerprint variable name: %s\n' "$name" >&2
                return 2
            }
            printf '%s=%s\0' "$name" "${!name-}"
        done
    } | sha256sum | awk '{print $1}'
}

suite_stage_marker() {
    printf '%s/stages/%s\n' "$SUITE_STATE_DIR" "$1"
}

suite_run_stage() {
    local stage="$1" install_function="$2" verify_function="$3"
    local fingerprint marker saved status had_errexit
    case $- in
        *e*) had_errexit=1 ;;
        *) had_errexit=0 ;;
    esac
    shift 3
    fingerprint="$(suite_stage_fingerprint "$stage" "$SUITE_PREVIOUS_FINGERPRINT" "$@")" || return
    marker="$(suite_stage_marker "$stage")"
    CURRENT_LOG="$SUITE_LOG_DIR/$stage.log"

    if [[ -f "$marker" ]]; then
        saved="$(cat "$marker")"
        if [[ "$saved" != "$fingerprint" ]]; then
            suite_set_run_state "$stage" blocked-config-change
            suite_fail "$stage was completed with different inputs. Automatic changes to completed stages are not supported; follow the upgrade/recovery guide instead of editing them through resume."
            return 1
        fi
        printf 'Checking completed stage: %s\n' "$stage"
        # Do not put a stage function in an if/while/! condition. Bash ignores
        # errexit throughout such a function, including its nested subshells.
        set +e
        NEREID_VERIFY_TIMEOUT=30s NEREID_CURL_TIMEOUT=30 \
            "$verify_function" >> "$CURRENT_LOG" 2>&1
        status=$?
        if (( had_errexit )); then set -e; fi
        if (( status == 0 )); then
            printf 'Stage already complete and healthy: %s\n' "$stage"
            suite_set_run_state "$stage" complete
            SUITE_PREVIOUS_FINGERPRINT="$fingerprint"
            return 0
        fi
        printf 'Stage marker exists but live verification failed; reconciling: %s\n' "$stage" >&2
    fi

    suite_set_run_state "$stage" running
    SUITE_WAIT_REASON=""
    SUITE_WAIT_REASON_FILE="$SUITE_STATE_DIR/wait-reason"
    rm -f "$SUITE_WAIT_REASON_FILE"
    printf 'Running stage: %s\n' "$stage"
    set +e
    "$install_function" >> "$CURRENT_LOG" 2>&1
    status=$?
    if (( had_errexit )); then set -e; fi
    if (( status == 0 )); then
        set +e
        NEREID_VERIFY_TIMEOUT="${NEREID_INSTALL_VERIFY_TIMEOUT:-5m}" \
            NEREID_CURL_TIMEOUT="${NEREID_INSTALL_CURL_TIMEOUT:-300}" \
            "$verify_function" >> "$CURRENT_LOG" 2>&1
        status=$?
        if (( had_errexit )); then set -e; fi
        if (( status == 0 )); then
            suite_atomic_write "$marker" "$fingerprint" || return
            suite_set_run_state "$stage" complete
            printf 'Stage complete: %s\n' "$stage"
            SUITE_PREVIOUS_FINGERPRINT="$fingerprint"
            return 0
        fi
    fi

    if (( status == SUITE_WAITING )); then
        suite_set_run_state "$stage" waiting
        if [[ -z "${SUITE_WAIT_REASON:-}" && -f "$SUITE_WAIT_REASON_FILE" ]]; then
            SUITE_WAIT_REASON="$(cat "$SUITE_WAIT_REASON_FILE")"
        fi
        printf 'Stage is waiting for an external action: %s\n' "$stage" >&2
        if [[ -n "${SUITE_WAIT_REASON:-}" ]]; then
            printf '%s\n' "$SUITE_WAIT_REASON" >&2
        fi
        printf 'Complete the documented action, then rerun the same command. Private log: %s\n' "$CURRENT_LOG" >&2
    else
        suite_set_run_state "$stage" failed
        printf 'Stage failed: %s. Fix the cause and rerun the same command. Private log: %s\n' \
            "$stage" "$CURRENT_LOG" >&2
    fi
    return "$status"
}

suite_acquire_lock() {
    local lock_file="$1"
    exec 9> "$lock_file" || return
    chmod 600 "$lock_file" || return
    if ! flock -n 9; then
        suite_fail "another suite installation process holds $lock_file"
        return 1
    fi
}

suite_bind_cluster() {
    local context="$1" cluster_uid="$2" managed_releases="$3"
    local context_file="$SUITE_STATE_DIR/cluster-context"
    local uid_file="$SUITE_STATE_DIR/cluster-uid"
    if [[ -f "$context_file" || -f "$uid_file" ]]; then
        [[ -f "$context_file" && -f "$uid_file" ]] || {
            suite_fail "incomplete cluster identity in $SUITE_STATE_DIR; stop for recovery"
            return 1
        }
        [[ "$(cat "$context_file")" == "$context" ]] || {
            suite_fail "deployment state belongs to kubecontext $(cat "$context_file"), not $context"
            return 1
        }
        [[ "$(cat "$uid_file")" == "$cluster_uid" ]] || {
            suite_fail "deployment state belongs to a different live cluster; refusing to continue"
            return 1
        }
        return 0
    fi

    if [[ -n "$managed_releases" ]]; then
        suite_fail "existing NereidAI product releases were found without quick-install state; use the manual recovery path instead of adopting them: $managed_releases"
        return 1
    fi
    suite_atomic_write "$context_file" "$context" || return
    if ! suite_atomic_write "$uid_file" "$cluster_uid"; then
        rm -f "$context_file"
        return 1
    fi
}

suite_print_status() {
    local stage marker saved fingerprint
    SUITE_PREVIOUS_FINGERPRINT=""
    if [[ -f "$SUITE_STATE_DIR/current" ]]; then
        printf 'Last recorded state: %s\n' "$(cat "$SUITE_STATE_DIR/current")"
    else
        printf 'Last recorded state: not-started\n'
    fi
    for stage in "${SUITE_STAGES[@]}"; do
        fingerprint="$(suite_stage_fingerprint "$stage" "$SUITE_PREVIOUS_FINGERPRINT" \
            ${SUITE_STAGE_INPUTS[$stage]-})" || return
        marker="$(suite_stage_marker "$stage")"
        if [[ -f "$marker" ]]; then
            saved="$(cat "$marker")"
            if [[ "$saved" == "$fingerprint" ]]; then
                printf '%-24s complete\n' "$stage"
            else
                printf '%-24s blocked-config-change\n' "$stage"
            fi
        else
            printf '%-24s pending\n' "$stage"
        fi
        SUITE_PREVIOUS_FINGERPRINT="$fingerprint"
    done
}
