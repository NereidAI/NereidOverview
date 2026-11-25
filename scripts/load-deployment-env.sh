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
_nereid_deployment_env="${DEPLOYMENT_ENV_FILE:-$_nereid_deployment_root/deployment.env}"
if [[ ! -r "$_nereid_deployment_env" ]]; then
    echo "Missing deployment environment: $_nereid_deployment_env" >&2
    echo "Create it with docs/deploy/install-suite.md section 2 first." >&2
    unset _nereid_deployment_root _nereid_deployment_env
    return 1
fi
# shellcheck disable=SC1090,SC1091
source "$_nereid_deployment_env"
unset _nereid_deployment_root _nereid_deployment_env

# Artifact intents are operator state, not command output. Once an anonymous
# selector has been resolved, every later retrieval uses the retained digest.
_nereid_atomic_write() (
    set -euo pipefail
    local destination="$1" content="$2" temporary
    temporary="$(mktemp "${destination}.tmp.XXXXXX")"
    trap 'rm -f -- '"$(printf '%q' "$temporary")" EXIT
    printf '%s\n' "$content" > "$temporary"
    chmod 600 "$temporary"
    mv -f "$temporary" "$destination"
    trap - EXIT
)

_nereid_expect_line() {
    local path="$1" expected="$2" description="$3"
    local -a lines
    [[ -f "$path" && ! -L "$path" ]] || {
        echo "Missing or unsafe $description: $path" >&2
        return 1
    }
    mapfile -t lines < "$path"
    (( ${#lines[@]} == 1 )) && [[ "${lines[0]}" == "$expected" ]] || {
        echo "Invalid $description: $path" >&2
        return 1
    }
}

_nereid_resolve_digest() (
    set -euo pipefail
    local intent="$1" evidence="$2" selector="$3" repository="$4" oras_config="$5"
    local completion="${6:-}" digest temporary
    if [[ -e "$intent" || -L "$intent" ]]; then
        [[ -f "$intent" && ! -L "$intent" ]] || {
            echo "Missing or unsafe OCI digest intent: $intent" >&2
            return 1
        }
        local -a lines
        mapfile -t lines < "$intent"
        (( ${#lines[@]} == 2 )) && [[ "${lines[0]}" == "selector=$selector" ]] \
            && [[ "${lines[1]}" =~ ^digest=sha256:[0-9a-f]{64}$ ]] || {
            echo "Invalid OCI digest intent for $selector: $intent" >&2
            return 1
        }
        digest="${lines[1]#digest=}"
    else
        if [[ -e "$evidence" || -L "$evidence" || \
            -n "$completion" && ( -e "$completion" || -L "$completion" ) ]]; then
            echo "Missing OCI digest intent with existing resume evidence: $intent" >&2
            return 1
        fi
        temporary="$(mktemp "${intent}.resolve.XXXXXX")"
        trap 'rm -f -- '"$(printf '%q' "$temporary")" EXIT
        oras resolve --registry-config "$oras_config" "${repository}:${selector}" > "$temporary"
        local -a resolved
        mapfile -t resolved < "$temporary"
        (( ${#resolved[@]} == 1 )) && [[ "${resolved[0]}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
            echo "Registry returned an invalid OCI digest for $repository:$selector" >&2
            return 1
        }
        digest="${resolved[0]}"
        _nereid_atomic_write "$intent" "$(printf 'selector=%q\ndigest=%q' "$selector" "$digest")"
        rm -f "$temporary"
        trap - EXIT
    fi
    if [[ -e "$evidence" || -L "$evidence" ]]; then
        _nereid_expect_line "$evidence" "$digest" "OCI digest evidence"
    else
        _nereid_atomic_write "$evidence" "$digest"
    fi
    printf '%s\n' "$digest"
)

_nereid_validate_pre_files() {
    python3 - "$1" "$2" <<'PY'
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
}

_nereid_validate_pre_identity() {
    python3 - "$1" "$2" "$3" "$4" <<'PY'
import re
import sys

selector, version, revision, digest = sys.argv[1:]
if not re.fullmatch(r"0\.0\.0-dev-[0-9a-f]{7}", version):
    raise SystemExit(f"invalid immutable pre installer version: {version!r}")
if selector != "0.0.0-dev" and version != selector:
    raise SystemExit(f"selector {selector} resolved to unexpected version {version}")
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit(f"invalid pre installer source revision: {revision!r}")
if not revision.startswith(version.removeprefix("0.0.0-dev-")):
    raise SystemExit(f"pre installer version {version} does not match source revision {revision}")
if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
    raise SystemExit(f"invalid pre installer OCI digest: {digest!r}")
PY
}

# Chart version shapes. The development channel uses the floating 0.0.0-dev
# selector, always resolved to an immutable 0.0.0-dev-<sha7> chart, while a
# suite release selects a bare SemVer chart. Resolved versions are always
# pinned, never the floating tag.
_NEREID_DEV_CHART_SELECTOR_RE='^0\.0\.0-dev(-[0-9a-f]{7})?$'
_NEREID_DEV_CHART_VERSION_RE='^0\.0\.0-dev-[0-9a-f]{7}$'
_NEREID_RELEASE_CHART_RE='^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(-[0-9A-Za-z][0-9A-Za-z.-]*)?$'

_nereid_is_supported_chart_selector() {
    [[ "$1" =~ $_NEREID_DEV_CHART_SELECTOR_RE || "$1" =~ $_NEREID_RELEASE_CHART_RE ]]
}

_nereid_is_supported_resolved_chart_version() {
    [[ "$1" =~ $_NEREID_DEV_CHART_VERSION_RE || "$1" =~ $_NEREID_RELEASE_CHART_RE ]]
}

# Resolve a chart selector once. The OCI manifest and chart blob are retrieved
# by digest, so neither an initial pull nor an interrupted pull can follow a
# moved floating tag. Completion evidence avoids all registry calls on rerun.
pull_nereid_chart() (
    set -euo pipefail
    umask 077
    local product="$1" selector="$2" pull_dir archive repository final_archive
    local digest layer_digest resolved_version archive_sha256 anonymous_dir oras_config
    local intent evidence complete candidate candidate_version content
    local COMPLETE_SELECTOR="" COMPLETE_DIGEST="" COMPLETE_LAYER_DIGEST=""
    local COMPLETE_RESOLVED_VERSION="" COMPLETE_ARCHIVE_SHA256="" COMPLETE_ARCHIVE=""
    [[ "$product" =~ ^[a-z0-9-]+$ ]] || {
        echo "Invalid chart product name: $product" >&2
        return 2
    }
    _nereid_is_supported_chart_selector "$selector" || {
        echo "Expected a development or release chart selector, got: $selector" >&2
        return 2
    }
    install -d -m 700 "$DEPLOY_LOG_ROOT/$product" "$DEPLOYMENT_ROOT/chart-archives"
    anonymous_dir="$(mktemp -d "$DEPLOYMENT_ROOT/anonymous-registry.XXXXXX")"
    trap 'rm -rf -- '"$(printf '%q' "$anonymous_dir")" EXIT
    oras_config="$anonymous_dir/oras.json"
    export HELM_REGISTRY_CONFIG="$anonymous_dir/helm.json"
    repository="ghcr.io/nereidai/charts/${product}"
    intent="$DEPLOY_LOG_ROOT/$product/chart-digest-intent-$selector.txt"
    evidence="$DEPLOY_LOG_ROOT/$product/chart-digest.txt"
    complete="$DEPLOY_LOG_ROOT/$product/chart-complete-$selector.env"
    digest="$(_nereid_resolve_digest \
        "$intent" "$evidence" "$selector" "$repository" "$oras_config" "$complete")"

    if [[ -e "$complete" || -L "$complete" ]]; then
        [[ -f "$complete" && ! -L "$complete" ]] || {
            echo "Missing or unsafe chart completion evidence: $complete" >&2
            return 1
        }
        # shellcheck disable=SC1090,SC1091
        source "$complete"
        [[ "$COMPLETE_SELECTOR" == "$selector" && "$COMPLETE_DIGEST" == "$digest" ]] || {
            echo "Chart completion identity mismatch: $product:$selector" >&2
            return 1
        }
        resolved_version="$COMPLETE_RESOLVED_VERSION"
        _nereid_is_supported_resolved_chart_version "$resolved_version" \
            && [[ "$selector" == "0.0.0-dev" || "$resolved_version" == "$selector" ]] \
            && [[ "$COMPLETE_LAYER_DIGEST" =~ ^sha256:[0-9a-f]{64}$ ]] \
            && [[ "$COMPLETE_ARCHIVE_SHA256" == "${COMPLETE_LAYER_DIGEST#sha256:}" ]] || {
            echo "Invalid chart completion identity: $product:$selector" >&2
            return 1
        }
        archive="$COMPLETE_ARCHIVE"
        [[ "$archive" == "$DEPLOYMENT_ROOT/chart-archives/$product-$resolved_version.tgz" \
            && -f "$archive" && ! -L "$archive" ]] || {
            echo "Frozen chart archive is missing or unsafe: $archive" >&2
            return 1
        }
        archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
        [[ "$archive_sha256" == "$COMPLETE_ARCHIVE_SHA256" ]] || {
            echo "Frozen chart archive digest mismatch: $product" >&2
            return 1
        }
        [[ "$(helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"')" == "$resolved_version" ]] || {
            echo "Frozen chart archive version changed: $product" >&2
            return 1
        }
        _nereid_expect_line "$DEPLOY_LOG_ROOT/$product/chart-resolved-version.txt" \
            "$resolved_version" "chart version evidence"
        printf '%s\n' "$archive"
        return 0
    fi

    pull_dir="$(mktemp -d "$DEPLOYMENT_ROOT/chart-archives/${product}.XXXXXX")"
    oras manifest fetch --registry-config "$oras_config" "${repository}@${digest}" \
        > "$pull_dir/manifest.json"
    layer_digest="$(python3 - "$pull_dir/manifest.json" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    manifest = json.load(source)
layers = [
    layer for layer in manifest.get("layers", [])
    if layer.get("mediaType") == "application/vnd.cncf.helm.chart.content.v1.tar+gzip"
]
if len(layers) != 1 or not re.fullmatch(r"sha256:[0-9a-f]{64}", layers[0].get("digest", "")):
    raise SystemExit("expected exactly one digest-addressed Helm chart layer")
print(layers[0]["digest"])
PY
    )"

    # A rename can complete just before a crash without the completion record.
    # Reuse only a top-level archive whose bytes equal the retained OCI layer.
    archive=""
    resolved_version=""
    while IFS= read -r -d '' candidate; do
        [[ "$(sha256sum "$candidate" | awk '{print $1}')" == "${layer_digest#sha256:}" ]] || continue
        candidate_version="$(helm show chart "$candidate" | awk '/^version:/ {print $2; exit}' | tr -d '"')"
        _nereid_is_supported_resolved_chart_version "$candidate_version" \
            && [[ "$selector" == "0.0.0-dev" || "$candidate_version" == "$selector" ]] || {
            echo "Recovered chart has an invalid version or selector: $candidate" >&2
            return 1
        }
        [[ "$candidate" == "$DEPLOYMENT_ROOT/chart-archives/$product-$candidate_version.tgz" ]] || continue
        [[ -z "$archive" || "$archive" == "$candidate" ]] || {
            echo "Ambiguous recovered chart archives for $product:$selector" >&2
            return 1
        }
        archive="$candidate"
        resolved_version="$candidate_version"
    done < <(find "$DEPLOYMENT_ROOT/chart-archives" -maxdepth 1 -type f \
        -name "$product-*.tgz" -print0)

    if [[ -z "$archive" ]]; then
        archive="$pull_dir/$product.tgz"
        oras blob fetch --output "$archive" --registry-config "$oras_config" \
            "${repository}@${layer_digest}" 2>&1 \
            | tee "$DEPLOY_LOG_ROOT/$product/chart-pull.txt" >&2
        archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
        [[ "$archive_sha256" == "${layer_digest#sha256:}" ]] || {
            echo "Downloaded chart blob digest mismatch: $product" >&2
            return 1
        }
        helm show chart "$archive" | tee "$DEPLOY_LOG_ROOT/$product/chart-metadata.txt" >&2
        resolved_version="$(helm show chart "$archive" | awk '/^version:/ {print $2; exit}' | tr -d '"')"
        _nereid_is_supported_resolved_chart_version "$resolved_version" || {
            echo "Chart did not retain a supported immutable version: $product:$resolved_version" >&2
            return 1
        }
        [[ "$selector" == "0.0.0-dev" || "$resolved_version" == "$selector" ]] || {
            echo "Chart selector $selector resolved to unexpected version $resolved_version" >&2
            return 1
        }
        final_archive="$DEPLOYMENT_ROOT/chart-archives/$product-$resolved_version.tgz"
        [[ ! -e "$final_archive" && ! -L "$final_archive" ]] || {
            echo "Refusing to replace an existing chart archive without valid completion evidence: $final_archive" >&2
            return 1
        }
        mv "$archive" "$final_archive"
        archive="$final_archive"
    fi

    archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
    _nereid_atomic_write "$DEPLOY_LOG_ROOT/$product/chart-resolved-version.txt" "$resolved_version"
    content="$(printf 'COMPLETE_SELECTOR=%q\nCOMPLETE_DIGEST=%q\nCOMPLETE_LAYER_DIGEST=%q\nCOMPLETE_RESOLVED_VERSION=%q\nCOMPLETE_ARCHIVE_SHA256=%q\nCOMPLETE_ARCHIVE=%q' \
        "$selector" "$digest" "$layer_digest" "$resolved_version" "$archive_sha256" "$archive")"
    _nereid_atomic_write "$complete" "$content"
    printf '%s\n' "$archive"
)

# Pull the pre installer by its resolved OCI digest, validate exactly the four
# published files, and persist only its non-secret resolved identity for later
# shells. The printed path is the extracted installer root.
pull_pre_nereidforge_installer() (
    set -euo pipefail
    umask 077
    local selector="${1:-$PRE_VERSION}" repository digest artifact_dir archive
    local resolved_version source_commit anonymous_dir oras_config intent complete
    local archive_sha256 content staging extract_dir extracted_root manifest_tmp
    local COMPLETE_SELECTOR="" COMPLETE_DIGEST="" COMPLETE_RESOLVED_VERSION=""
    local COMPLETE_SOURCE_COMMIT="" COMPLETE_ARCHIVE_SHA256="" COMPLETE_ARCHIVE="" COMPLETE_ROOT=""
    [[ "$selector" == "$PRE_VERSION" ]]
    [[ "$selector" =~ ^0\.0\.0-dev(-[0-9a-f]{7})?$ ]] || {
        echo "Expected a development pre installer selector, got: $selector" >&2
        return 2
    }
    install -d -m 700 "$PRE_HANDOFF_DIR" "$PRE_RELEASE_DIR" \
        "$PRE_RELEASE_DIR/artifacts" "$DEPLOY_LOG_ROOT/nereidforge"
    anonymous_dir="$(mktemp -d "$DEPLOYMENT_ROOT/anonymous-registry.XXXXXX")"
    trap 'rm -rf -- '"$(printf '%q' "$anonymous_dir")" EXIT
    oras_config="$anonymous_dir/oras.json"
    repository="ghcr.io/nereidai/pre-nereidforge-installer"
    intent="$PRE_RELEASE_DIR/installer-digest-intent.txt"
    complete="$PRE_RELEASE_DIR/installer-complete.env"
    digest="$(_nereid_resolve_digest "$intent" "$PRE_RELEASE_DIR/installer-digest.txt" \
        "$selector" "$repository" "$oras_config" "$complete")"

    if [[ -e "$complete" || -L "$complete" ]]; then
        [[ -f "$complete" && ! -L "$complete" ]] || {
            echo "Missing or unsafe pre installer completion evidence: $complete" >&2
            return 1
        }
        # shellcheck disable=SC1090,SC1091
        source "$complete"
        [[ "$COMPLETE_SELECTOR" == "$selector" && "$COMPLETE_DIGEST" == "$digest" ]] || {
            echo "Pre installer completion identity mismatch: $selector" >&2
            return 1
        }
        resolved_version="$COMPLETE_RESOLVED_VERSION"
        source_commit="$COMPLETE_SOURCE_COMMIT"
        _nereid_validate_pre_identity "$selector" "$resolved_version" "$source_commit" "$digest"
        PRE_ROOT="$COMPLETE_ROOT"
        archive="$COMPLETE_ARCHIVE"
        [[ "$PRE_ROOT" == "$PRE_RELEASE_DIR/pre-nereidforge-installer-$resolved_version" \
            && "$archive" == "$PRE_RELEASE_DIR/artifacts/$resolved_version/pre-nereidforge-installer-$resolved_version.tar.gz" \
            && -d "$PRE_ROOT" && ! -L "$PRE_ROOT" \
            && -s "$PRE_ROOT/install-lock.json" && ! -L "$PRE_ROOT/install-lock.json" \
            && -f "$archive" && ! -L "$archive" ]] || {
            echo "Frozen pre installer completion is incomplete or unsafe" >&2
            return 1
        }
        archive_sha256="$(sha256sum "$archive" | awk '{print $1}')"
        [[ "$archive_sha256" == "$COMPLETE_ARCHIVE_SHA256" ]] || {
            echo "Frozen pre installer archive digest mismatch" >&2
            return 1
        }
        _nereid_expect_line "$PRE_RELEASE_DIR/resolved-version.txt" "$resolved_version" "pre version evidence"
        _nereid_expect_line "$PRE_RELEASE_DIR/source-commit.txt" "$source_commit" "pre source evidence"
        _nereid_expect_line "$PRE_RELEASE_DIR/resolved-digest.txt" "$digest" "pre digest evidence"
        _nereid_validate_pre_files "$PRE_RELEASE_DIR/artifacts/$resolved_version" "$resolved_version"
        (
            cd "$PRE_RELEASE_DIR/artifacts/$resolved_version"
            sha256sum -c "pre-nereidforge-installer-$resolved_version.tar.gz.sha256" >&2
        )
        printf '%s\n' "$PRE_ROOT"
        return 0
    fi

    manifest_tmp="$(mktemp "$PRE_RELEASE_DIR/installer-manifest.XXXXXX.json")"
    oras manifest fetch --registry-config "$oras_config" "${repository}@${digest}" > "$manifest_tmp"
    mapfile -t metadata < <(python3 - "$manifest_tmp" "$selector" <<'PY'
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
    _nereid_atomic_write "$PRE_RELEASE_DIR/installer-manifest.json" "$(cat "$manifest_tmp")"
    rm -f "$manifest_tmp"
    artifact_dir="$PRE_RELEASE_DIR/artifacts/$resolved_version"
    archive="pre-nereidforge-installer-${resolved_version}.tar.gz"
    if [[ -e "$artifact_dir" || -L "$artifact_dir" ]]; then
        [[ -d "$artifact_dir" && ! -L "$artifact_dir" ]] || {
            echo "Unsafe pre installer artifact directory: $artifact_dir" >&2
            return 1
        }
    else
        staging="$(mktemp -d "$PRE_RELEASE_DIR/artifacts/.${resolved_version}.XXXXXX")"
        oras pull --output "$staging" --registry-config "$oras_config" \
            "${repository}@${digest}" 2>&1 \
            | tee "$DEPLOY_LOG_ROOT/nereidforge/pre-installer-pull.txt" >&2
        _nereid_validate_pre_files "$staging" "$resolved_version"
        (
            cd "$staging"
            sha256sum -c "${archive}.sha256" >&2
        )
        mv "$staging" "$artifact_dir"
    fi
    _nereid_validate_pre_files "$artifact_dir" "$resolved_version"
    (
        cd "$artifact_dir"
        sha256sum -c "${archive}.sha256" 2>&1 \
            | tee "$DEPLOY_LOG_ROOT/nereidforge/pre-installer-checksum.txt" >&2
    )
    archive_sha256="$(sha256sum "$artifact_dir/$archive" | awk '{print $1}')"

    PRE_ROOT="$PRE_RELEASE_DIR/pre-nereidforge-installer-$resolved_version"
    if [[ -e "$PRE_ROOT" || -L "$PRE_ROOT" ]]; then
        [[ -d "$PRE_ROOT" && ! -L "$PRE_ROOT" && -s "$PRE_ROOT/install-lock.json" \
            && ! -L "$PRE_ROOT/install-lock.json" ]] || {
            echo "Incomplete or unsafe extracted pre installer root: $PRE_ROOT" >&2
            return 1
        }
    else
        extract_dir="$(mktemp -d "$PRE_RELEASE_DIR/.extract.XXXXXX")"
        tar -xzf "$artifact_dir/$archive" -C "$extract_dir"
        extracted_root="$extract_dir/pre-nereidforge-installer-$resolved_version"
        [[ -d "$extracted_root" && ! -L "$extracted_root" \
            && -s "$extracted_root/install-lock.json" && ! -L "$extracted_root/install-lock.json" ]] || {
            echo "Extracted pre installer root is incomplete: $resolved_version" >&2
            return 1
        }
        mv "$extracted_root" "$PRE_ROOT"
        rm -rf "$extract_dir"
    fi
    test -s "$artifact_dir/pre-nereidforge-charts-$resolved_version.txt"
    _nereid_atomic_write "$PRE_RELEASE_DIR/resolved-version.txt" "$resolved_version"
    _nereid_atomic_write "$PRE_RELEASE_DIR/source-commit.txt" "$source_commit"
    _nereid_atomic_write "$PRE_RELEASE_DIR/resolved-digest.txt" "$digest"
    content="$(printf 'COMPLETE_SELECTOR=%q\nCOMPLETE_DIGEST=%q\nCOMPLETE_RESOLVED_VERSION=%q\nCOMPLETE_SOURCE_COMMIT=%q\nCOMPLETE_ARCHIVE_SHA256=%q\nCOMPLETE_ARCHIVE=%q\nCOMPLETE_ROOT=%q' \
        "$selector" "$digest" "$resolved_version" "$source_commit" "$archive_sha256" \
        "$artifact_dir/$archive" "$PRE_ROOT")"
    _nereid_atomic_write "$complete" "$content"
    printf '%s\n' "$PRE_ROOT"
)

record_nereid_images() (
    set -euo pipefail
    umask 077
    local product="$1" pod_json
    pod_json="$(mktemp "$DEPLOY_LOG_ROOT/$product/pods.XXXXXX.json")"
    trap 'rm -f -- '"$(printf '%q' "$pod_json")" EXIT
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
