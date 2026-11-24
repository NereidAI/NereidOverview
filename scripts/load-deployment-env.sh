#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Load persistent, non-secret deployment selections and the runbook helpers.
# Usage from the NereidOverview repository root:
#   source scripts/load-deployment-env.sh
# Credentials remain in the separate mode-0600 stores documented by the runbook.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Source this file instead of executing it: source scripts/load-deployment-env.sh" >&2
    exit 2
fi

_nereid_deployment_root="${DEPLOYMENT_ROOT:-$HOME/.nereidai-deployment}"
if [[ ! -r "$_nereid_deployment_root/deployment.env" ]]; then
    echo "Missing deployment environment: $_nereid_deployment_root/deployment.env" >&2
    echo "Create it with docs/deploy/install-suite.md section 2 first." >&2
    unset _nereid_deployment_root
    return 1
fi
# shellcheck disable=SC1090,SC1091
source "$_nereid_deployment_root/deployment.env"
unset _nereid_deployment_root

# Resolve a chart selector once and archive both its bytes and non-secret OCI
# evidence. A floating alias may not move while its archive is being pulled.
pull_nereid_chart() (
    set -euo pipefail
    umask 077
    local product="$1" selector="$2" pull_dir archive repository
    local digest_before digest_after resolved_version anonymous_dir oras_config
    [[ "$product" =~ ^[a-z0-9-]+$ ]] || {
        echo "Invalid chart product name: $product" >&2
        return 2
    }
    [[ "$selector" =~ ^0\.0\.0-dev(-[0-9a-f]{7})?$ ]] || {
        echo "Expected a development chart selector, got: $selector" >&2
        return 2
    }
    install -d -m 700 "$DEPLOY_LOG_ROOT/$product" "$DEPLOYMENT_ROOT/chart-archives"
    anonymous_dir="$(mktemp -d "$DEPLOYMENT_ROOT/anonymous-registry.XXXXXX")"
    trap 'rm -rf "$anonymous_dir"' EXIT
    oras_config="$anonymous_dir/oras.json"
    export HELM_REGISTRY_CONFIG="$anonymous_dir/helm.json"
    pull_dir="$(mktemp -d "$DEPLOYMENT_ROOT/chart-archives/${product}.XXXXXX")"
    repository="ghcr.io/nereidai/charts/${product}"
    oras resolve --registry-config "$oras_config" "${repository}:${selector}" \
        > "$DEPLOY_LOG_ROOT/$product/chart-digest.txt"
    digest_before="$(cat "$DEPLOY_LOG_ROOT/$product/chart-digest.txt")"
    helm pull "oci://${repository}" \
        --version "$selector" --destination "$pull_dir" 2>&1 \
        | tee "$DEPLOY_LOG_ROOT/$product/chart-pull.txt" >&2
    oras resolve --registry-config "$oras_config" "${repository}:${selector}" \
        > "$DEPLOY_LOG_ROOT/$product/chart-digest-after-pull.txt"
    digest_after="$(cat "$DEPLOY_LOG_ROOT/$product/chart-digest-after-pull.txt")"
    [[ "$digest_after" == "$digest_before" ]] || {
        echo "Chart selector moved during pull; retry with an immutable version: $product:$selector" >&2
        return 1
    }
    archive="$(find "$pull_dir" -maxdepth 1 -type f -name "${product}-*.tgz" -print -quit)"
    test -s "$archive"
    helm show chart "$archive" | tee "$DEPLOY_LOG_ROOT/$product/chart-metadata.txt" >&2
    resolved_version="$(helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"')"
    [[ "$resolved_version" =~ ^0\.0\.0-dev-[0-9a-f]{7}$ ]] || {
        echo "Chart did not retain an immutable development version: $product:$resolved_version" >&2
        return 1
    }
    [[ "$selector" == "0.0.0-dev" || "$resolved_version" == "$selector" ]] || {
        echo "Chart selector $selector resolved to unexpected version $resolved_version" >&2
        return 1
    }
    printf '%s\n' "$resolved_version" > "$DEPLOY_LOG_ROOT/$product/chart-resolved-version.txt"
    printf '%s\n' "$archive"
)

