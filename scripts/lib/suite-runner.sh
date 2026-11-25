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

suite_stage_position() {
    local stage="$1" item index=0 total=0
    if declare -p SUITE_STAGES &>/dev/null; then
        for item in "${SUITE_STAGES[@]}"; do
            total=$((total + 1))
            if [[ "$item" == "$stage" ]]; then
                index="$total"
            fi
        done
    fi
    (( index > 0 )) || index=1
    (( total > 0 )) || total=1
    printf '%s %s\n' "$index" "$total"
}

suite_print_progress() {
    local stage="$1" completed="${2:-}" index total percent
    read -r index total < <(suite_stage_position "$stage")
    if [[ "$completed" == complete ]]; then
        completed="$index"
    elif [[ -z "$completed" ]]; then
        completed=$((index - 1))
    fi
    percent=$((completed * 100 / total))
    printf 'Suite progress: %d/%d stages complete (%d%%)\n' \
        "$completed" "$total" "$percent"
}

suite_print_stage_header() {
    local stage="$1" log="$2" index total description
    read -r index total < <(suite_stage_position "$stage")
    description="Install and verify $stage"
    if declare -p SUITE_STAGE_DESCRIPTIONS &>/dev/null; then
        description="${SUITE_STAGE_DESCRIPTIONS[$stage]:-$description}"
    fi
    printf '\n'
    suite_print_progress "$stage"
    printf 'Stage %d/%d: %s\n' "$index" "$total" "$stage"
    printf 'Purpose: %s\n' "$description"
    printf 'Private log: %s\n' "$log"
}

suite_safe_log_activity() {
    local log="$1" limit="${2:-1}"
    [[ -f "$log" && "$limit" =~ ^[1-9][0-9]*$ ]] || return 0
    # The complete log remains private and unchanged. The console receives only
    # known operational messages, and even those are dropped when they mention
    # credential-shaped material. Never relay arbitrary command output.
    {
        tail -n 200 "$log" 2>/dev/null \
            | sed $'s/\033\[[0-9;]*[mK]//g' \
            | grep -E '^\[(INFO|OK|WARNING|ERR)\] |^DIAG_(REMOTE_RESULT|CURL_EXIT|HTTP_CODE|RESP_BODY_BYTES|KUBECTL_EXIT)=[A-Za-z0-9_.-]+$|^deployment .+ successfully rolled out$|^HEAD is now at [0-9a-f]{7,40} |^Cloning into |: OK$' \
            | grep -Evi 'password|passwd|token|secret|credential|authorization|cookie|ticket|access[_-]?key|private[_-]?key|client[_-]?key' \
            | tail -n "$limit"
    } || true
}

suite_print_recent_activity() {
    local stage="$1" log="$2" limit="${3:-3}" activity line
    activity="$(suite_safe_log_activity "$log" "$limit")"
    [[ -n "$activity" ]] || return 0
    printf 'Recent non-secret activity (%s):\n' "$stage"
    while IFS= read -r line; do
        printf '  %s\n' "$line"
    done <<< "$activity"
}

suite_progress_monitor() {
    local stage="$1" log="$2" started="$3" parent="$4" interval="$5"
    local elapsed activity progress
    while kill -0 "$parent" 2>/dev/null; do
        sleep "$interval"
        kill -0 "$parent" 2>/dev/null || break
        elapsed=$((SECONDS - started))
        progress="$(suite_print_progress "$stage")"
        activity="$(suite_safe_log_activity "$log" 1)"
        printf '%s; %s is still running (elapsed %ds)\n' \
            "$progress" "$stage" "$elapsed"
        if [[ -n "$activity" ]]; then
            printf 'Latest non-secret activity: %s\n' "$activity"
        fi
    done
}

suite_start_progress_monitor() {
    local stage="$1" log="$2" started="$3" interval="${SUITE_PROGRESS_INTERVAL:-}"
    if [[ -z "$interval" ]]; then
        if [[ -t 1 ]]; then interval=15; else interval=0; fi
    fi
    [[ "$interval" =~ ^[0-9]+$ ]] || interval=15
    (( interval > 0 )) || return 0
    suite_progress_monitor "$stage" "$log" "$started" "$$" "$interval" &
    SUITE_MONITOR_PID="$!"
}

