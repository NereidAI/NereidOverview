#!/bin/bash
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0

# Per-component install hook: build public upstream target(s), substitute the
# operator-supplied Dex settings, then apply the rendered resources.
set -euo pipefail

MANIFESTS_DIR="${MANIFESTS_DIR:-/manifests}"
DEX_STATIC_EMAIL="${DEX_STATIC_EMAIL:-admin@example.org}"
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
)
PY

rendered=$(mktemp)
if ! kustomize build "$WFP_DIR" > "$rendered"; then
  echo "[ERROR] kustomize build failed: $TARGETS" >&2
  rm -f "$rendered"
  exit 1
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