# Pull the pre installer by its resolved OCI digest, validate exactly the four
# published files, and persist only its non-secret resolved identity for later
# shells. The printed path is the extracted installer root.
pull_pre_nereidforge_installer() (
    set -euo pipefail
    umask 077
    local selector="${1:-$PRE_VERSION}" repository digest artifact_dir archive
    local resolved_version source_commit anonymous_dir oras_config
    [[ "$selector" == "$PRE_VERSION" ]]
    [[ "$selector" =~ ^0\.0\.0-dev(-[0-9a-f]{7})?$ ]] || {
        echo "Expected a development pre installer selector, got: $selector" >&2
        return 2
    }
    install -d -m 700 "$PRE_HANDOFF_DIR" "$PRE_RELEASE_DIR" \
        "$DEPLOY_LOG_ROOT/nereidforge"
    anonymous_dir="$(mktemp -d "$DEPLOYMENT_ROOT/anonymous-registry.XXXXXX")"
    trap 'rm -rf "$anonymous_dir"' EXIT
    oras_config="$anonymous_dir/oras.json"
    repository="ghcr.io/nereidai/pre-nereidforge-installer"
    oras resolve --registry-config "$oras_config" "${repository}:${selector}" \
        > "$PRE_RELEASE_DIR/installer-digest.txt"
    digest="$(cat "$PRE_RELEASE_DIR/installer-digest.txt")"
    oras manifest fetch --registry-config "$oras_config" "${repository}@${digest}" \
        > "$PRE_RELEASE_DIR/installer-manifest.json"
    mapfile -t metadata < <(python3 - "$PRE_RELEASE_DIR/installer-manifest.json" "$selector" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    manifest = json.load(source)
annotations = manifest.get("annotations", {})
version = annotations.get("org.opencontainers.image.version", "")
revision = annotations.get("org.opencontainers.image.revision", "")
if not re.fullmatch(r"0\.0\.0-dev-[0-9a-f]{7}", version):
    raise SystemExit(f"invalid immutable pre installer version annotation: {version!r}")
if sys.argv[2] != "0.0.0-dev" and version != sys.argv[2]:
    raise SystemExit(f"selector {sys.argv[2]} resolved to unexpected version {version}")
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit(f"invalid pre installer source revision annotation: {revision!r}")
short_revision = version.removeprefix("0.0.0-dev-")
if not revision.startswith(short_revision):
    raise SystemExit(
        f"pre installer version {version} does not match source revision {revision}"
    )
print(version)
print(revision)
PY
    )
    resolved_version="${metadata[0]}"
    source_commit="${metadata[1]}"
    artifact_dir="$PRE_RELEASE_DIR/artifacts/$resolved_version"
    install -d -m 700 "$artifact_dir"
    oras pull --output "$artifact_dir" --registry-config "$oras_config" \
        "${repository}@${digest}" 2>&1 \
        | tee "$DEPLOY_LOG_ROOT/nereidforge/pre-installer-pull.txt" >&2
    python3 - "$artifact_dir" "$resolved_version" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
version = sys.argv[2]
archive = f"pre-nereidforge-installer-{version}.tar.gz"
expected = {
    archive,
    archive + ".sha256",
    f"pre-nereidforge-installer-{version}.lock.json",
    f"pre-nereidforge-charts-{version}.txt",
}
entries = list(root.rglob("*"))
actual = {str(path.relative_to(root)) for path in entries if path.is_file() and not path.is_symlink()}
if actual != expected or any(path.is_symlink() or (not path.is_file() and not path.is_dir()) for path in entries):
    raise SystemExit(f"expected exactly the four pre installer files, found: {sorted(actual)}")
PY
    archive="pre-nereidforge-installer-${resolved_version}.tar.gz"
    (
        cd "$artifact_dir"
        sha256sum -c "${archive}.sha256" 2>&1 \
            | tee "$DEPLOY_LOG_ROOT/nereidforge/pre-installer-checksum.txt" >&2
    )
    tar -xzf "$artifact_dir/$archive" -C "$PRE_RELEASE_DIR"
    printf '%s\n' "$resolved_version" > "$PRE_RELEASE_DIR/resolved-version.txt"
    printf '%s\n' "$source_commit" > "$PRE_RELEASE_DIR/source-commit.txt"
    printf '%s\n' "$digest" > "$PRE_RELEASE_DIR/resolved-digest.txt"
    PRE_ROOT="$PRE_RELEASE_DIR/pre-nereidforge-installer-$resolved_version"
    test -s "$PRE_ROOT/install-lock.json"
    test -s "$artifact_dir/pre-nereidforge-charts-$resolved_version.txt"
    printf '%s\n' "$PRE_ROOT"
)

record_nereid_images() (
    set -euo pipefail
    umask 077
    local product="$1" pod_json
    pod_json="$(mktemp "$DEPLOY_LOG_ROOT/$product/pods.XXXXXX.json")"
    trap 'rm -f "$pod_json"' EXIT
    kubectl -n "$product" get pods -o json > "$pod_json"
    python3 - "$pod_json" <<'PY' | tee "$DEPLOY_LOG_ROOT/$product/image-digests.txt"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    pods = json.load(source).get("items")
if not isinstance(pods, list) or not pods:
    raise SystemExit("no pods found; refusing to record empty image evidence")

lines = []
for pod in pods:
    pod_name = pod.get("metadata", {}).get("name", "<unnamed>")
    spec = pod.get("spec", {})
    status = pod.get("status", {})
    for field, status_field, label in (
        ("initContainers", "initContainerStatuses", "initContainer"),
        ("containers", "containerStatuses", "container"),
    ):
        statuses = {
            item.get("name"): item
            for item in status.get(status_field, [])
            if isinstance(item, dict)
        }
        for container in spec.get(field, []) or []:
            name = container.get("name", "")
            image = container.get("image", "")
            image_id = statuses.get(name, {}).get("imageID", "")
            if not name or not image or "sha256:" not in image_id:
                raise SystemExit(
                    f"missing image or image digest for {pod_name} {label}/{name or '<unnamed>'}; "
                    "wait for image pulls and ready status before recording evidence"
                )
            lines.append(f"{pod_name}\n  {label}/{name} image={image}\n  {label}/{name} imageID={image_id}")
if not lines:
    raise SystemExit("no containers found; refusing to record empty image evidence")
print("\n".join(lines))
PY
)
