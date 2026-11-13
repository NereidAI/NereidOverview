#!/bin/bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Per-component install hook: kustomize build the upstream target(s) with the
# private-registry component, rewrite residual public image refs, then apply.
set -euo pipefail

MANIFESTS_DIR="${MANIFESTS_DIR:-/manifests}"
# Treaty §18: no committed internal registry hostname. An empty domain skips
# image rewriting entirely and leaves public coordinates for the node-level
# containerd mirror. Legacy flows that still need manifest-time rewriting
# inject REGISTRY_DOMAIN/REGISTRY_PROJECT from the operator environment.
REGISTRY_DOMAIN="${REGISTRY_DOMAIN:-}"
REGISTRY_PROJECT="${REGISTRY_PROJECT:-nereidai}"
DEX_STATIC_EMAIL="${DEX_STATIC_EMAIL:-admin@nereidforge.local}"
DEX_STATIC_PASSWORD_HASH="${DEX_STATIC_PASSWORD_HASH:-}"
TARGETS="${TARGETS:?TARGETS required}"

WFP_DIR="$MANIFESTS_DIR/.wfp-$(echo "$TARGETS" | md5sum | cut -c1-8)"
KUSTOMIZATION="$WFP_DIR/kustomization.yaml"
mkdir -p "$WFP_DIR"

python3 - "$MANIFESTS_DIR" "$TARGETS" "$WFP_DIR" <<'PY'
import sys, os
m, targets, wfp = sys.argv[1], sys.argv[2], sys.argv[3]
res = "\n".join(f"  - ../{t}" for t in targets.split(","))
open(os.path.join(wfp, "kustomization.yaml"), "w").write(
    "apiVersion: kustomize.config.k8s.io/v1beta1\n"
    "kind: Kustomization\n"
    "resources:\n" + res + "\n"
    "components:\n"
    "- ../common/private-registry\n"
)
PY

rendered=$(mktemp)
if ! kustomize build "$WFP_DIR" > "$rendered"; then
  echo "[ERROR] kustomize build failed: $TARGETS" >&2
  rm -f "$rendered"
  exit 1
fi

if [ -n "$REGISTRY_DOMAIN" ]; then
  PRIV="$REGISTRY_DOMAIN/$REGISTRY_PROJECT"
  sed -i -E \
    -e "s#quay.io/jetstack/cert-manager-acmesolver:v1.21.1#${PRIV}/jetstack/cert-manager-acmesolver:v1.21.1#g" \
    -e "s#registry.istio.io/release#${PRIV}/release#g" \
    -e "s#image: busybox:1\.28#image: ${PRIV}/library/busybox:1.28#g" \
    -e "s#gcr.io/knative-releases/#${PRIV}/knative-releases/#g" \
    -e "s#ghcr.io/containerd/busybox#${PRIV}/containerd/busybox#g" \
    -e "s#ghcr.io/kubeflow/kfp-driver:2\.17\.0#${PRIV}/kubeflow/kfp-driver:2.17.0#g" \
    -e "s#ghcr.io/kubeflow/kfp-launcher:2\.17\.0#${PRIV}/kubeflow/kfp-launcher:2.17.0#g" \
    -e "s#ghcr.io/kubeflow/kfp-frontend#${PRIV}/kubeflow/kfp-frontend:2.17.0#g" \
    -e "s#ghcr.io/kubeflow/katib/#${PRIV}/kubeflow/katib/#g" \
    -e "s#ghcr.io/kubeflow/kubeflow/notebook-servers/#${PRIV}/kubeflow/kubeflow/notebook-servers/#g" \
    -e "s#quay.io/argoproj/argoexec:v4\.0\.5#${PRIV}/argoproj/argoexec:v4.0.5#g" \
    "$rendered"
fi
sed -i -E \
  -e "s#^  DEX_USER_PASSWORD: .*#  DEX_USER_PASSWORD: ${DEX_STATIC_PASSWORD_HASH}#" \
  -e "s#email: user@example.com#email: ${DEX_STATIC_EMAIL}#g" \
  "$rendered"

if [ ! -s "$rendered" ]; then
  echo "[INFO] (no resources to apply, skipping) $TARGETS"
  rm -f "$rendered"
  exit 0
fi

if ! kubectl apply -f "$rendered" 2>"$rendered.err"; then
  if grep -qE "262144|Too long" "$rendered.err"; then
    echo "[WARN] annotation limit, retrying with server-side apply"
    if ! kubectl apply --server-side=true --field-manager=wfp --force-conflicts -f "$rendered"; then
      echo "[ERROR] server-side apply failed: $TARGETS" >&2
      cat "$rendered.err" >&2
      exit 1
    fi
  else
    echo "[ERROR] kubectl apply failed: $TARGETS" >&2
    cat "$rendered.err" >&2
    exit 1
  fi
fi
rm -f "$rendered" "$rendered.err" "$KUSTOMIZATION"
echo "[OK] applied: $TARGETS"
