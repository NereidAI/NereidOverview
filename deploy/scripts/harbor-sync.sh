#!/usr/bin/env bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
#
# Single entry point for every operation that names the internal Harbor
# registry. Deployment standards section 15.3: this script and its untracked
# harbor.env are the ONLY place in the suite allowed to know the internal
# registry hostname and credentials. Product repositories carry public
# coordinates only; cluster nodes resolve them through the containerd
# mirror rendered by the `node-mirror` subcommand, so the same manifests
# work online and air-gapped without any edit.
#
# Configuration is read from the environment, or from an untracked
# deploy/scripts/harbor.env file copied from harbor.env.example:
#   HARBOR_HOST          Internal registry hostname, no scheme or path.
#                        Required for every subcommand; no committed default.
#   HARBOR_PROJECT       Default Harbor project (default: nereidai).
#   HARBOR_USER          Login username (optional for anonymous pull).
#   HARBOR_PASS          Login password/token; never commit, used via stdin.
#   INSECURE_SKIP_VERIFY true|false for self-signed Harbor TLS (default false).
#   DRY_RUN=1            Print the planned copy/render actions without
#                        contacting any registry or writing node files.
#
# Subcommands:
#   check                          Validate configuration and tooling.
#   login                          Authenticate the local copy tool to Harbor.
#   mirror <manifest-file>         Copy public refs into Harbor in bulk.
#   push <image-ref> [rel-target]  Copy one image into Harbor. The source may
#                                  be a public docker:// ref, a local daemon
#                                  image (docker-daemon:<name>:<tag>, the local
#                                  make build output) or an OCI archive
#                                  (oci-archive:<path>.tar:<tag>). A transport-
#                                  prefixed source requires the explicit
#                                  relative target; plain refs derive it.
#   node-mirror [--apply]          Render k3s registries.yaml to stdout, or
#                                  write /etc/rancher/k3s/registries.yaml.
#
# Manifest line format (blank lines and lines starting with # are ignored):
#   <public-image-ref> [<harbor-relative-target>]
# When the relative target is omitted it is derived as
# "$HARBOR_PROJECT/<upstream-repo-path>:<tag>", unless the upstream path
# already starts with the project name. Multi-arch indexes are copied whole.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${SCRIPT_DIR}/harbor.env" ]]; then
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/harbor.env"
fi

HARBOR_PROJECT="${HARBOR_PROJECT:-nereidai}"
INSECURE_SKIP_VERIFY="${INSECURE_SKIP_VERIFY:-false}"
DRY_RUN="${DRY_RUN:-0}"
REGISTRIES_FILE="/etc/rancher/k3s/registries.yaml"

usage() {
  sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_host() {
  [[ -n "${HARBOR_HOST:-}" ]] || die "HARBOR_HOST is required; set it in the environment or harbor.env (see harbor.env.example)."
}

copy_tool() {
  if command -v skopeo >/dev/null 2>&1; then
    echo "skopeo"
  elif command -v crane >/dev/null 2>&1; then
    echo "crane"
  else
    die "need skopeo or crane installed for registry-to-registry copies."
  fi
}

# derive_relative <public-ref>: strip the registry host and prefix the
# default project when the upstream path does not already begin with it.
derive_relative() {
  local ref="$1" rest
  rest="${ref#*://}"
  rest="${rest#*/}"
  if [[ "$rest" == "${HARBOR_PROJECT}/"* ]]; then
    echo "$rest"
  else
    echo "${HARBOR_PROJECT}/${rest}"
  fi
}

# as_source passes explicit skopeo transports through (docker-daemon:,
# oci-archive:, containers-storage:, docker://) and treats anything else as
# a public registry reference. Local make builds reach Harbor through the
# docker-daemon: transport; no product repository needs push tooling.
as_source() {
  local ref="$1"
  case "$ref" in
    docker://*|docker-daemon:*|oci-archive:*|containers-storage:*) echo "$ref" ;;
    *) echo "docker://${ref}" ;;
  esac
}

has_transport() {
  case "$1" in
    docker://*|docker-daemon:*|oci-archive:*|containers-storage:*) return 0 ;;
    *) return 1 ;;
  esac
}

copy_image() {
  local tool="$1" src="$2" dst="$3"
  echo "[mirror] ${src} -> ${dst}"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  if [[ "$tool" == "skopeo" ]]; then
    local tls_args=()
    [[ "$INSECURE_SKIP_VERIFY" == "true" ]] && tls_args=(--dest-tls-verify=false)
    skopeo copy --all "${tls_args[@]}" "$(as_source "$src")" "docker://${dst}"
  else
    if has_transport "$src"; then
      die "crane cannot read ${src%%:*} sources; install skopeo for local daemon/OCI copies."
    fi
    crane copy "$src" "$dst"
  fi
}

