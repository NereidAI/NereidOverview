#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Optional, resumable central-suite installation from one non-secret environment
# file. The complete manual path remains docs/deploy/install-suite.md.

set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=scripts/lib/suite-versions.sh
source "$SCRIPT_DIR/lib/suite-versions.sh"
# Product chart selectors default from the suite version matrix. A checkout
# exactly on a v* tag resolves to that release's pinned matrix; every other
# checkout uses the rolling dev channel. Explicit deployment.env values still
# take precedence because they are applied below as unset-only defaults.
SUITE_VERSION_CHANNEL="$(suite_resolve_version_channel "$REPO_ROOT")"
SUITE_VERSIONS_MANIFEST="$REPO_ROOT/deploy/suite-versions.yaml"
SUITE_VERSION_ASSIGNMENTS="$(python3 "$SCRIPT_DIR/lib/suite_versions.py" \
    --manifest "$SUITE_VERSIONS_MANIFEST" \
    --channel "$SUITE_VERSION_CHANNEL")" || {
    echo "FATAL: cannot resolve the suite version matrix for channel $SUITE_VERSION_CHANNEL" >&2
    exit 2
}
eval "$SUITE_VERSION_ASSIGNMENTS"
unset SUITE_VERSION_ASSIGNMENTS
COMMAND=run
CONFIG_PATH=""

usage() {
    cat <<'EOF'
Usage:
  scripts/install-suite.sh --config PATH [run]
  scripts/install-suite.sh --config PATH status

Run and resume use the same command. The configuration is non-secret shell
input. Site values, credentials, artifact locks, logs, and resume state are kept
under DEPLOYMENT_ROOT with restrictive permissions.
EOF
}