suite_stop_progress_monitor() {
    if [[ -n "${SUITE_MONITOR_PID:-}" ]]; then
        kill "$SUITE_MONITOR_PID" 2>/dev/null || true
        wait "$SUITE_MONITOR_PID" 2>/dev/null || true
        SUITE_MONITOR_PID=""
    fi
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
    local fingerprint marker saved status had_errexit stage_started operation_started
    case $- in
        *e*) had_errexit=1 ;;
        *) had_errexit=0 ;;
    esac
    shift 3
    fingerprint="$(suite_stage_fingerprint "$stage" "$SUITE_PREVIOUS_FINGERPRINT" "$@")" || return
    marker="$(suite_stage_marker "$stage")"
    CURRENT_LOG="$SUITE_LOG_DIR/$stage.log"
    stage_started="$SECONDS"
    SUITE_MONITOR_PID=""
    suite_print_stage_header "$stage" "$CURRENT_LOG"
    suite_start_progress_monitor "$stage" "$CURRENT_LOG" "$stage_started"

    if [[ -f "$marker" ]]; then
        saved="$(cat "$marker")"
        if [[ "$saved" != "$fingerprint" ]]; then
            suite_stop_progress_monitor
            suite_set_run_state "$stage" blocked-config-change
            suite_fail "$stage was completed with different inputs. Automatic changes to completed stages are not supported; follow the upgrade/recovery guide instead of editing them through resume."
            return 1
        fi
        printf 'Checking completed stage: %s\n' "$stage"
        printf 'Step: repeat live verification before skipping this stage\n'
        operation_started="$SECONDS"
        # Do not put a stage function in an if/while/! condition. Bash ignores
        # errexit throughout such a function, including its nested subshells.
        set +e
        NEREID_VERIFY_TIMEOUT=30s NEREID_CURL_TIMEOUT=30 \
            "$verify_function" >> "$CURRENT_LOG" 2>&1
        status=$?
        if (( had_errexit )); then set -e; fi
        if (( status == 0 )); then
            suite_stop_progress_monitor
            printf 'Stage already complete and healthy: %s (verified in %ds)\n' \
                "$stage" "$((SECONDS - operation_started))"
            suite_set_run_state "$stage" complete
            suite_print_progress "$stage" complete
            suite_print_recent_activity "$stage" "$CURRENT_LOG" 1
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
    printf 'Step 1/2: stage action\n'
    operation_started="$SECONDS"
    set +e
    "$install_function" >> "$CURRENT_LOG" 2>&1
    status=$?
    if (( had_errexit )); then set -e; fi
    if (( status == 0 )); then
        printf 'Step 1/2 finished in %ds\n' "$((SECONDS - operation_started))"
        printf 'Step 2/2: live verification\n'
        operation_started="$SECONDS"
        set +e
        NEREID_VERIFY_TIMEOUT="${NEREID_INSTALL_VERIFY_TIMEOUT:-5m}" \
            NEREID_CURL_TIMEOUT="${NEREID_INSTALL_CURL_TIMEOUT:-300}" \
            "$verify_function" >> "$CURRENT_LOG" 2>&1
        status=$?
        if (( had_errexit )); then set -e; fi
        if (( status == 0 )); then
            printf 'Step 2/2 finished in %ds\n' "$((SECONDS - operation_started))"
            suite_stop_progress_monitor
            suite_atomic_write "$marker" "$fingerprint" || return
            suite_set_run_state "$stage" complete
            printf 'Stage complete: %s (elapsed %ds)\n' \
                "$stage" "$((SECONDS - stage_started))"
            suite_print_progress "$stage" complete
            suite_print_recent_activity "$stage" "$CURRENT_LOG" 3
            SUITE_PREVIOUS_FINGERPRINT="$fingerprint"
            return 0
        fi
    fi

    suite_stop_progress_monitor
    if (( status == SUITE_WAITING )); then
        suite_set_run_state "$stage" waiting
        if [[ -z "${SUITE_WAIT_REASON:-}" && -f "$SUITE_WAIT_REASON_FILE" ]]; then
            SUITE_WAIT_REASON="$(cat "$SUITE_WAIT_REASON_FILE")"
        fi
        printf 'Stage is waiting for an external action: %s (elapsed %ds)\n' \
            "$stage" "$((SECONDS - stage_started))" >&2
        if [[ -n "${SUITE_WAIT_REASON:-}" ]]; then
            printf '%s\n' "$SUITE_WAIT_REASON" >&2
        fi
        printf 'Complete the documented action, then rerun the same command. Private log: %s\n' "$CURRENT_LOG" >&2
    else
        suite_set_run_state "$stage" failed
        printf 'Stage failed: %s (exit %d, elapsed %ds). Fix the cause and rerun the same command. Private log: %s\n' \
            "$stage" "$status" "$((SECONDS - stage_started))" "$CURRENT_LOG" >&2
    fi
    suite_print_recent_activity "$stage" "$CURRENT_LOG" 8 >&2
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
    if [[ "${SUITE_VERSION_CHANNEL:-dev}" == "dev" ]]; then
        printf 'Suite version channel: dev (rolling 0.0.0-dev matrix)\n'
    else
        printf 'Suite release: v%s (pinned product matrix)\n' "$SUITE_VERSION_CHANNEL"
    fi
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