cmd_check() {
  require_host
  local tool
  tool="$(copy_tool)"
  echo "[ok] HARBOR_HOST=${HARBOR_HOST} project=${HARBOR_PROJECT} tool=${tool} dry_run=${DRY_RUN}"
}

cmd_login() {
  require_host
  [[ -n "${HARBOR_USER:-}" && -n "${HARBOR_PASS:-}" ]] \
    || die "HARBOR_USER and HARBOR_PASS are required for login."
  local tool
  tool="$(copy_tool)"
  echo "[login] ${HARBOR_USER}@${HARBOR_HOST} (${tool})"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  if [[ "$tool" == "skopeo" ]]; then
    local tls_args=()
    [[ "$INSECURE_SKIP_VERIFY" == "true" ]] && tls_args=(--tls-verify=false)
    echo "$HARBOR_PASS" | skopeo login "${tls_args[@]}" \
      -u "$HARBOR_USER" --password-stdin "$HARBOR_HOST"
  else
    echo "$HARBOR_PASS" | crane auth login -u "$HARBOR_USER" --password-stdin "$HARBOR_HOST"
  fi
}

cmd_mirror() {
  local manifest="${1:-}"
  [[ -n "$manifest" && -f "$manifest" ]] || die "usage: harbor-sync.sh mirror <manifest-file>"
  require_host
  local tool
  tool="$(copy_tool)"
  local line src rel dst
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    read -r src rel <<< "$line"
    [[ -n "$src" ]] || continue
    rel="${rel:-$(derive_relative "$src")}"
    dst="${HARBOR_HOST}/${rel}"
    copy_image "$tool" "$src" "$dst"
  done < "$manifest"
  echo "[done] manifest ${manifest} processed."
}

cmd_push() {
  local src="${1:-}" rel="${2:-}"
  [[ -n "$src" ]] || die "usage: harbor-sync.sh push <image-ref> [harbor-relative-target]"
  require_host
  local tool
  tool="$(copy_tool)"
  if has_transport "$src"; then
    # A local daemon image or OCI archive carries no public ref the relative
    # target could be derived from, so naming it is the operator's decision.
    [[ -n "$rel" ]] || die "source '${src%%:*}' requires an explicit harbor-relative target, e.g. nereidai/nereidlink:v0.0.1"
  else
    rel="${rel:-$(derive_relative "$src")}"
  fi
  copy_image "$tool" "$src" "${HARBOR_HOST}/${rel}"
}

render_registries_yaml() {
  require_host
  local registry
  cat <<EOF
# Generated by deploy/scripts/harbor-sync.sh node-mirror; do not edit by hand.
# Public coordinates are rewritten to the internal Harbor project, so pods
# keep their upstream/ghcr.io image references unchanged (deploy-standards §15.3).
mirrors:
EOF
  for registry in docker.io ghcr.io quay.io registry.k8s.io gcr.io nvcr.io; do
    cat <<EOF
  ${registry}:
    endpoint:
      - "https://${HARBOR_HOST}"
    rewrite:
      "^/(.*)\$": "/${HARBOR_PROJECT}/\$1"
EOF
  done
  cat <<EOF
configs:
  "${HARBOR_HOST}":
    auth:
      username: ${HARBOR_USER:-}
      password: ${HARBOR_PASS:-}
    tls:
      insecure_skip_verify: ${INSECURE_SKIP_VERIFY}
EOF
}

cmd_node_mirror() {
  local apply=0
  [[ "${1:-}" == "--apply" ]] && apply=1
  if [[ "$apply" == "0" ]]; then
    render_registries_yaml
    return 0
  fi
  [[ "$(id -u)" == "0" ]] || die "node-mirror --apply must run as root."
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would write ${REGISTRIES_FILE}"
    render_registries_yaml >/dev/null
    return 0
  fi
  mkdir -p "$(dirname "$REGISTRIES_FILE")"
  render_registries_yaml > "$REGISTRIES_FILE"
  chmod 600 "$REGISTRIES_FILE"
  echo "[ok] wrote ${REGISTRIES_FILE}; restart k3s (or k3s-agent) to apply."
}

main() {
  local sub="${1:-}"
  case "$sub" in
    check)       cmd_check ;;
    login)       cmd_login ;;
    mirror)      shift; cmd_mirror "$@" ;;
    push)        shift; cmd_push "$@" ;;
    node-mirror) shift; cmd_node_mirror "$@" ;;
    -h|--help|help|"") usage ;;
    *) die "unknown subcommand: ${sub} (see --help)" ;;
  esac
}

main "$@"