while (($#)); do
    case "$1" in
        --config)
            (($# >= 2)) || { echo "--config requires a path" >&2; exit 2; }
            CONFIG_PATH="$2"
            shift 2
            ;;
        run|status)
            [[ -z "${COMMAND_EXPLICIT:-}" ]] || { echo "Only one command is allowed" >&2; exit 2; }
            COMMAND="$1"
            COMMAND_EXPLICIT=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

[[ -n "$CONFIG_PATH" ]] || {
    usage >&2
    exit 2
}
CONFIG_PATH="$(readlink -f "$CONFIG_PATH")"
[[ -f "$CONFIG_PATH" && ! -L "$CONFIG_PATH" && -r "$CONFIG_PATH" ]] || {
    echo "Configuration must be a readable regular file: $CONFIG_PATH" >&2
    exit 2
}
[[ "$(stat -c '%u' "$CONFIG_PATH")" == "$(id -u)" ]] || {
    echo "Configuration must be owned by the current user: $CONFIG_PATH" >&2
    exit 2
}
(( (0$(stat -c '%a' "$CONFIG_PATH") & 077) == 0 )) || {
    echo "Configuration must not be accessible by group/other; chmod 600 $CONFIG_PATH" >&2
    exit 2
}

# shellcheck disable=SC1090,SC1091
source "$CONFIG_PATH"
export DEPLOYMENT_ENV_FILE="$CONFIG_PATH"

: "${DEPLOYMENT_ROOT:=$HOME/.nereidai-deployment}"
: "${DEPLOY_VALUES_ROOT:=$DEPLOYMENT_ROOT/deploy-values}"
: "${DEPLOY_LOG_ROOT:=$DEPLOYMENT_ROOT/deploy-logs}"
: "${NEREIDIDENTITY_VERSION:=$SUITE_DEFAULT_NEREIDIDENTITY_VERSION}"
: "${NEREIDSPHERE_VERSION:=$SUITE_DEFAULT_NEREIDSPHERE_VERSION}"
: "${NEREIDHORIZON_VERSION:=$SUITE_DEFAULT_NEREIDHORIZON_VERSION}"
: "${PRE_VERSION:=$SUITE_DEFAULT_PRE_VERSION}"
: "${NEREIDFORGE_VERSION:=$SUITE_DEFAULT_NEREIDFORGE_VERSION}"
: "${NEREIDLINK_VERSION:=$SUITE_DEFAULT_NEREIDLINK_VERSION}"
: "${STORAGE_CLASS:=nfs-csi}"
: "${LOCAL_STORAGE_CLASS:=local-path}"
: "${INGRESS_CLASS:=traefik}"
: "${POD_CIDR:=10.42.0.0/16}"
: "${SERVICE_CIDR:=10.43.0.0/16}"
: "${SPHERE_REPLICAS:=1}"
: "${NF_IMAGE_PROFILE:=cpu-xpu}"
: "${HARDWARE_PLUGINS:=}"
: "${SUITE_ADMIN_USERNAME:=admin}"
: "${SUITE_ADMIN_EMAIL:=admin@nereidai.local}"
: "${SUITE_ADMIN_FIRST_NAME:=Admin}"
: "${SUITE_ADMIN_LAST_NAME:=User}"
: "${SPHERE_SSO_ACCEPTANCE_CONFIRMED:=no}"
: "${HORIZON_SETUP_CONFIRMED:=no}"
: "${PRE_GATE_CONFIRMED:=no}"
: "${NF_GATE_CONFIRMED:=no}"
: "${NF_LIVE_ACCEPTANCE_CONFIRMED:=no}"

PRE_HANDOFF_DIR="$DEPLOY_VALUES_ROOT/nereidforge"
PRE_RELEASE_DIR="$DEPLOYMENT_ROOT/pre-nereidforge/$PRE_VERSION"
PRE_ENV_FILE="$PRE_HANDOFF_DIR/site.env"
NF_SECRET_DIR="$DEPLOYMENT_ROOT/secrets/nereidforge"
NF_VALUES_FILE="$PRE_HANDOFF_DIR/values.generated.yaml"
NF_OPERATOR_VALUES_FILE="$PRE_HANDOFF_DIR/operator-values.yaml"
QUICK_INSTALL_DIR="$DEPLOYMENT_ROOT/quick-install"
QUICK_VALUES_DIR="$QUICK_INSTALL_DIR/values"
QUICK_ARTIFACT_LOCK_DIR="$QUICK_INSTALL_DIR/artifact-locks"
SUITE_STATE_DIR="$QUICK_INSTALL_DIR/state"
SUITE_LOG_DIR="$DEPLOY_LOG_ROOT/quick-install"
# NereidLink creates a fixed empty-password platform admin in migration 0049 and
# exposes a one-time bootstrap API. The installer completes that bootstrap itself
# instead of leaving a setup screen for the first browser visitor.
LINK_ADMIN_EMAIL="admin@nereidai.local"
LINK_ADMIN_CREDENTIALS_FILE="$DEPLOY_VALUES_ROOT/nereidlink/admin-credentials.env"
# 0 (the default) lets the kernel assign the loopback port, so a busy host
# port can never break the bootstrap; a positive value pins a fixed port.
LINK_LOCAL_HTTP_PORT="${LINK_LOCAL_HTTP_PORT:-0}"
LINK_API_READY_ATTEMPTS="${LINK_API_READY_ATTEMPTS:-20}"
LINK_API_RETRY_DELAY="${LINK_API_RETRY_DELAY:-2}"
# Ingress readiness lags Deployment availability: EndpointSlice publication,
# the Traefik backend reload and, on a first install, cert-manager issuance of
# the TLS Secret all settle asynchronously. Product verification gates retry
# transient gateway/transport answers inside this bounded window instead of
# aborting on a single 503; 3xx/4xx answers and an exhausted budget still fail
# the stage closed.
INGRESS_VERIFY_ATTEMPTS="${INGRESS_VERIFY_ATTEMPTS:-30}"
INGRESS_VERIFY_RETRY_DELAY="${INGRESS_VERIFY_RETRY_DELAY:-5}"

export DEPLOYMENT_ROOT DEPLOY_VALUES_ROOT DEPLOY_LOG_ROOT DEPLOYMENT_ENV_FILE
export KUBECONTEXT BASE_DOMAIN NFS_SERVER NFS_EXPORT LINK_MQTTS_HOST
if [[ -n "${KUBECONFIG-}" ]]; then
    export KUBECONFIG
fi
export NEREIDIDENTITY_VERSION NEREIDSPHERE_VERSION NEREIDHORIZON_VERSION
export PRE_VERSION NEREIDFORGE_VERSION NEREIDLINK_VERSION
export STORAGE_CLASS LOCAL_STORAGE_CLASS INGRESS_CLASS POD_CIDR SERVICE_CIDR
export SPHERE_REPLICAS NF_IMAGE_PROFILE HARDWARE_PLUGINS
export SUITE_ADMIN_USERNAME SUITE_ADMIN_EMAIL SUITE_ADMIN_FIRST_NAME SUITE_ADMIN_LAST_NAME
export SPHERE_SSO_ACCEPTANCE_CONFIRMED HORIZON_SETUP_CONFIRMED PRE_GATE_CONFIRMED NF_GATE_CONFIRMED NF_LIVE_ACCEPTANCE_CONFIRMED
export PRE_HANDOFF_DIR PRE_RELEASE_DIR PRE_ENV_FILE NF_SECRET_DIR NF_VALUES_FILE NF_OPERATOR_VALUES_FILE
export QUICK_INSTALL_DIR QUICK_VALUES_DIR QUICK_ARTIFACT_LOCK_DIR SUITE_STATE_DIR SUITE_LOG_DIR

# The optional entrypoint must never inherit or persist credentials in its one
# public configuration channel. Private stores are initialized separately below.
for forbidden in \
    PG_ADMIN_PASSWORD SEAWEEDFS_S3_ACCESS_KEY SEAWEEDFS_S3_SECRET_KEY \
    DEX_STATIC_PASSWORD DEX_STATIC_PASSWORD_HASH \
    NEREIDFORGE_AUTH_JWT_SECRET NEREIDFORGE_SSO_NS_CLIENT_SECRET
do
    if [[ -n "${!forbidden-}" ]]; then
        echo "Credential variables are forbidden in quick-install configuration: $forbidden" >&2
        exit 2
    fi
done

if [[ ! -d "$DEPLOYMENT_ROOT" ]]; then
    install -d -m 700 "$DEPLOYMENT_ROOT"
fi
(( (0$(stat -c '%a' "$DEPLOYMENT_ROOT") & 077) == 0 )) || {
    echo "Deployment root must not be accessible by group/other: $DEPLOYMENT_ROOT" >&2
    exit 2
}
install -d -m 700 "$DEPLOY_VALUES_ROOT" "$DEPLOY_LOG_ROOT" \
    "$DEPLOYMENT_ROOT/chart-archives" "$QUICK_VALUES_DIR" \
    "$QUICK_ARTIFACT_LOCK_DIR" "$SUITE_STATE_DIR/stages" \
    "$SUITE_STATE_DIR/identity-initializations" "$SUITE_LOG_DIR" "$PRE_HANDOFF_DIR"
for product in nereididentity nereidsphere nereidhorizon nereidforge nereidlink; do
    install -d -m 700 "$DEPLOY_VALUES_ROOT/$product" "$DEPLOY_LOG_ROOT/$product"
done

# shellcheck source=scripts/load-deployment-env.sh
source "$SCRIPT_DIR/load-deployment-env.sh"
# shellcheck source=scripts/lib/suite-runner.sh
source "$SCRIPT_DIR/lib/suite-runner.sh"
# shellcheck source=scripts/lib/suite-artifacts.sh
source "$SCRIPT_DIR/lib/suite-artifacts.sh"

SUITE_STAGES=(
    prerequisites identity sphere sphere-acceptance horizon horizon-acceptance
    pre-artifact pre-infra pre-kubeflow pre-verify
    forge forge-acceptance link
)
declare -A SUITE_STAGE_DESCRIPTIONS=(
    [prerequisites]="Prepare cluster dependencies, storage, hardware plugins, and retained suite Secrets"
    [identity]="Install NereidIdentity and verify database, Keycloak, and OIDC readiness"
    [sphere]="Install NereidSphere and verify rollout and readiness"
    [sphere-acceptance]="Confirm the browser Sphere-to-Identity login and ticket flow"
    [horizon]="Install NereidHorizon and verify backend and frontend health"
    [horizon-acceptance]="Confirm the Horizon first-run browser setup"
    [pre-artifact]="Retrieve and verify the frozen Pre-NereidForge installer and private inputs"
    [pre-infra]="Install and verify only the Pre-NereidForge infrastructure"
    [pre-kubeflow]="Install and verify only the Kubeflow layer"
    [pre-verify]="Verify infrastructure, Kubeflow, Model Registry, and the NF handoff"
    [forge]="Install the frozen selected-profile NF charts and verify application rollouts"
    [forge-acceptance]="Run exact-commit NF business verification and retain the Link handoff"
    [link]="Install NereidLink, complete the one-time platform admin bootstrap, and verify migration, storage, MQTT, and application health"
)
declare -A SUITE_STAGE_INPUTS=(
    [prerequisites]="NFS_SERVER NFS_EXPORT STORAGE_CLASS LOCAL_STORAGE_CLASS INGRESS_CLASS HARDWARE_PLUGINS"
    [identity]="NEREIDIDENTITY_VERSION BASE_DOMAIN STORAGE_CLASS INGRESS_CLASS SUITE_ADMIN_USERNAME SUITE_ADMIN_EMAIL SUITE_ADMIN_FIRST_NAME SUITE_ADMIN_LAST_NAME"
    [sphere]="NEREIDSPHERE_VERSION BASE_DOMAIN SPHERE_REPLICAS INGRESS_CLASS"
    [sphere-acceptance]="SPHERE_SSO_ACCEPTANCE_CONFIRMED"
    [horizon]="NEREIDHORIZON_VERSION BASE_DOMAIN LOCAL_STORAGE_CLASS INGRESS_CLASS"
    [horizon-acceptance]="HORIZON_SETUP_CONFIRMED"
    [pre-artifact]="PRE_VERSION BASE_DOMAIN STORAGE_CLASS POD_CIDR SERVICE_CIDR PRE_GATE_CONFIRMED"
    [pre-infra]=""
    [pre-kubeflow]=""
    [pre-verify]=""
    [forge]="NEREIDFORGE_VERSION NF_IMAGE_PROFILE NF_GATE_CONFIRMED BASE_DOMAIN"
    [forge-acceptance]="NF_LIVE_ACCEPTANCE_CONFIRMED"
    [link]="NEREIDLINK_VERSION BASE_DOMAIN STORAGE_CLASS LOCAL_STORAGE_CLASS INGRESS_CLASS LINK_MQTTS_HOST"
)
# Preserve existing default-input fingerprints while recording an explicit
# verifier-only override as part of the acceptance stage's immutable identity.
if [[ -n "${NF_VERIFIER_REF:-}" ]]; then
    SUITE_STAGE_INPUTS[forge-acceptance]+=" NF_VERIFIER_REF"
fi

require_confirmation() {
    local variable="$1" reason="$2"
    [[ "${!variable:-no}" == yes ]] || {
        suite_wait "$reason"
        return
    }
}

suite_identity_initialization_marker() {
    printf '%s/identity-initializations/%s\n' "$SUITE_STATE_DIR" "$1"
}

suite_identity_may_have_been_initialized() {
    local target="$1" stage marker
    local target_seen=false
    marker="$(suite_identity_initialization_marker "$target")"
    [[ ! -e "$marker" && ! -L "$marker" ]] || return 0
    for stage in "${SUITE_STAGES[@]}"; do
        [[ "$stage" == "$target" ]] && target_seen=true
        if [[ "$target_seen" == true && -f "$(suite_stage_marker "$stage")" ]]; then
            return 0
        fi
    done
    [[ "$target_seen" == true ]] || return 0
    return 1
}

suite_record_identity_initialization() {
    local stage="$1" marker
    marker="$(suite_identity_initialization_marker "$stage")"
    if [[ -e "$marker" || -L "$marker" ]]; then
        [[ -f "$marker" && ! -L "$marker" ]] || {
            suite_fail "unsafe identity initialization record: $marker"
            return 1
        }
        [[ "$(cat "$marker")" == "stage=$stage" ]] || {
            suite_fail "invalid identity initialization record: $marker"
            return 1
        }
        return 0
    fi
    suite_atomic_write "$marker" "stage=$stage"
}

validate_configuration() (
    set -euo pipefail
    local required name version
    local -a required_names=(
        KUBECONTEXT BASE_DOMAIN NFS_SERVER NFS_EXPORT LINK_MQTTS_HOST
    )
    for name in "${required_names[@]}"; do
        [[ -n "${!name-}" ]] || {
            echo "Missing required configuration: $name" >&2
            exit 1
        }
    done
    [[ "$BASE_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || {
        echo "BASE_DOMAIN is not a valid DNS suffix" >&2
        exit 1
    }
    case "$BASE_DOMAIN" in
        example.org|*.example.org|example.com|*.example.com|*.invalid)
            echo "Replace the reserved BASE_DOMAIN placeholder with the actual site domain" >&2
            exit 1
            ;;
    esac
    [[ "$NFS_EXPORT" == /* ]] || {
        echo "NFS_EXPORT must be an absolute exported path" >&2
        exit 1
    }
    [[ "$SPHERE_REPLICAS" =~ ^[1-9][0-9]*$ ]] || {
        echo "SPHERE_REPLICAS must be a positive integer" >&2
        exit 1
    }
    [[ "$NF_IMAGE_PROFILE" == full || "$NF_IMAGE_PROFILE" == cpu-xpu ]] || {
        echo "NF_IMAGE_PROFILE must be full or cpu-xpu" >&2
        exit 1
    }
    for name in SPHERE_SSO_ACCEPTANCE_CONFIRMED HORIZON_SETUP_CONFIRMED PRE_GATE_CONFIRMED NF_GATE_CONFIRMED NF_LIVE_ACCEPTANCE_CONFIRMED; do
        [[ "${!name}" == yes || "${!name}" == no ]] || {
            echo "$name must be yes or no" >&2
            exit 1
        }
    done
    if [[ -n "${NF_VERIFIER_REF:-}" && ! "$NF_VERIFIER_REF" =~ ^[0-9a-f]{40}$ ]]; then
        echo "NF_VERIFIER_REF must be a full 40-character lowercase Git commit ID" >&2
        exit 1
    fi
    for version in \
        "$NEREIDIDENTITY_VERSION" "$NEREIDSPHERE_VERSION" "$NEREIDHORIZON_VERSION" \
        "$PRE_VERSION" "$NEREIDFORGE_VERSION" "$NEREIDLINK_VERSION"
    do
        [[ "$version" =~ ^0\.0\.0-dev(-[0-9a-f]{7})?$ ]] || {
            echo "The quick installer supports reviewed development selectors only: $version" >&2
            exit 1
        }
    done
    local plugin
    IFS=',' read -r -a plugins <<< "$HARDWARE_PLUGINS"
    for plugin in "${plugins[@]}"; do
        [[ -z "$plugin" ]] && continue
        case "$plugin" in
            intel-gpu|intel-npu|nvidia|amd) ;;
            *) echo "Unknown HARDWARE_PLUGINS entry: $plugin" >&2; exit 1 ;;
        esac
    done
    for name in helm oras kubectl git tar curl openssl base64 sha256sum python3 flock getent readlink stat; do
        command -v "$name" >/dev/null || {
            echo "Missing required host tool: $name" >&2
            exit 1
        }
    done
    python3 -c 'import boto3, yaml' >/dev/null
    if [[ -n "${KUBECONFIG-}" ]]; then
        local kubeconfig_path kubeconfig_seen=false
        local -a kubeconfig_files=()
        IFS=':' read -r -a kubeconfig_files <<< "$KUBECONFIG"
        for kubeconfig_path in "${kubeconfig_files[@]}"; do
            [[ -n "$kubeconfig_path" ]] || continue
            kubeconfig_seen=true
            [[ -r "$kubeconfig_path" ]] || {
                echo "KUBECONFIG component is not readable: $kubeconfig_path" >&2
                exit 1
            }
        done
        [[ "$kubeconfig_seen" == true ]] || {
            echo "KUBECONFIG does not name a configuration file" >&2
            exit 1
        }
    fi
)

render_product_values() {
    local product="$1"
    local site="$QUICK_VALUES_DIR/$product.site.yaml"
    RENDERED_PRODUCT_VALUES="$QUICK_VALUES_DIR/$product.generated.yaml"
    python3 "$SCRIPT_DIR/render-suite-site-values.py" \
        --product "$product" --output "$site"
    local -a command=(
        python3 "$SCRIPT_DIR/generate-suite-secrets.py" render
        --deployment-root "$DEPLOYMENT_ROOT"
        --product "$product"
        --input "$site"
        --output "$RENDERED_PRODUCT_VALUES"
    )
    if [[ -e "$RENDERED_PRODUCT_VALUES" ]]; then
        command+=(--force)
    fi
    if [[ "$product" == nereidlink ]]; then
        command+=(--forge-credentials "$PRE_HANDOFF_DIR/seaweedfs-credentials.yaml")
    fi
    "${command[@]}"
}

kubectl_error_is_not_found() {
    local output="$1" first_line
    first_line="${output%%$'\n'*}"
    [[ "$first_line" == "Error from server (NotFound):"* ]]
}

resource_exists() {
    local namespace="$1" kind="$2" name="$3" output
    local -a query=(kubectl)
    if [[ -n "$namespace" ]]; then
        query+=(-n "$namespace")
    fi
    query+=(get "$kind" "$name" -o name)
    if output="$("${query[@]}" 2>&1)"; then
        return 0
    fi
    if kubectl_error_is_not_found "$output"; then
        return 1
    fi
    printf 'Could not query %s/%s in %s\n' "$kind" "$name" "${namespace:-cluster}" >&2
    return 2
}

ensure_namespaces_and_ca() {
    local namespace
    for namespace in nereididentity nereidsphere nereidhorizon; do
        kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
    done
    kubectl -n cert-manager get secret nereid-internal-ca-tls \
        -o jsonpath='{.data.ca\.crt}' | base64 -d > "$DEPLOYMENT_ROOT/nereid-internal-ca.crt"
    chmod 600 "$DEPLOYMENT_ROOT/nereid-internal-ca.crt"
    for namespace in nereididentity nereidsphere nereidhorizon; do
        kubectl -n "$namespace" create secret generic nereid-internal-ca-tls \
            --from-file=ca.crt="$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
            --dry-run=client -o yaml | kubectl apply -f -
    done
}

install_prerequisites() (
    set -euo pipefail
    local store="$DEPLOYMENT_ROOT/secret-store/suite-secrets.json"
    [[ ! -L "$store" ]] || {
        echo "suite secret store must not be a symlink; stop for recovery" >&2
        return 1
    }
    if [[ ! -e "$store" ]] && suite_identity_may_have_been_initialized prerequisites; then
        echo "restore the canonical suite secret store from its encrypted backup; refusing to generate replacements on resume" >&2
        return 1
    fi
    suite_record_identity_initialization prerequisites
    python3 "$SCRIPT_DIR/generate-suite-secrets.py" init --deployment-root "$DEPLOYMENT_ROOT"
    helm repo add jetstack https://charts.jetstack.io --force-update
    helm repo update jetstack
    helm upgrade --install cert-manager jetstack/cert-manager \
        --namespace cert-manager --create-namespace \
        --version v1.15.3 --set installCRDs=true --wait --timeout 5m
    kubectl apply -f "$REPO_ROOT/deploy/prereqs/manifests/00-internal-ca.yaml"
    kubectl wait --for=condition=Ready clusterissuer internal-ca --timeout=120s
    ensure_namespaces_and_ca

    helm upgrade --install nfs-csi "$REPO_ROOT/deploy/prereqs/charts/nfs-csi" \
        --namespace kube-system \
        --set-string "nfs.nfs.server=$NFS_SERVER" \
        --set-string "nfs.nfs.share=$NFS_EXPORT" \
        --set-string "nfs.storageClass.name=$STORAGE_CLASS" \
        --wait --timeout 5m
    kubectl -n kube-system rollout status deploy/csi-nfs-controller --timeout=180s

    local plugin need_intel=false
    IFS=',' read -r -a plugins <<< "$HARDWARE_PLUGINS"
    for plugin in "${plugins[@]}"; do
        case "$plugin" in
            intel-gpu|intel-npu) need_intel=true ;;
        esac
    done
    if [[ "$need_intel" == true ]]; then
        kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/intel/nfd.yaml"
        kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/intel/node-feature-rules.yaml"
        kubectl -n node-feature-discovery rollout status deployment/nfd-master --timeout=180s
    fi
    for plugin in "${plugins[@]}"; do
        case "$plugin" in
            intel-gpu)
                kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/intel/intel-gpu-plugin.yaml"
                kubectl -n kube-system rollout status daemonset/intel-gpu-plugin --timeout=180s
                ;;
            intel-npu)
                kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/intel/intel-npu-plugin.yaml"
                kubectl -n kube-system rollout status daemonset/intel-npu-plugin --timeout=180s
                ;;
            nvidia)
                kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/nvidia-gpu-plugin.yaml"
                kubectl -n kube-system rollout status daemonset/nvidia-device-plugin-daemonset --timeout=180s
                ;;
            amd)
                kubectl apply -f "$REPO_ROOT/deploy/prereqs/device-plugins/amd-gpu-plugin.yaml"
                kubectl -n kube-system rollout status daemonset/amdgpu-device-plugin-daemonset --timeout=180s
                ;;
        esac
    done

    local cnpg_status
    if resource_exists "" crd clusters.postgresql.cnpg.io; then
        :
    else
        cnpg_status=$?
        (( cnpg_status == 1 )) || return "$cnpg_status"
        helm pull cloudnative-pg --repo https://cloudnative-pg.io/charts \
            --version 0.29.0 --destination "$DEPLOYMENT_ROOT/chart-archives"
        tar -xOzf "$DEPLOYMENT_ROOT/chart-archives/cloudnative-pg-0.29.0.tgz" \
            cloudnative-pg/templates/crds/crds.yaml | sed '1d;$d' \
            | kubectl apply --server-side --force-conflicts -f -
    fi
    kubectl get crd clusters.postgresql.cnpg.io >/dev/null
    storage_smoke
)

storage_smoke() (
    set -euo pipefail
    local name=nereidai-quick-nfs-smoke owner kind
    for kind in pvc pod; do
        if owner="$(kubectl -n default get "$kind" "$name" \
            -o jsonpath='{.metadata.labels.app\.kubernetes\.io/managed-by}' 2>&1)"
        then
            [[ "$owner" == nereidoverview-quick-install ]] || {
                echo "Refusing to replace an unlabeled or foreign storage-smoke resource: $kind/$name" >&2
                exit 1
            }
        elif ! kubectl_error_is_not_found "$owner"; then
            echo "Could not verify storage-smoke ownership for $kind/$name; refusing to mutate it" >&2
            exit 1
        fi
    done
    kubectl -n default delete pod "$name" --ignore-not-found --wait=true
    kubectl -n default apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: $name
  labels:
    app.kubernetes.io/managed-by: nereidoverview-quick-install
spec:
  accessModes: [ReadWriteMany]
  storageClassName: $STORAGE_CLASS
  resources:
    requests:
      storage: 1Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: $name
  labels:
    app.kubernetes.io/managed-by: nereidoverview-quick-install
spec:
  restartPolicy: Never
  containers:
    - name: probe
      image: docker.io/library/busybox:1.36.1
      command: ["sh", "-c", "printf suite-storage-ok > /data/probe && test \"\$(cat /data/probe)\" = suite-storage-ok"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: $name
EOF
    kubectl -n default wait --for=jsonpath='{.status.phase}'=Succeeded "pod/$name" --timeout=180s
    kubectl -n default delete pod "$name" --wait=true
    kubectl -n default delete pvc "$name" --wait=true
)

verify_hardware() (
    set -euo pipefail
    [[ -n "$HARDWARE_PLUGINS" ]] || return 0
    local nodes
    nodes="$(mktemp "$QUICK_INSTALL_DIR/nodes.XXXXXX.json")"
    trap 'rm -f -- '"$(printf '%q' "$nodes")" EXIT
    kubectl get nodes -o json > "$nodes"
    python3 - "$nodes" "$HARDWARE_PLUGINS" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    nodes = json.load(source).get("items", [])
plugins = {item for item in sys.argv[2].split(",") if item}
required = {
    "nvidia": {"nvidia.com/gpu"},
    "amd": {"amd.com/gpu"},
    "intel-gpu": {"gpu.intel.com/i915", "gpu.intel.com/xe"},
    "intel-npu": {"npu.intel.com/accel"},
}
for plugin in sorted(plugins):
    names = required[plugin]
    found = any(
        any(node.get("status", {}).get("capacity", {}).get(name) not in (None, "0") for name in names)
        for node in nodes
    )
    if not found:
        raise SystemExit(f"no node advertises a positive resource for {plugin}: {sorted(names)}")
PY
)

verify_prerequisites() (
    set -euo pipefail
    kubectl wait --for=condition=Ready clusterissuer internal-ca --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n kube-system rollout status deploy/csi-nfs-controller --timeout="$NEREID_VERIFY_TIMEOUT"
    local actual_server actual_share
    actual_server="$(kubectl get storageclass "$STORAGE_CLASS" -o jsonpath='{.parameters.server}')"
    actual_share="$(kubectl get storageclass "$STORAGE_CLASS" -o jsonpath='{.parameters.share}')"
    [[ "$actual_server" == "$NFS_SERVER" && "$actual_share" == "$NFS_EXPORT" ]] || {
        echo "StorageClass $STORAGE_CLASS does not match the frozen NFS configuration" >&2
        exit 1
    }
    kubectl get storageclass "$LOCAL_STORAGE_CLASS" >/dev/null
    kubectl get crd clusters.postgresql.cnpg.io >/dev/null
    verify_hardware
)

# Poll a product URL through the cluster Ingress until it answers with a 2xx
# status. `kubectl rollout status` only waits for the Pod's own readiness gate;
# the EndpointSlice, the Traefik backend and, on a first install, the
# cert-manager TLS Secret propagate afterwards, during which Traefik returns
# 502/503/504 or refuses the connection even though the Pod is already Ready.
# Only those transient gateway/transport failures are retried: a 3xx/4xx
# answer or an exhausted attempt budget fails the stage, so real routing or
# authentication faults are never masked. The response body is emitted on
# stdout for the caller to redirect, exactly like a direct curl invocation.
# Usage: wait_for_ingress_url "<label>" [curl flags...] "<url>" > file
wait_for_ingress_url() {
    local label="$1"; shift
    local attempt status curl_rc body err
    body="$(mktemp)"
    err="$(mktemp)"
    trap 'rm -f "$body" "$err"' RETURN
    for ((attempt = 1; attempt <= INGRESS_VERIFY_ATTEMPTS; attempt++)); do
        curl_rc=0
        if ! status=$(curl --silent --show-error \
                --max-time "$NEREID_CURL_TIMEOUT" \
                -o "$body" -w '%{http_code}' "$@" 2>"$err"); then
            curl_rc=$?
            status=""
        fi
        if [[ "$curl_rc" -eq 0 && "$status" =~ ^2[0-9][0-9]$ ]]; then
            cat "$body"
            rm -f "$body" "$err"
            return 0
        fi
        if [[ "$curl_rc" -eq 0 && "$status" =~ ^(3|4)[0-9][0-9]$ ]]; then
            echo "[ERROR] $label answered HTTP $status; failing without retry" >&2
            cat "$err" >&2 || true
            rm -f "$body" "$err"
            return 1
        fi
        if (( attempt < INGRESS_VERIFY_ATTEMPTS )); then
            echo "[INFO] $label not reachable through the Ingress yet" \
                "(attempt $attempt/$INGRESS_VERIFY_ATTEMPTS," \
                "http=${status:-none}, curl=$curl_rc); retrying in" \
                "${INGRESS_VERIFY_RETRY_DELAY}s" >&2
            sleep "$INGRESS_VERIFY_RETRY_DELAY"
        fi
    done
    echo "[ERROR] $label did not become reachable through the Ingress within" \
        "$INGRESS_VERIFY_ATTEMPTS attempts" >&2
    cat "$err" >&2 || true
    rm -f "$body" "$err"
    return 1
}

install_identity() (
    set -euo pipefail
    local chart
    chart="$(suite_pull_chart_frozen nereididentity "$NEREIDIDENTITY_VERSION")"
    render_product_values nereididentity
    helm upgrade --install nereididentity "$chart" \
        --namespace nereididentity --create-namespace --skip-crds \
        --wait --timeout 10m --values "$RENDERED_PRODUCT_VALUES"
)

verify_identity() (
    set -euo pipefail
    kubectl -n nereididentity wait --for=condition=Ready \
        clusters.postgresql.cnpg.io/keycloak-db --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereididentity rollout status statefulset/nereididentity-keycloak --timeout="$NEREID_VERIFY_TIMEOUT"
    wait_for_ingress_url "NereidIdentity OIDC discovery" \
        --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        "https://sso.$BASE_DOMAIN/auth/realms/nereidai/.well-known/openid-configuration" \
        > "$DEPLOY_LOG_ROOT/nereididentity/openid-configuration.json"
    record_nereid_images nereididentity
)

install_sphere() (
    set -euo pipefail
    local chart
    chart="$(suite_pull_chart_frozen nereidsphere "$NEREIDSPHERE_VERSION")"
    render_product_values nereidsphere
    helm upgrade --install nereidsphere "$chart" \
        --namespace nereidsphere --create-namespace \
        --wait --timeout 5m --values "$RENDERED_PRODUCT_VALUES"
)

verify_sphere() (
    set -euo pipefail
    kubectl -n nereidsphere rollout status deploy/nereidsphere --timeout="$NEREID_VERIFY_TIMEOUT"
    wait_for_ingress_url "NereidSphere readiness" \
        --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        "https://nereidsphere.$BASE_DOMAIN/readyz" >/dev/null
    record_nereid_images nereidsphere
)

install_sphere_acceptance() (
    set -euo pipefail
    require_confirmation SPHERE_SSO_ACCEPTANCE_CONFIRMED \
        "Open Sphere in an unauthenticated browser, complete the Identity login and a ticket verification, then set SPHERE_SSO_ACCEPTANCE_CONFIRMED=yes in deployment.env."
)

verify_sphere_acceptance() {
    [[ "$SPHERE_SSO_ACCEPTANCE_CONFIRMED" == yes ]]
}

install_horizon() (
    set -euo pipefail
    local chart
    chart="$(suite_pull_chart_frozen nereidhorizon "$NEREIDHORIZON_VERSION")"
    render_product_values nereidhorizon
    helm upgrade --install nereidhorizon "$chart" \
        --namespace nereidhorizon --create-namespace \
        --wait --timeout 8m --values "$RENDERED_PRODUCT_VALUES"
)

verify_horizon() (
    set -euo pipefail
    kubectl -n nereidhorizon rollout status deploy/nereidhorizon-backend --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidhorizon rollout status deploy/nereidhorizon-frontend --timeout="$NEREID_VERIFY_TIMEOUT"
    wait_for_ingress_url "NereidHorizon backend health" \
        --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        "https://nereidhorizon.$BASE_DOMAIN/api/health" >/dev/null
    wait_for_ingress_url "NereidHorizon setup status" \
        --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        "https://nereidhorizon.$BASE_DOMAIN/api/setup-status" \
        > "$DEPLOY_LOG_ROOT/nereidhorizon/setup-status.json"
    record_nereid_images nereidhorizon
)

install_horizon_acceptance() (
    set -euo pipefail
    require_confirmation HORIZON_SETUP_CONFIRMED \
        "Complete Horizon first-run Setup with the site's Open Horizon Exchange inputs, then set HORIZON_SETUP_CONFIRMED=yes in deployment.env."
)

verify_horizon_acceptance() {
    [[ "$HORIZON_SETUP_CONFIRMED" == yes ]]
}

render_pre_inputs() {
    PRE_NONSECRET_BASE_DOMAIN="$BASE_DOMAIN" \
    PRE_NONSECRET_STORAGE_CLASS="$STORAGE_CLASS" \
    PRE_NONSECRET_POD_CIDR="$POD_CIDR" \
    PRE_NONSECRET_SERVICE_CIDR="$SERVICE_CIDR" \
    PRE_NONSECRET_FRONTEND_HOST="nereidforge.$BASE_DOMAIN" \
    PRE_NONSECRET_SSO_NS_BASE_URL="https://nereidsphere.$BASE_DOMAIN" \
    PRE_NONSECRET_ENV_FILE="$PRE_ENV_FILE" \
    python3 - <<'PY'
import os
from pathlib import Path
import re
import shlex

path = Path(os.environ["PRE_NONSECRET_ENV_FILE"])
managed = {
    "BASE_DOMAIN": os.environ["PRE_NONSECRET_BASE_DOMAIN"],
    "STORAGE_CLASS": os.environ["PRE_NONSECRET_STORAGE_CLASS"],
    "POD_CIDR": os.environ["PRE_NONSECRET_POD_CIDR"],
    "SERVICE_CIDR": os.environ["PRE_NONSECRET_SERVICE_CIDR"],
    "DEX_STATIC_EMAIL": "admin@nereidforge.local",
    "FRONTEND_HOST": os.environ["PRE_NONSECRET_FRONTEND_HOST"],
    "SSO_MODE": "ns",
    "SSO_NS_BASE_URL": os.environ["PRE_NONSECRET_SSO_NS_BASE_URL"],
}
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
output = []
seen = set()
for line in lines:
    match = re.match(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
    key = match.group(1) if match else None
    if key in managed:
        if key not in seen:
            output.append(f"{key}={shlex.quote(managed[key])}")
            seen.add(key)
    else:
        output.append(line)
for key, value in managed.items():
    if key not in seen:
        output.append(f"{key}={shlex.quote(value)}")
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY
}

record_pre_secret() {
    local name="$1" value="$2"
    if [[ -z "${!name:-}" ]]; then
        if [[ "$PRE_IDENTITY_RECOVERY_REQUIRED" == true ]]; then
            echo "restore $name from the retained pre backup; refusing to generate a replacement on resume" >&2
            return 1
        fi
        suite_record_identity_initialization pre-artifact
        printf '%s=%q\n' "$name" "$value" >> "$PRE_ENV_FILE"
        printf -v "$name" '%s' "$value"
    fi
}

ensure_pre_secrets() {
    local resource_status resource kind name
    PRE_IDENTITY_RECOVERY_REQUIRED=false
    if suite_identity_may_have_been_initialized pre-artifact; then
        PRE_IDENTITY_RECOVERY_REQUIRED=true
    fi
    if resource_exists nereidforge secret "pg-$PG_CLUSTER_NAME-credentials"; then
        [[ -n "$PG_ADMIN_PASSWORD" ]] || {
            echo "Restore PG_ADMIN_PASSWORD from the retained backup; do not rotate the existing database identity" >&2
            return 1
        }
    else
        resource_status=$?
        (( resource_status == 1 )) || return "$resource_status"
        record_pre_secret PG_ADMIN_PASSWORD "$(openssl rand -hex 32)"
    fi

    local seaweed_present=false
    for resource in \
        "secret seaweedfs-s3-credentials" \
        "secret seaweedfs-s3-config" \
        "configmap seaweedfs-s3-config"
    do
        read -r kind name <<< "$resource"
        if resource_exists nereidforge "$kind" "$name"; then
            seaweed_present=true
        else
            resource_status=$?
            (( resource_status == 1 )) || return "$resource_status"
        fi
    done
    if [[ "$seaweed_present" == true ]]; then
        [[ -n "$SEAWEEDFS_S3_ACCESS_KEY" && -n "$SEAWEEDFS_S3_SECRET_KEY" ]] || {
            echo "Restore the retained SeaweedFS site credentials; do not generate replacements" >&2
            return 1
        }
    else
        record_pre_secret SEAWEEDFS_S3_ACCESS_KEY "$(openssl rand -hex 16)"
        record_pre_secret SEAWEEDFS_S3_SECRET_KEY "$(openssl rand -hex 40)"
    fi

    local auth_present=false
    if resource_exists "" namespace auth; then
        auth_present=true
    else
        resource_status=$?
        (( resource_status == 1 )) || return "$resource_status"
    fi
    if [[ "$auth_present" == true ]] && \
        [[ -z "$DEX_STATIC_PASSWORD" || -z "$DEX_STATIC_PASSWORD_HASH" ]]; then
        echo "Restore both retained Dex inputs; a partial or new Dex identity cannot be inferred" >&2
        return 1
    fi
    if [[ -n "$DEX_STATIC_PASSWORD_HASH" && -z "$DEX_STATIC_PASSWORD" ]]; then
        echo "Restore DEX_STATIC_PASSWORD from backup; do not generate a different one" >&2
        return 1
    fi
    record_pre_secret DEX_STATIC_PASSWORD "$(openssl rand -hex 24)"
    if [[ -z "$DEX_STATIC_PASSWORD_HASH" ]]; then
        local dex_hash
        dex_hash="$(printf '%s\n' "$DEX_STATIC_PASSWORD" | htpasswd -inBC 12 "" | tr -d ':\n')"
        record_pre_secret DEX_STATIC_PASSWORD_HASH "$dex_hash"
    fi
    chmod 600 "$PRE_ENV_FILE"
}

validate_pre_inputs() {
    local name resource_status
    local -a missing=()
    for name in \
        BASE_DOMAIN STORAGE_CLASS POD_CIDR SERVICE_CIDR \
        PG_CLUSTER_NAME PG_DB_NAME PG_DB_USER \
        DEX_STATIC_EMAIL DEX_STATIC_PASSWORD DEX_STATIC_PASSWORD_HASH \
        SSO_MODE SSO_NS_BASE_URL FRONTEND_HOST
    do
        [[ -n "${!name:-}" ]] || missing+=("$name")
    done
    ((${#missing[@]} == 0)) || {
        printf 'Missing required pre input: %s\n' "${missing[@]}" >&2
        return 1
    }
    [[ "$DEX_STATIC_EMAIL" == admin@nereidforge.local && "$SSO_MODE" == ns ]] || return 1
    kubectl get storageclass "$STORAGE_CLASS" >/dev/null

    local secret_password secret_username access_key secret_key
    if resource_exists nereidforge secret "pg-$PG_CLUSTER_NAME-credentials"; then
        secret_password="$(kubectl -n nereidforge get secret "pg-$PG_CLUSTER_NAME-credentials" -o jsonpath='{.data.password}' | base64 -d)"
        secret_username="$(kubectl -n nereidforge get secret "pg-$PG_CLUSTER_NAME-credentials" -o jsonpath='{.data.username}' | base64 -d)"
        [[ "$secret_username" == "$PG_DB_USER" && "$secret_password" == "$PG_ADMIN_PASSWORD" ]] || {
            echo "PostgreSQL site input does not match the retained canonical Secret" >&2
            return 1
        }
    else
        resource_status=$?
        (( resource_status == 1 )) || return "$resource_status"
        [[ -n "$PG_ADMIN_PASSWORD" ]] || {
            echo "PG_ADMIN_PASSWORD is required before the first infrastructure stage" >&2
            return 1
        }
    fi
    if resource_exists nereidforge secret seaweedfs-s3-credentials; then
        access_key="$(kubectl -n nereidforge get secret seaweedfs-s3-credentials -o jsonpath='{.data.accessKey}' | base64 -d)"
        secret_key="$(kubectl -n nereidforge get secret seaweedfs-s3-credentials -o jsonpath='{.data.secretKey}' | base64 -d)"
        [[ "$access_key" == "$SEAWEEDFS_S3_ACCESS_KEY" && "$secret_key" == "$SEAWEEDFS_S3_SECRET_KEY" ]] || {
            echo "SeaweedFS site inputs do not match the retained canonical Secret" >&2
            return 1
        }
    else
        resource_status=$?
        (( resource_status == 1 )) || return "$resource_status"
        [[ -n "$SEAWEEDFS_S3_ACCESS_KEY" && -n "$SEAWEEDFS_S3_SECRET_KEY" ]] || {
            echo "Retained SeaweedFS credentials are required" >&2
            return 1
        }
    fi

    local python=python3 dex_hash_file
    if [[ -x "$PRE_ROOT/.venv/bin/python" ]] && "$PRE_ROOT/.venv/bin/python" -c 'import boto3' >/dev/null 2>&1; then
        python="$PRE_ROOT/.venv/bin/python"
    fi
    "$python" -c 'import boto3' >/dev/null
    dex_hash_file="$(mktemp "$QUICK_INSTALL_DIR/dex.XXXXXX")"
    chmod 600 "$dex_hash_file"
    printf 'dex:%s\n' "$DEX_STATIC_PASSWORD_HASH" > "$dex_hash_file"
    if ! printf '%s\n' "$DEX_STATIC_PASSWORD" | htpasswd -iv "$dex_hash_file" dex >/dev/null 2>&1; then
        rm -f "$dex_hash_file"
        echo "Dex plaintext and bcrypt hash do not match" >&2
        return 1
    fi
    rm -f "$dex_hash_file"
}

prepare_pre_runtime() {
    suite_prepare_pre_frozen "$PRE_VERSION"
    SOURCE_COMMIT="$PRE_SOURCE_COMMIT"
    export SOURCE_COMMIT
    # shellcheck disable=SC1090,SC1091
    source "$PRE_ROOT/scripts/lib/config.sh"
    assert_cluster_binding
}

install_pre_artifact() (
    set -euo pipefail
    require_confirmation PRE_GATE_CONFIRMED \
        "Verify the selected pre installer and five supporting charts through the independent anonymous publication gate, then set PRE_GATE_CONFIRMED=yes."
    suite_prepare_pre_frozen "$PRE_VERSION"
    render_pre_inputs
    prepare_pre_runtime
    command -v htpasswd >/dev/null
    command -v envsubst >/dev/null
    ensure_pre_secrets
    validate_pre_inputs
    helm repo add cloudnative-pg https://cloudnative-pg.io/charts --force-update
    helm repo update cloudnative-pg
)

verify_pre_artifact() (
    set -euo pipefail
    [[ "$PRE_GATE_CONFIRMED" == yes ]]
    prepare_pre_runtime
    validate_pre_inputs
)

install_pre_infra() (
    set -euo pipefail
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/10_infra.sh"
    assert_cluster_binding
)

verify_pre_infra() (
    set -euo pipefail
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/60_verify/infra-check.sh"
    assert_cluster_binding
)

install_pre_kubeflow() (
    set -euo pipefail
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/30_install-kubeflow.sh"
    assert_cluster_binding
)

verify_pre_kubeflow() (
    set -euo pipefail
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/60_verify/kubeflow-check.sh"
    assert_cluster_binding
)

install_pre_verify() {
    verify_pre_verify
}

verify_pre_verify() (
    set -euo pipefail
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/60_verify/infra-check.sh"
    bash "$PRE_ROOT/scripts/60_verify/kubeflow-check.sh"
    bash "$PRE_ROOT/scripts/60_verify/mr-check.sh"
    test -s "$NF_VALUES_FILE"
    assert_cluster_binding
)

prepare_nf_secrets() {
    local nf_identity_recovery=false
    if suite_identity_may_have_been_initialized forge; then
        nf_identity_recovery=true
    fi
    install -d -m 700 "$NF_SECRET_DIR"
    NF_SECRET_DIR="$NF_SECRET_DIR" PRE_HANDOFF_DIR="$PRE_HANDOFF_DIR" \
        DEPLOYMENT_ROOT="$DEPLOYMENT_ROOT" \
        NF_IDENTITY_RECOVERY_REQUIRED="$nf_identity_recovery" \
        NF_IDENTITY_INITIALIZATION_MARKER="$(suite_identity_initialization_marker forge)" \
        python3 - <<'PY'
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess

root = Path(os.environ["NF_SECRET_DIR"])
deployment = Path(os.environ["DEPLOYMENT_ROOT"])
store_path = deployment / "secret-store" / "suite-secrets.json"
store = json.loads(store_path.read_text(encoding="utf-8"))
expected_sso = store["secrets"]["sphere.ticket.forge"]
recovery_required = os.environ["NF_IDENTITY_RECOVERY_REQUIRED"] == "true"
identity_marker = Path(os.environ["NF_IDENTITY_INITIALIZATION_MARKER"])


def kubernetes_not_found(error):
    lines = error.splitlines()
    return bool(lines) and lines[0].startswith("Error from server (NotFound):")


def record_identity_initialization():
    if identity_marker.exists() or identity_marker.is_symlink():
        if (
            identity_marker.is_symlink()
            or not identity_marker.is_file()
            or identity_marker.read_text(encoding="utf-8") != "stage=forge\n"
        ):
            raise SystemExit("invalid NF identity initialization record; stop for recovery")
        return
    temporary = identity_marker.with_name(f".{identity_marker.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text("stage=forge\n", encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(identity_marker)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def live_secret(name):
    result = subprocess.run(
        ["kubectl", "-n", "nereidforge", "get", "secret", name, "-o", "json"],
        capture_output=True,
    )
    if result.returncode:
        error = result.stderr.decode("utf-8", "replace")
        if kubernetes_not_found(error):
            return None
        raise SystemExit(f"could not query retained Secret {name}; stop for recovery")
    document = json.loads(result.stdout)
    return {key: base64.b64decode(value).decode("utf-8") for key, value in document.get("data", {}).items()}

def retain_file(filename, key, live, generated=None):
    path = root / filename
    local = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    live_value = (live or {}).get(key, "")
    if live_value and local and live_value != local:
        raise SystemExit(f"local {filename} differs from the canonical Secret; refusing to replace either one")
    value = live_value or local
    if not value and generated and not recovery_required:
        record_identity_initialization()
        value = generated
    if not value:
        raise SystemExit(
            f"restore {filename} from the retained NF backup; refusing to generate a replacement on resume"
        )
    if not local:
        temporary = root / f".{filename}.{os.getpid()}.tmp"
        temporary.write_text(value, encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)
    return value

runtime = live_secret("nereidforge-service-credentials")
runtime_sso = (runtime or {}).get("NEREIDFORGE_SSO_NS_CLIENT_SECRET", "")
if runtime_sso and runtime_sso != expected_sso:
    raise SystemExit("Forge runtime SSO identity differs from Sphere; stop for recovery")
sso = retain_file("sso-client", "NEREIDFORGE_SSO_NS_CLIENT_SECRET", runtime, expected_sso)
if sso != expected_sso:
    raise SystemExit("local Forge SSO identity differs from Sphere")
jwt = retain_file("jwt", "NEREIDFORGE_AUTH_JWT_SECRET", runtime, secrets.token_hex(32))
admin = live_secret("nereidforge-admin-credentials")
password = retain_file("admin-password", "password", admin, secrets.token_hex(24))
patch = {
    "stringData": {
        "NEREIDFORGE_AUTH_JWT_SECRET": jwt,
        "NEREIDFORGE_SSO_NS_CLIENT_SECRET": sso,
    }
}
destination = root / "runtime-secret-patch.json"
temporary = root / f".{destination.name}.{os.getpid()}.tmp"
temporary.write_text(json.dumps(patch) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(destination)
print("Retained NF secret inputs are ready; values were not displayed")
PY
    kubectl -n nereidforge patch secret nereidforge-service-credentials \
        --type=merge --patch-file="$NF_SECRET_DIR/runtime-secret-patch.json"
    local resource_status
    if resource_exists nereidforge secret nereidforge-admin-credentials; then
        :
    else
        resource_status=$?
        (( resource_status == 1 )) || return "$resource_status"
        kubectl -n nereidforge create secret generic nereidforge-admin-credentials \
            --from-file=password="$NF_SECRET_DIR/admin-password" \
            --dry-run=client -o yaml | kubectl apply -f -
    fi
    if [[ ! -e "$NF_OPERATOR_VALUES_FILE" ]]; then
        printf '{}\n' > "$NF_OPERATOR_VALUES_FILE"
    fi
    chmod 600 "$NF_OPERATOR_VALUES_FILE"
}

install_forge() (
    set -euo pipefail
    require_confirmation NF_GATE_CONFIRMED \
        "Verify every image in the selected NF_IMAGE_PROFILE and exactly three NF charts through the independent anonymous gate, then set NF_GATE_CONFIRMED=yes."
    prepare_pre_runtime
    prepare_nf_secrets
    local app ml version chart
    app="$(suite_pull_chart_frozen nereidforge "$NEREIDFORGE_VERSION")"
    ml="$(suite_pull_chart_frozen nereidforge-ml-backend "$NEREIDFORGE_VERSION")"
    version="$(suite_frozen_chart_version nereidforge "$NEREIDFORGE_VERSION")"
    for chart in nereidforge-ml-backend; do
        [[ "$(suite_frozen_chart_version "$chart" "$NEREIDFORGE_VERSION")" == "$version" ]] || {
            echo "NF application charts resolved to different versions" >&2
            exit 1
        }
    done
    printf '%s\n' "$version" > "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt"
    chmod 600 "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt"
    bash "$PRE_ROOT/scripts/40_check-nf-handoff.sh"
    helm upgrade --install nereidforge "$app" --namespace nereidforge \
        -f "$NF_VALUES_FILE" -f "$NF_OPERATOR_VALUES_FILE" --wait --timeout 10m
    helm upgrade --install ml-backend "$ml" --namespace nereidforge \
        -f "$NF_VALUES_FILE" -f "$NF_OPERATOR_VALUES_FILE" --wait --timeout 10m
    assert_cluster_binding
)

verify_forge() (
    set -euo pipefail
    [[ "$NF_GATE_CONFIRMED" == yes ]]
    prepare_pre_runtime
    bash "$PRE_ROOT/scripts/40_check-nf-handoff.sh"
    kubectl -n nereidforge rollout status deploy/nereidforge-api --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidforge rollout status deploy/nereidforge-worker --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidforge rollout status deploy/nereidforge-frontend --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidforge rollout status deploy/ml-backend --timeout="$NEREID_VERIFY_TIMEOUT"
    record_nereid_images nereidforge
)

prepare_nf_verifier_checkout() {
    local checkout="$1" short_sha="$2"
    if ! git -C "$checkout" cat-file -e "$short_sha^{commit}"; then
        # A killed clone can leave .git without the required objects. Repair it
        # from the configured remote instead of skipping every later resume.
        git -C "$checkout" fetch --filter=blob:none origin || return 1
    fi
    git -C "$checkout" cat-file -e "$short_sha^{commit}" || return 1
    git -C "$checkout" checkout --detach "$short_sha" || return 1
    [[ "$(git -C "$checkout" rev-parse HEAD)" == "$short_sha"* ]] || return 1
}

run_nf_verifier() {
    local version short_sha verifier_ref checkout_id verifier temporary
    version="$(suite_frozen_chart_version nereidforge "$NEREIDFORGE_VERSION")"
    short_sha="${version#0.0.0-dev-}"
    if [[ "$short_sha" =~ ^[0-9a-f]{7}$ ]]; then
        # Legacy immutable development chart: its internal version names the
        # exact source commit, which stays the default verifier checkout.
        verifier_ref="$short_sha"
        checkout_id="$version"
    elif [[ "$version" == "0.0.0-dev" ]]; then
        # A floating development chart intentionally carries no source commit.
        # The reviewed verifier commit must therefore be named explicitly so
        # acceptance still runs an exact, reproducible checkout.
        [[ -n "${NF_VERIFIER_REF:-}" ]] || {
            echo "Floating 0.0.0-dev chart carries no source commit;" >&2
            echo "set NF_VERIFIER_REF to the reviewed full NereidForge commit ID" >&2
            return 1
        }
        verifier_ref="$NF_VERIFIER_REF"
        checkout_id="$version-verifier-$verifier_ref"
    else
        echo "NF verifier requires a supported development chart version: $version" >&2
        return 1
    fi
    if [[ -n "${NF_VERIFIER_REF:-}" && "$verifier_ref" != "$NF_VERIFIER_REF" ]]; then
        verifier_ref="$NF_VERIFIER_REF"
        checkout_id="$version-verifier-$NF_VERIFIER_REF"
    fi
    verifier="$DEPLOYMENT_ROOT/verifiers/nereidforge-$checkout_id"
    install -d -m 700 "$DEPLOYMENT_ROOT/verifiers"
    if [[ ! -d "$verifier/.git" ]]; then
        [[ ! -e "$verifier" ]] || {
            echo "NF verifier path exists but is not a Git checkout: $verifier" >&2
            return 1
        }
        temporary="$(mktemp -d "$DEPLOYMENT_ROOT/verifiers/.nereidforge-$checkout_id.XXXXXX")"
        if ! git clone --filter=blob:none --no-checkout \
            https://github.com/NereidAI/NereidForge.git "$temporary"; then
            rm -rf "$temporary"
            return 1
        fi
        if ! prepare_nf_verifier_checkout "$temporary" "$verifier_ref"; then
            rm -rf "$temporary"
            return 1
        fi
        if ! mv "$temporary" "$verifier"; then
            rm -rf "$temporary"
            return 1
        fi
    else
        prepare_nf_verifier_checkout "$verifier" "$verifier_ref" || return 1
    fi
    NF_ENV_FILE="$PRE_ENV_FILE" NF_HANDOFF_DIR="$PRE_HANDOFF_DIR" \
        bash "$verifier/scripts/60_verify/nf-check.sh"
}

write_link_handoff() {
    PRE_HANDOFF_DIR="$PRE_HANDOFF_DIR" python3 - <<'PY'
import base64
import json
import os
from pathlib import Path
import subprocess
import yaml

result = subprocess.run(
    ["kubectl", "-n", "nereidforge", "get", "secret", "seaweedfs-s3-credentials", "-o", "json"],
    capture_output=True,
    check=True,
)
document = json.loads(result.stdout)
data = document.get("data", {})
if set(data) < {"accessKey", "secretKey"}:
    raise SystemExit("canonical SeaweedFS Secret lacks the Link handoff keys")
credentials = {key: base64.b64decode(data[key]).decode("utf-8") for key in ("accessKey", "secretKey")}
if not all(credentials.values()):
    raise SystemExit("canonical SeaweedFS Secret contains an empty Link handoff value")
path = Path(os.environ["PRE_HANDOFF_DIR"]) / "seaweedfs-credentials.yaml"
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(yaml.safe_dump(credentials, sort_keys=False), encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
print("Link credential handoff retained; values were not displayed")
PY
}

install_forge_acceptance() (
    set -euo pipefail
    prepare_pre_runtime
    run_nf_verifier
    require_confirmation NF_LIVE_ACCEPTANCE_CONFIRMED \
        "Complete NF browser SSO/login/logout, a real KFP run, Label Studio/CVAT, notebook WebSocket, and four-bucket SeaweedFS acceptance, then set NF_LIVE_ACCEPTANCE_CONFIRMED=yes."
    write_link_handoff
    assert_cluster_binding
)

verify_forge_acceptance() (
    set -euo pipefail
    [[ "$NF_LIVE_ACCEPTANCE_CONFIRMED" == yes ]]
    PRE_HANDOFF_DIR="$PRE_HANDOFF_DIR" python3 - <<'PY'
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import yaml

path = Path(os.environ["PRE_HANDOFF_DIR"]) / "seaweedfs-credentials.yaml"
if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077:
    raise SystemExit("Link credential handoff must be a regular mode-0600 file")
try:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
except (UnicodeError, yaml.YAMLError) as error:
    mark = getattr(error, "problem_mark", None)
    location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
    raise SystemExit(
        f"invalid Link credential handoff YAML: {path}{location}; source content suppressed"
    ) from None
if not isinstance(document, dict) or set(document) != {"accessKey", "secretKey"}:
    raise SystemExit("Link credential handoff must contain exactly accessKey and secretKey")
if any(not isinstance(value, str) or not value for value in document.values()):
    raise SystemExit("Link credential handoff contains an invalid value")
result = subprocess.run(
    ["kubectl", "-n", "nereidforge", "get", "secret", "seaweedfs-s3-credentials", "-o", "json"],
    capture_output=True,
)
if result.returncode:
    raise SystemExit("could not read the canonical SeaweedFS Secret for Link verification")
try:
    data = json.loads(result.stdout).get("data", {})
    canonical = {
        key: base64.b64decode(data[key]).decode("utf-8")
        for key in ("accessKey", "secretKey")
    }
except (KeyError, UnicodeError, ValueError):
    raise SystemExit("canonical SeaweedFS Secret has an invalid Link identity") from None
if document != canonical:
    raise SystemExit("Link credential handoff differs from the canonical SeaweedFS Secret")
PY
)

# Retain the kubectl port-forward log on failure and point the operator at it.
# The log carries only forwarding/bind diagnostics, never credentials.
link_retain_forward_log() {
    local message="$1"
    LINK_API_FORWARD_KEPT=yes
    suite_fail "$message Retained diagnostic: $DEPLOY_LOG_ROOT/nereidlink/api-port-forward.log"
}

# Establish a loopback-only forward to the Link app Pod and expose
# LINK_API_BASE/LINK_API_WORK_DIR. This mirrors the product post-deploy flow and
# keeps the one-time bootstrap call off the public Ingress. The local port is
# kernel-assigned unless LINK_LOCAL_HTTP_PORT pins one, so another host service
# cannot block the bootstrap by occupying a fixed port. Callers run in a
# subshell; the EXIT trap reaps the forward and removes temporary response files.
link_start_api_forward() {
    local pod attempt forward_log local_spec chosen_port
    LINK_API_WORK_DIR="$(mktemp -d "$QUICK_INSTALL_DIR/link-api.XXXXXX")"
    chmod 700 "$LINK_API_WORK_DIR"
    forward_log="$LINK_API_WORK_DIR/port-forward.log"
    pod="$(kubectl -n nereidlink get pod \
        -l app.kubernetes.io/component=app \
        -o jsonpath='{.items[0].metadata.name}')"
    if [[ -z "$pod" ]]; then
        rm -rf "$LINK_API_WORK_DIR"
        suite_fail "no NereidLink application Pod is available for the admin API forward"
        return 1
    fi
    LINK_API_FORWARD_KEPT=""
    if [[ "$LINK_LOCAL_HTTP_PORT" =~ ^[1-9][0-9]*$ ]]; then
        local_spec="${LINK_LOCAL_HTTP_PORT}:8080"
        chosen_port="$LINK_LOCAL_HTTP_PORT"
    else
        local_spec=":8080"
        chosen_port=""
    fi
    kubectl -n nereidlink port-forward --address 127.0.0.1 \
        "pod/$pod" "$local_spec" >"$forward_log" 2>&1 &
    LINK_API_PID=$!
    trap '
        kill "$LINK_API_PID" 2>/dev/null || true
        if [[ -n "${LINK_API_FORWARD_KEPT:-}" && -s "$LINK_API_WORK_DIR/port-forward.log" ]]; then
            cp "$LINK_API_WORK_DIR/port-forward.log" "$DEPLOY_LOG_ROOT/nereidlink/api-port-forward.log"
            chmod 600 "$DEPLOY_LOG_ROOT/nereidlink/api-port-forward.log"
        fi
        rm -rf "$LINK_API_WORK_DIR"
    ' EXIT
    if [[ -z "$chosen_port" ]]; then
        for ((attempt = 1; attempt <= LINK_API_READY_ATTEMPTS; attempt++)); do
            chosen_port="$(sed -n 's/^Forwarding from 127\.0\.0\.1:\([0-9][0-9]*\) -> 8080.*/\1/p' \
                "$forward_log" | head -n1)"
            [[ -n "$chosen_port" ]] && break
            if ! kill -0 "$LINK_API_PID" 2>/dev/null; then
                link_retain_forward_log "the NereidLink local API forward exited before selecting a port."
                return 1
            fi
            sleep "$LINK_API_RETRY_DELAY"
        done
        if [[ -z "$chosen_port" ]]; then
            link_retain_forward_log "the NereidLink local API forward did not select a local port within the retry budget."
            return 1
        fi
    fi
    LINK_API_BASE="http://127.0.0.1:${chosen_port}"
    for ((attempt = 1; attempt <= LINK_API_READY_ATTEMPTS; attempt++)); do
        if curl --noproxy '*' --silent --show-error --fail --max-time 5 \
            "$LINK_API_BASE/healthz" >/dev/null 2>&1; then
            return 0
        fi
        if ! kill -0 "$LINK_API_PID" 2>/dev/null; then
            link_retain_forward_log "the NereidLink local API forward exited before becoming ready."
            return 1
        fi
        sleep "$LINK_API_RETRY_DELAY"
    done
    link_retain_forward_log "NereidLink API did not become reachable on the local forward within the retry budget."
    return 1
}

# Complete Link's one-time platform admin bootstrap when it is still pending.
# An existing non-empty password is never reset: the API itself rejects a second
# bootstrap and this function does not call it once status reports completion.
bootstrap_link_admin() (
    set -euo pipefail
    local status_file response_file admin_password required
    link_start_api_forward
    status_file="$LINK_API_WORK_DIR/bootstrap-status.json"
    curl --noproxy '*' --silent --show-error --fail \
        --max-time "${NEREID_CURL_TIMEOUT:-60}" \
        "$LINK_API_BASE/v1/auth/bootstrap-status" -o "$status_file"
    required="$(python3 - "$status_file" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        body = json.load(source)
except (OSError, json.JSONDecodeError):
    raise SystemExit("invalid NereidLink bootstrap-status response")
if not isinstance(body.get("required"), bool):
    raise SystemExit("NereidLink bootstrap-status response lacks a boolean required field")
print("true" if body["required"] else "false")
PY
)"
    if [[ "$required" != true ]]; then
        printf '[INFO] Link platform admin is already initialized; existing password left unchanged\n'
        return 0
    fi
    if [[ -f "$LINK_ADMIN_CREDENTIALS_FILE" ]]; then
        # Resume after an interrupted bootstrap: reuse the retained password
        # instead of orphaning it with a second generated value.
        admin_password="$(sed -n 's/^LINK_ADMIN_PASSWORD=//p' "$LINK_ADMIN_CREDENTIALS_FILE" | head -n1)"
        if [[ -z "$admin_password" ]]; then
            suite_fail "retained Link admin credential file exists but contains no LINK_ADMIN_PASSWORD"
            exit 1
        fi
        printf '[INFO] Retrying Link admin bootstrap with the retained private password\n'
    else
        admin_password="$(openssl rand -hex 24)"
    fi
    response_file="$LINK_API_WORK_DIR/bootstrap-response.json"
    printf '{"password":"%s"}' "$admin_password" \
        | curl --noproxy '*' --silent --show-error --fail \
            --max-time "${NEREID_CURL_TIMEOUT:-60}" \
            -X POST "$LINK_API_BASE/v1/auth/bootstrap" \
            -H 'Content-Type: application/json' --data-binary @- \
            -o "$response_file"
    grep -q '"access_token"' "$response_file" || {
        suite_fail "NereidLink admin bootstrap response did not contain an access token"
        exit 1
    }
    suite_atomic_write "$LINK_ADMIN_CREDENTIALS_FILE" "$(printf '%s\n' \
        '# NereidLink built-in platform admin; save securely and never commit.' \
        "LINK_ADMIN_EMAIL=$LINK_ADMIN_EMAIL" \
        "LINK_ADMIN_PASSWORD=$admin_password")"
    printf '[INFO] Link platform admin initialized; private credential file: %s\n' \
        "$LINK_ADMIN_CREDENTIALS_FILE"
)

# Read-only gate used by live verification and by resume of a completed stage.
verify_link_bootstrap() (
    set -euo pipefail
    local status_file
    link_start_api_forward
    status_file="$LINK_API_WORK_DIR/bootstrap-status.json"
    curl --noproxy '*' --silent --show-error --fail \
        --max-time "${NEREID_CURL_TIMEOUT:-60}" \
        "$LINK_API_BASE/v1/auth/bootstrap-status" -o "$status_file"
    python3 - "$status_file" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as source:
        body = json.load(source)
except (OSError, json.JSONDecodeError):
    raise SystemExit("invalid NereidLink bootstrap-status response")
if body.get("required") is not False:
    raise SystemExit("NereidLink first-run administrator bootstrap is still required")
PY
    if [[ -f "$LINK_ADMIN_CREDENTIALS_FILE" ]]; then
        (( (0$(stat -c '%a' "$LINK_ADMIN_CREDENTIALS_FILE") & 077) == 0 )) || {
            suite_fail "Link admin credential file must be mode 0600: $LINK_ADMIN_CREDENTIALS_FILE"
            exit 1
        }
        grep -q "^LINK_ADMIN_EMAIL=$LINK_ADMIN_EMAIL$" "$LINK_ADMIN_CREDENTIALS_FILE" || {
            suite_fail "retained Link admin credential file has an unexpected administrator identity"
            exit 1
        }
    fi
    printf '[INFO] Link administrator bootstrap completion verified\n'
)

install_link() (
    set -euo pipefail
    local chart
    chart="$(suite_pull_chart_frozen nereidlink "$NEREIDLINK_VERSION")"
    render_product_values nereidlink
    kubectl create namespace nereidlink --dry-run=client -o yaml | kubectl apply -f -
    kubectl -n nereidlink create secret generic nereid-internal-ca-tls \
        --from-file=ca.crt="$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        --dry-run=client -o yaml | kubectl apply -f -
    helm upgrade --install nereidlink "$chart" \
        --namespace nereidlink --create-namespace \
        --wait --timeout 8m --values "$RENDERED_PRODUCT_VALUES"
    bootstrap_link_admin
)

verify_link_storage() (
    set -euo pipefail
    local deployment replicasets pods
    deployment="$(mktemp "$QUICK_INSTALL_DIR/link-deployment.XXXXXX.json")"
    replicasets="$(mktemp "$QUICK_INSTALL_DIR/link-replicasets.XXXXXX.json")"
    pods="$(mktemp "$QUICK_INSTALL_DIR/link-pods.XXXXXX.json")"
    trap 'rm -f -- '"$(printf '%q' "$deployment")"' '"$(printf '%q' "$replicasets")"' '"$(printf '%q' "$pods")" EXIT
    kubectl -n nereidlink get deployment nereidlink -o json > "$deployment"
    kubectl -n nereidlink get replicasets -o json > "$replicasets"
    kubectl -n nereidlink get pods -o json > "$pods"
    python3 - "$deployment" "$replicasets" "$pods" <<'PY'
import json
import sys


def load(path):
    with open(path, encoding="utf-8") as source:
        return json.load(source)


deployment = load(sys.argv[1])
replicasets = load(sys.argv[2]).get("items", [])
pods = load(sys.argv[3]).get("items", [])
deployment_metadata = deployment.get("metadata", {})
template = deployment.get("spec", {}).get("template", {})
init_names = {
    item.get("name")
    for item in template.get("spec", {}).get("initContainers", []) or []
    if isinstance(item, dict)
}
if "migrate" not in init_names:
    raise SystemExit("the current Link Deployment does not define the migrate init container")


def owns_deployment(resource):
    for owner in resource.get("metadata", {}).get("ownerReferences", []) or []:
        if not isinstance(owner, dict) or not owner.get("controller"):
            continue
        if owner.get("kind") != "Deployment" or owner.get("name") != "nereidlink":
            continue
        if owner.get("uid") == deployment_metadata.get("uid"):
            return True
    return False


def revision(replicaset):
    value = replicaset.get("metadata", {}).get("annotations", {}).get(
        "deployment.kubernetes.io/revision"
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SystemExit("a Link ReplicaSet has no valid Deployment revision") from None


matching = [
    replicaset
    for replicaset in replicasets
    if owns_deployment(replicaset)
    and replicaset.get("spec", {}).get("template") == template
]
if not matching:
    raise SystemExit("no ReplicaSet matches the current Link Deployment template")
current_revision = max(revision(replicaset) for replicaset in matching)
current = [replicaset for replicaset in matching if revision(replicaset) == current_revision]
if len(current) != 1:
    raise SystemExit("the current Link ReplicaSet is ambiguous")
current = current[0]
current_metadata = current.get("metadata", {})

migrations = []
for pod in pods:
    metadata = pod.get("metadata", {})
    owned = any(
        isinstance(owner, dict)
        and owner.get("controller")
        and owner.get("kind") == "ReplicaSet"
        and owner.get("name") == current_metadata.get("name")
        and owner.get("uid") == current_metadata.get("uid")
        for owner in metadata.get("ownerReferences", []) or []
    )
    if not owned or metadata.get("deletionTimestamp"):
        continue
    pod_name = metadata.get("name", "<unnamed>")
    spec = pod.get("spec", {})
    if "migrate" not in {
        item.get("name") for item in spec.get("initContainers", []) or []
        if isinstance(item, dict)
    }:
        raise SystemExit(f"current Link Pod {pod_name} has no migrate init container")
    statuses = {
        item.get("name"): item
        for item in pod.get("status", {}).get("initContainerStatuses", [])
        if isinstance(item, dict)
    }
    migrations.append((pod_name, statuses.get("migrate", {})))
if not migrations:
    raise SystemExit("no non-terminating Pods are owned by the current Link ReplicaSet")
for pod, status in migrations:
    terminated = status.get("state", {}).get("terminated", {})
    if terminated.get("exitCode") != 0:
        raise SystemExit(f"Link migration has not completed successfully for current Pod {pod}")
PY

    LINK_CREDENTIALS_FILE="$PRE_HANDOFF_DIR/seaweedfs-credentials.yaml" \
    LINK_BUCKET_ENDPOINT="https://seaweedfs-s3.nereidforge.$BASE_DOMAIN" \
    LINK_VERIFY_CA="$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
    python3 - <<'PY'
import os
from pathlib import Path
import boto3
import yaml

path = Path(os.environ["LINK_CREDENTIALS_FILE"])
try:
    credentials = yaml.safe_load(path.read_text(encoding="utf-8"))
except (UnicodeError, yaml.YAMLError) as error:
    mark = getattr(error, "problem_mark", None)
    location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
    raise SystemExit(f"invalid Link credential YAML{location}; source content suppressed") from None
if not isinstance(credentials, dict) or set(credentials) != {"accessKey", "secretKey"}:
    raise SystemExit("Link credential handoff must contain exactly accessKey and secretKey")
try:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["LINK_BUCKET_ENDPOINT"],
        aws_access_key_id=credentials["accessKey"],
        aws_secret_access_key=credentials["secretKey"],
        verify=os.environ["LINK_VERIFY_CA"],
    )
    client.head_bucket(Bucket="nereidlink")
    client.list_objects_v2(Bucket="nereidlink", MaxKeys=1)
except Exception as error:
    raise SystemExit(
        f"authenticated Link SeaweedFS bucket verification failed ({type(error).__name__})"
    ) from None
print("Link migration and authenticated SeaweedFS bucket checks passed")
PY
)

verify_link() (
    set -euo pipefail
    kubectl -n nereidlink rollout status deploy/nereidlink --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidlink rollout status deploy/nereidlink-frontend --timeout="$NEREID_VERIFY_TIMEOUT"
    kubectl -n nereidlink get svc nereidlink-mqtt >/dev/null
    wait_for_ingress_url "NereidLink readiness" \
        --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
        "https://nereidlink.$BASE_DOMAIN/healthz" >/dev/null
    verify_link_bootstrap
    record_nereid_images nereidlink
    verify_link_storage
    kubectl -n nereidlink logs deployment/nereidlink -c nereidlink --since=10m \
        >> "$DEPLOY_LOG_ROOT/nereidlink/startup.log"
    kubectl -n nereidlink exec deployment/nereidlink -c nereidlink -- \
        cat /var/lib/nereidlink/pki/ca.pem > "$DEPLOYMENT_ROOT/nereidlink-device-ca.pem"
    chmod 600 "$DEPLOYMENT_ROOT/nereidlink-device-ca.pem"
    openssl x509 -in "$DEPLOYMENT_ROOT/nereidlink-device-ca.pem" \
        -noout -subject -fingerprint -sha256
)

prepare_private_kubeconfig() {
    local source_config="${KUBECONFIG:-$HOME/.kube/config}" temporary actual_context
    temporary="$(mktemp "$QUICK_INSTALL_DIR/kubeconfig.XXXXXX")"
    chmod 600 "$temporary"
    KUBECONFIG="$source_config" kubectl --context="$KUBECONTEXT" \
        config view --minify --flatten --raw -o yaml > "$temporary"
    actual_context="$(KUBECONFIG="$temporary" kubectl config current-context)"
    [[ "$actual_context" == "$KUBECONTEXT" ]] || {
        suite_fail "the private kubeconfig did not retain context $KUBECONTEXT"
        return 1
    }
    mv -f "$temporary" "$QUICK_INSTALL_DIR/kubeconfig"
    KUBECONFIG="$QUICK_INSTALL_DIR/kubeconfig"
    export KUBECONFIG
}

assert_cluster_binding() {
    local actual_context actual_uid
    [[ -f "$SUITE_STATE_DIR/cluster-context" && -f "$SUITE_STATE_DIR/cluster-uid" ]] || {
        suite_fail "cluster identity is not initialized"
        return 1
    }
    actual_context="$(kubectl config current-context)"
    actual_uid="$(kubectl get namespace kube-system -o jsonpath='{.metadata.uid}')"
    [[ "$actual_context" == "$(cat "$SUITE_STATE_DIR/cluster-context")" ]] || {
        suite_fail "the active context changed during installation"
        return 1
    }
    [[ -n "$actual_uid" && "$actual_uid" == "$(cat "$SUITE_STATE_DIR/cluster-uid")" ]] || {
        suite_fail "the live cluster identity changed during installation"
        return 1
    }
}

preflight_cluster() {
    local actual_context uid
    actual_context="$(kubectl config current-context)"
    [[ "$actual_context" == "$KUBECONTEXT" ]] || {
        suite_fail "kubectl context is $actual_context; expected $KUBECONTEXT"
        return 1
    }
    kubectl get --raw=/healthz >/dev/null
    uid="$(kubectl get namespace kube-system -o jsonpath='{.metadata.uid}')"
    [[ -n "$uid" ]] || {
        suite_fail "could not determine the live cluster identity"
        return 1
    }
    local releases="" namespace resource_status
    if [[ ! -f "$SUITE_STATE_DIR/cluster-context" ]]; then
        releases="$(helm list -A --all -o json | python3 -c '
import json, sys
managed = {
    "nereididentity", "nereidsphere", "nereidhorizon", "nereidforge",
    "ml-backend", "nereidlink",
}
releases = sorted(item["name"] for item in json.load(sys.stdin) if item.get("name") in managed)
print(",".join(releases))
')"
        for namespace in nereididentity nereidsphere nereidhorizon nereidforge nereidlink; do
            if resource_exists "" namespace "$namespace"; then
                releases="${releases:+$releases,}namespace/$namespace"
            else
                resource_status=$?
                (( resource_status == 1 )) || return "$resource_status"
            fi
        done
    fi
    suite_bind_cluster "$actual_context" "$uid" "$releases"
    assert_cluster_binding
    getent hosts "sso.$BASE_DOMAIN" >/dev/null
    getent hosts "nereidsphere.$BASE_DOMAIN" >/dev/null
    getent hosts "nereidhorizon.$BASE_DOMAIN" >/dev/null
    getent hosts "nereidforge.$BASE_DOMAIN" >/dev/null
    getent hosts "seaweedfs-s3.nereidforge.$BASE_DOMAIN" >/dev/null
    getent hosts "nereidlink.$BASE_DOMAIN" >/dev/null
    getent hosts "$NFS_SERVER" >/dev/null
}

run_installation() {
    validate_configuration
    suite_acquire_lock "$QUICK_INSTALL_DIR/install.lock"
    prepare_private_kubeconfig
    preflight_cluster
    printf 'Central suite progress counts completed stages, not elapsed time. Detailed output remains in private logs; the console shows filtered non-secret activity.\n'
    SUITE_PREVIOUS_FINGERPRINT=""
    suite_run_stage prerequisites install_prerequisites verify_prerequisites ${SUITE_STAGE_INPUTS[prerequisites]}
    suite_run_stage identity install_identity verify_identity ${SUITE_STAGE_INPUTS[identity]}
    suite_run_stage sphere install_sphere verify_sphere ${SUITE_STAGE_INPUTS[sphere]}
    suite_run_stage sphere-acceptance install_sphere_acceptance verify_sphere_acceptance ${SUITE_STAGE_INPUTS[sphere-acceptance]}
    suite_run_stage horizon install_horizon verify_horizon ${SUITE_STAGE_INPUTS[horizon]}
    suite_run_stage horizon-acceptance install_horizon_acceptance verify_horizon_acceptance ${SUITE_STAGE_INPUTS[horizon-acceptance]}
    suite_run_stage pre-artifact install_pre_artifact verify_pre_artifact ${SUITE_STAGE_INPUTS[pre-artifact]}
    suite_run_stage pre-infra install_pre_infra verify_pre_infra ${SUITE_STAGE_INPUTS[pre-infra]}
    suite_run_stage pre-kubeflow install_pre_kubeflow verify_pre_kubeflow ${SUITE_STAGE_INPUTS[pre-kubeflow]}
    suite_run_stage pre-verify install_pre_verify verify_pre_verify ${SUITE_STAGE_INPUTS[pre-verify]}
    suite_run_stage forge install_forge verify_forge ${SUITE_STAGE_INPUTS[forge]}
    suite_run_stage forge-acceptance install_forge_acceptance verify_forge_acceptance ${SUITE_STAGE_INPUTS[forge-acceptance]}
    suite_run_stage link install_link verify_link ${SUITE_STAGE_INPUTS[link]}
    printf 'Central suite installation is complete. Complete the external browser, edge, MQTT, and ESS acceptance checklist before production use.\n'
}

case "$COMMAND" in
    run) run_installation ;;
    status) suite_print_status ;;
esac
