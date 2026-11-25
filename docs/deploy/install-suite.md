# NereidAI Public Suite Installation Guide (k3s + Rancher)

Start with a ready, empty, Rancher-managed k3s cluster from
[`cluster-bootstrap.md`](cluster-bootstrap.md). This document is the complete
manual path: every phase is executed by the operator and accepted before the
next phase starts. The optional [resumable quick installer](quick-install.md)
provides the same ordering and gates through one non-secret environment file.
Operators may also use independent procedures and tooling; NereidOverview is a
convenience, not a required deployment controller.

Products install directly from versioned public GHCR OCI charts. No product
source checkout is needed for chart installation; §7.5 separately uses an
exact-commit verification-only NF checkout. NereidOverview supplies the shared
prerequisite manifests and this runbook; product repositories remain the chart
sources of truth.

> **Current stop point:** pre-NereidForge and NereidForge have independent
> anonymous `0.0.0-dev` artifact gates. Section 7.2 requires only the verified
> pre installer and five supporting charts. Do not start NF §§7.3–7.5 until the
> selected NF profile (23 `full` images, or 18 `cpu-xpu` images retaining Intel
> XPU) and three NF charts pass their separate gate. Live NF and
> SeaweedFS acceptance is still required; do not install Link until it passes.

## 1. Verified development channel and installation scope

These floating development selectors passed anonymous chart pull/render and
image-manifest verification on 2026-11-22:

| Product | OCI chart | Development selector |
|---|---|---|
| Identity | `oci://ghcr.io/nereidai/charts/nereididentity` | `0.0.0-dev` |
| Sphere | `oci://ghcr.io/nereidai/charts/nereidsphere` | `0.0.0-dev` |
| Horizon | `oci://ghcr.io/nereidai/charts/nereidhorizon` | `0.0.0-dev` |
| Link | `oci://ghcr.io/nereidai/charts/nereidlink` | `0.0.0-dev` |

The [dated evidence snapshot](reference/development-artifacts-2026-11-22.md)
binds that verification to the exact resolved chart versions/digests and image
index digests. It is historical evidence, not a per-commit installation pin.

A floating chart tag aliases the latest successfully published immutable
`0.0.0-dev-<short-sha>` OCI manifest. The downloaded archive retains that
short-SHA chart `version` and `appVersion`, so its suite images use the same
immutable snapshot. Third-party images retain their public upstream coordinates
and pinned versions.

The pre-NereidForge installer and NereidForge charts also use `0.0.0-dev`.
Section 2 writes every selector to one persistent `deployment.env`; no per-shell
version exports or per-commit edits are needed. Pre and NF resolve their floating
selectors independently to immutable `0.0.0-dev-<short-sha>` artifacts.

Record each resolved chart OCI digest and internal version, the running image
IDs/digests, selected kubecontext, and installation date in the deployment
hand-off. For deliberate reproduction, replace a floating selector in
`deployment.env` with its resolved `0.0.0-dev-<short-sha>` version only after
anonymously verifying that snapshot. Do not infer or invent release versions.

## 2. Operator environment

Required tools on the operator host: Helm with OCI support, ORAS 1.4 or newer,
`kubectl`, `git`, `tar`, `curl`, `openssl`, `base64`, `sha256sum`, `htpasswd`,
`envsubst`, and Python 3 with PyYAML. Pre-NereidForge also needs Python `boto3`;
its exact interpreter selection and preflight appear in §7.2. On Ubuntu,
`apache2-utils` provides `htpasswd` and `gettext-base` provides `envsubst`. The
operator host and every cluster node must reach all public artifact registries
referenced by the charts. DNS and TLS must be valid for every product endpoint.

### ORAS CLI installation

ORAS is required only on the operator host, not inside the cluster. The pre
installer helpers use it to resolve OCI digests, read source-version annotations,
and anonymously download the installer archive and checksum files. Install ORAS
1.4 or newer and ensure every later shell can find `oras` through `PATH`.

For Linux, the following commands install the pinned ORAS 1.4.0 release from the
official project and verify its published SHA-256 checksum before installation.
The architecture mapping supports amd64, arm64, armv7, and loong64; stop on any
download or checksum failure rather than installing an unverified binary:

```bash
(
  set -euo pipefail
  ORAS_VERSION=1.4.0
  ARCH="$(uname -m | sed -e 's/x86_64/amd64/' -e 's/aarch64/arm64/' \
    -e 's/armv7l/armv7/' -e 's/loongarch64/loong64/')"
  case "$ARCH" in amd64|arm64|armv7|loong64) ;; *)
    echo "Unsupported ORAS architecture: $(uname -m)" >&2; exit 1 ;;
  esac
  ARCHIVE="oras_${ORAS_VERSION}_linux_${ARCH}.tar.gz"
  CHECKSUMS="oras_${ORAS_VERSION}_checksums.txt"
  RELEASE="https://github.com/oras-project/oras/releases/download/v${ORAS_VERSION}"
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  cd "$WORK"
  curl -fLO "$RELEASE/$ARCHIVE"
  curl -fLO "$RELEASE/$CHECKSUMS"
  sha256sum --ignore-missing -c "$CHECKSUMS"
  mkdir oras-install
  tar -xzf "$ARCHIVE" -C oras-install
  sudo install -o root -g root -m 0755 oras-install/oras /usr/local/bin/oras
)
oras version
```

Confirm that `oras version` reports 1.4.0 or newer and that `command -v oras`
resolves to the installed binary. For macOS, Windows, package-manager options,
and optional GPG/provenance verification, use the official
[ORAS installation guide](https://oras.land/docs/installation) and
[binary-verification guide](https://oras.land/docs/how_to_guides/verifying_binaries).
`oras version` is only a local client check; it does not contact a registry or
change the cluster.

Run the shell examples from the NereidOverview repository root. Create the
persistent, non-secret environment only on the first run. Later runs preserve
all edits and resolved identities:

```bash
DEPLOYMENT_ROOT="${DEPLOYMENT_ROOT:-$HOME/.nereidai-deployment}"
umask 077
install -d -m 700 "$DEPLOYMENT_ROOT"
if [[ ! -e "$DEPLOYMENT_ROOT/deployment.env" ]]; then
  {
    printf 'export DEPLOYMENT_ROOT=%q\n' "$DEPLOYMENT_ROOT"
    cat <<'EOF'
export DEPLOY_VALUES_ROOT="$DEPLOYMENT_ROOT/deploy-values"
export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"
export NEREIDIDENTITY_VERSION=0.0.0-dev
export NEREIDSPHERE_VERSION=0.0.0-dev
export NEREIDHORIZON_VERSION=0.0.0-dev
export PRE_VERSION=0.0.0-dev
export NEREIDFORGE_VERSION=0.0.0-dev
export NEREIDLINK_VERSION=0.0.0-dev
export PRE_HANDOFF_DIR="$DEPLOY_VALUES_ROOT/nereidforge"
export PRE_RELEASE_DIR="$DEPLOYMENT_ROOT/pre-nereidforge/$PRE_VERSION"
export PRE_ENV_FILE="$PRE_HANDOFF_DIR/site.env"
export NF_SECRET_DIR="$DEPLOYMENT_ROOT/secrets/nereidforge"
export NF_VALUES_FILE="$PRE_HANDOFF_DIR/values.generated.yaml"
export NF_OPERATOR_VALUES_FILE="$PRE_HANDOFF_DIR/operator-values.yaml"
# Edit and uncomment these two non-secret site values before section 4.2:
# export NFS_SERVER=nfs.example.org
# export NFS_EXPORT=/srv/nfs/nereidai
unset PRE_RESOLVED_VERSION PRE_SOURCE_COMMIT PRE_ROOT NEREIDFORGE_RESOLVED_VERSION
if [[ -s "$PRE_RELEASE_DIR/resolved-version.txt" ]]; then
  export PRE_RESOLVED_VERSION="$(cat "$PRE_RELEASE_DIR/resolved-version.txt")"
  export PRE_SOURCE_COMMIT="$(cat "$PRE_RELEASE_DIR/source-commit.txt")"
  export PRE_ROOT="$PRE_RELEASE_DIR/pre-nereidforge-installer-$PRE_RESOLVED_VERSION"
fi
if [[ -s "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt" ]]; then
  export NEREIDFORGE_RESOLVED_VERSION="$(cat "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt")"
fi
EOF
  } > "$DEPLOYMENT_ROOT/deployment.env"
fi
chmod 600 "$DEPLOYMENT_ROOT/deployment.env"
source scripts/load-deployment-env.sh
install -d -m 700 "$DEPLOY_VALUES_ROOT" "$DEPLOY_LOG_ROOT" \
  "$DEPLOYMENT_ROOT/chart-archives"
for product in nereididentity nereidsphere nereidhorizon nereidforge nereidlink; do
  install -d -m 700 "$DEPLOY_VALUES_ROOT/$product" "$DEPLOY_LOG_ROOT/$product"
done

kubectl config current-context
kubectl get nodes
kubectl get namespaces
helm version
oras version
```

For every later shell, including after a disconnect, restore the selectors,
paths, resolved versions, and helper functions with one command:

```bash
source scripts/load-deployment-env.sh
```

The default root is `$HOME/.nereidai-deployment`. If you deliberately selected a
different root, prefix that command with the same `DEPLOYMENT_ROOT=/path` value.
Do not add credentials to `deployment.env`; the separate private files below
retain them. Rerunning the initialization block never replaces an existing
`deployment.env`, values file, Secret store, or password.

Confirm that the displayed context is the intended empty cluster. Stop if it is
not. Replace every reserved `example.org` name and example NFS endpoint below
with the site's actual values. Do not install into a cluster with existing
Nereid releases without a separate upgrade plan.

### DNS plan

Create DNS records through the site's ingress address before product setup:

| Endpoint | Purpose |
|---|---|
| `sso.example.org` | NereidIdentity issuer and login |
| `nereidsphere.example.org` | Suite portal and ticket verification |
| `nereidhorizon.example.org` | Horizon console and API |
| `nereidforge.example.org` | Forge console, after its development artifact gate |
| `labelstudio.nereidforge.example.org` | Forge Label Studio |
| `cvat.nereidforge.example.org` | Forge CVAT |
| `seaweedfs-s3.nereidforge.example.org` | Public S3 route required for external object downloads |
| `nereidlink.example.org` | Link console/API and SSO callback |

Create the product namespaces now so the public CA certificate can be copied
into them after Phase 0:

```bash
kubectl create namespace nereididentity
kubectl create namespace nereidsphere
kubectl create namespace nereidhorizon
# Forge owns its installation namespaces; create Link only after Forge passes §7.
```

## 3. Secret generation and policy

Initialize the operator-supplied secrets once:

```bash
python3 scripts/generate-suite-secrets.py init \
  --deployment-root "$DEPLOYMENT_ROOT"
```

The tool creates `$DEPLOYMENT_ROOT/secret-store/suite-secrets.json` with mode
`0600` inside a mode-`0700` directory. It prints paths and counts, never secret
values. Running `init` again preserves every existing value. If an existing store
lacks any expected key, `init` fails closed and leaves its bytes unchanged; it
never generates a replacement for a deployed identity. Restore the canonical
store from its encrypted backup. A newer tool version that introduces a field
requires a separate reviewed migration, not automatic gap filling. Keep an
encrypted off-cluster backup of this store. Do not delete it during an upgrade or
attempt to use it as a rotation tool. Current pre-NereidForge is a separate
exception: it neither reads nor
populates this suite store for its PostgreSQL, SeaweedFS, or Dex initialization;
§7.2 uses its private `site.env` and live canonical Kubernetes Secrets instead.

Keep non-secret site configuration in each product's `site-values.yaml`.
**Do not run `render` in this section.** Each product phase below first creates
or instructs you to create that file, gives you an explicit opportunity to edit
it, and only then provides the product-specific `render` command.

The default render output is `values.generated.yaml` beside the input. Use that
generated file for Helm, never the site file. After changing site configuration,
repeat the product phase's render command with `--force`; this replaces only the
generated values and does not rotate secrets. Do not edit the generated file
manually.

The generator shares a credential only where two products must use the exact
same contract, such as Identity's Sphere client secret and Sphere's OIDC client
secret. Database passwords, session/JWT keys, and product ticket secrets remain
independent. It also injects optional direct-OIDC secrets when those modes are
enabled.

The tool does not invent external credentials. Link rendering additionally
requires a mode-`0600` Forge hand-off containing exactly `accessKey` and
`secretKey`; pass it with `--forge-credentials`. The tool rejects extra keys and
angle-bracket placeholders, but only the preceding Forge health gate proves
that the supplied credentials are valid. Malformed YAML errors report the path
and line/column without reproducing source text. Open Horizon administrator
credentials, external database/Valkey credentials, and license material remain
operator-supplied. cert-manager generates the suite CA, Link generates its own
device CA, and Horizon retains its chart-generated session encryption key.

- Keep all values, hand-offs, and the secret store outside Git with mode `0600`.
- Never pass secrets through Helm `--set`, shell tracing, acceptance output, or
  deployment logs.
- Replace non-secret `<...>` placeholders with actual site values. Secret
  placeholders in the examples are overwritten by the generator; Forge's
  credential hand-off must contain real values, not placeholders.

## 4. Phase 0 — shared prerequisites

### 4.1 cert-manager and internal CA

Install the pinned upstream chart, wait for readiness, and create the suite CA:

```bash
helm repo add jetstack https://charts.jetstack.io --force-update
helm repo update jetstack
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.15.3 --set installCRDs=true --wait --timeout 5m
kubectl apply -f deploy/prereqs/manifests/00-internal-ca.yaml
kubectl wait --for=condition=Ready clusterissuer internal-ca --timeout=120s
```

Export only the CA public certificate and copy it into the namespaces that
verify suite TLS. Do not copy the CA private key into product namespaces:

```bash
kubectl -n cert-manager get secret nereid-internal-ca-tls \
  -o jsonpath='{.data.ca\.crt}' | base64 -d \
  > "$DEPLOYMENT_ROOT/nereid-internal-ca.crt"
for ns in nereididentity nereidsphere nereidhorizon; do
  kubectl -n "$ns" create secret generic nereid-internal-ca-tls \
    --from-file=ca.crt="$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
    --dry-run=client -o yaml | kubectl apply -f -
done
```

### 4.2 NFS CSI StorageClass

Prepare the NFS export and node NFS client support first. Edit `deployment.env`
to reuse the exact `NFS_SERVER` and `NFS_EXPORT` values recorded in
[`cluster-bootstrap.md` §3.4](cluster-bootstrap.md#34-nfs-service-and-clients),
then run `source scripts/load-deployment-env.sh`. The checks below fail closed
if either persistent value is still unset:

```bash
: "${NFS_SERVER:?Set NFS_SERVER to the actual NFS host}"
: "${NFS_EXPORT:?Set NFS_EXPORT to the actual exported path}"
helm upgrade --install nfs-csi deploy/prereqs/charts/nfs-csi \
  --namespace kube-system \
  --set-string "nfs.nfs.server=${NFS_SERVER}" \
  --set-string "nfs.nfs.share=${NFS_EXPORT}"
kubectl get storageclass nfs-csi \
  -o jsonpath='{.parameters.server}{"\n"}{.parameters.share}{"\n"}'
kubectl -n kube-system rollout status deploy/csi-nfs-controller --timeout=180s
```

Confirm that the printed server and share exactly match the real NFS export
before creating any PVC. For the bootstrap example, the share is
`/srv/nfs/nereidai`, not `/export/nereidai`.

Create and delete a small test PVC before product installation; record dynamic
provisioning, mounting, and deletion evidence. Keep node-local `local-path`
storage for the bundled PostgreSQL and NATS data directories described below.

### 4.3 Hardware plugins

Install only plugins matching the prepared node hardware, following
[`deploy/prereqs/device-plugins/README.md`](../../deploy/prereqs/device-plugins/README.md):

```bash
# Select only the applicable manifest sequence.
kubectl apply -f deploy/prereqs/device-plugins/nvidia-gpu-plugin.yaml
kubectl apply -f deploy/prereqs/device-plugins/amd-gpu-plugin.yaml
# Intel: nfd.yaml, node-feature-rules.yaml, intel-gpu-plugin.yaml,
# then optionally intel-npu-plugin.yaml.
```

Confirm the expected extended resources appear in node capacity before Forge.
Do not apply hardware manifests for absent hardware merely to complete a list.

### 4.4 CloudNativePG CRDs for Identity

Identity's locked dependency uses the CloudNativePG operator chart `0.29.0`.
Install its cluster-wide CRDs once, without installing a second operator:

```bash
cnpg_output=""
if cnpg_output="$(kubectl get crd clusters.postgresql.cnpg.io -o name 2>&1)"; then
  :
elif [[ "${cnpg_output%%$'\n'*}" == "Error from server (NotFound):"* ]]; then
  helm pull cloudnative-pg --repo https://cloudnative-pg.io/charts \
    --version 0.29.0 --destination "$DEPLOYMENT_ROOT/chart-archives"
  tar -xOzf "$DEPLOYMENT_ROOT/chart-archives/cloudnative-pg-0.29.0.tgz" \
    cloudnative-pg/templates/crds/crds.yaml | sed '1d;$d' \
    | kubectl apply --server-side --force-conflicts -f -
else
  printf 'Could not query the CloudNativePG CRD; refusing to mutate it\n' >&2
  exit 1
fi
kubectl get crd clusters.postgresql.cnpg.io
```

Only an explicit NotFound response permits CRD installation. RBAC, network, and
API failures stop this phase without pulling or applying the chart.

## 5. Phase 1 — NereidIdentity

Initialize the example values from the same verified OCI package, then edit the
copy before installation:

```bash
install -d -m 700 "$DEPLOY_VALUES_ROOT/nereididentity"
NEREIDIDENTITY_CHART="$(pull_nereid_chart nereididentity "$NEREIDIDENTITY_VERSION")"
test -s "$NEREIDIDENTITY_CHART"
test -s "$DEPLOY_VALUES_ROOT/nereididentity/site-values.yaml" || \
  tar -xOzf "$NEREIDIDENTITY_CHART" \
    nereididentity/values-k3s-example.yaml \
    > "$DEPLOY_VALUES_ROOT/nereididentity/site-values.yaml"
chmod 600 "$DEPLOY_VALUES_ROOT/nereididentity/site-values.yaml"
```

Stop here and edit `site-values.yaml` before rendering or installing. Do not
copy the next command until you have saved the site-specific changes.

The generator supplies these required values with unique strong secrets:

- `postgresql.bootstrap.password`;
- `identity.admin.password`;
- `identity.adminClient.secret`;
- `identity.clients.nereidsphere.secret`;
- `identity.clients.nereidhorizon.secret`;
- `identity.clients.nereidforge.secret`;
- `identity.clients.nereidlink.secret`; and
- `identity.suiteAdmin.password`.

Keep `identity.seedUsers=false`. Set the SSO Ingress host and every product
redirect/web origin to the planned `example.org` replacements. Set the
`identity.suiteAdmin` identity fields deliberately. The explicit generated
password is used only when the suite-admin user is first created; preserve the
secret store so later renders do not replace it with a different value.

After saving the edited site values, inject the persistent secrets:

```bash
test -s "$DEPLOY_VALUES_ROOT/nereididentity/site-values.yaml"
python3 scripts/generate-suite-secrets.py render \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --product nereididentity \
  --input "$DEPLOY_VALUES_ROOT/nereididentity/site-values.yaml"
```

Install and verify:

```bash
helm upgrade --install nereididentity "$NEREIDIDENTITY_CHART" \
  --namespace nereididentity --create-namespace --skip-crds --timeout 10m \
  --values "$DEPLOY_VALUES_ROOT/nereididentity/values.generated.yaml"
kubectl -n nereididentity get clusters.postgresql.cnpg.io
kubectl -n nereididentity get pods
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://sso.example.org/auth/realms/nereidai/.well-known/openid-configuration \
  > "$DEPLOY_LOG_ROOT/nereididentity/openid-configuration.json"
```

Stop until the CNPG cluster, Keycloak, and bootstrap hook are healthy and the
issuer document returns successfully. Do not continue after a failed Helm hook.
Once all pods are Ready, run `record_nereid_images nereididentity` and archive
its output with the chart-pull and chart-metadata logs.

## 6. Phase 2 — NereidSphere and NereidHorizon

### 6.1 NereidSphere

For a single-replica Lab/POC, create
`$DEPLOY_VALUES_ROOT/nereidsphere/site-values.yaml` with the following structure.
Replace all domains. The generator supplies every secret, including a
`config.session.secretKey` of exactly 32 ASCII bytes.

```yaml
replicaCount: 1
valkey:
  enabled: false
tickets:
  replayStore: memory
ingress:
  enabled: true
  className: traefik
  annotations:
    cert-manager.io/cluster-issuer: internal-ca
  hosts:
    - host: nereidsphere.example.org
      paths:
        - path: /
          pathType: Prefix
  tls:
    - hosts: [nereidsphere.example.org]
      secretName: nereidsphere-tls
config:
  server:
    baseUrl: https://nereidsphere.example.org
  oidc:
    issuer: https://sso.example.org/auth/realms/nereidai
    clientId: nereidsphere
    clientSecret: "<identity.clients.nereidsphere.secret>"
    adminClientId: nereidsphere-admin
    adminClientSecret: "<identity.adminClient.secret>"
    caBundleSecret: nereid-internal-ca-tls
  session:
    secretKey: "<exactly-32-byte-session-key>"
  products:
    - id: forge
      name: NereidForge
      description: Model factory
      url: https://nereidforge.example.org
      mode: ns
      oidcClientId: nereidforge
      ssoSecret: "<new-independent-forge-ticket-secret>"
      tenantsPath: /v1/integration/ns/tenants
    - id: horizon
      name: NereidHorizon
      description: Edge distribution
      url: https://nereidhorizon.example.org
      mode: ns
      oidcClientId: nereidhorizon
      ssoSecret: "<new-independent-horizon-ticket-secret>"
      tenantsPath: /v1/integration/ns/tenants
    - id: link
      name: NereidLink
      description: IoT platform
      url: https://nereidlink.example.org
      mode: ns
      oidcClientId: nereidlink
      ssoSecret: "<new-independent-link-ticket-secret>"
      tenantsPath: /v1/integration/ns/tenants
```

For a multi-replica deployment, retain the built-in Valkey topology, set
`valkey.enabled=true`, and use the Valkey ticket replay store. The generator
supplies `valkey.auth.password` unless an existing Secret is selected. Do not
use the in-memory replay store with multiple replicas.

```bash
chmod 600 "$DEPLOY_VALUES_ROOT/nereidsphere/site-values.yaml"
NEREIDSPHERE_CHART="$(pull_nereid_chart nereidsphere "$NEREIDSPHERE_VERSION")"
test -s "$NEREIDSPHERE_CHART"
python3 scripts/generate-suite-secrets.py render \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --product nereidsphere \
  --input "$DEPLOY_VALUES_ROOT/nereidsphere/site-values.yaml"
helm upgrade --install nereidsphere "$NEREIDSPHERE_CHART" \
  --namespace nereidsphere --create-namespace --timeout 5m \
  --values "$DEPLOY_VALUES_ROOT/nereidsphere/values.generated.yaml"
kubectl -n nereidsphere rollout status deploy/nereidsphere --timeout=240s
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidsphere.example.org/readyz
record_nereid_images nereidsphere
```

Stop until readiness succeeds and an unauthenticated browser visit reaches the
Identity login flow.

### 6.2 NereidHorizon

Create `$DEPLOY_VALUES_ROOT/nereidhorizon/site-values.yaml`. The chart generates a
64-hex-character session encryption key on first installation and retains it in
the release Secret on upgrades; archive that Secret securely.

```yaml
global:
  imagePullSecrets: []
postgres:
  auth:
    password: "<new-strong-horizon-postgres-password>"
  persistence:
    storageClass: local-path
ns:
  enabled: true
  baseUrl: https://nereidsphere.example.org
  productId: horizon
  clientSecret: "<Sphere config.products[id=horizon].ssoSecret>"
  callbackPath: /auth/ns-callback
  caBundleSecret: nereid-internal-ca-tls
  caBundleKey: ca.crt
ingress:
  enabled: true
  className: traefik
  host: nereidhorizon.example.org
  tls:
    enabled: true
    secretName: nereidhorizon-tls
```

Install both application tiers and verify the API:

```bash
chmod 600 "$DEPLOY_VALUES_ROOT/nereidhorizon/site-values.yaml"
NEREIDHORIZON_CHART="$(pull_nereid_chart nereidhorizon "$NEREIDHORIZON_VERSION")"
test -s "$NEREIDHORIZON_CHART"
python3 scripts/generate-suite-secrets.py render \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --product nereidhorizon \
  --input "$DEPLOY_VALUES_ROOT/nereidhorizon/site-values.yaml"
helm upgrade --install nereidhorizon "$NEREIDHORIZON_CHART" \
  --namespace nereidhorizon --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidhorizon/values.generated.yaml"
kubectl -n nereidhorizon rollout status deploy/nereidhorizon-backend --timeout=240s
kubectl -n nereidhorizon rollout status deploy/nereidhorizon-frontend --timeout=240s
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidhorizon.example.org/api/health
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidhorizon.example.org/api/setup-status
record_nereid_images nereidhorizon
```

Open the Horizon console and complete the first-run Setup form manually. Create
a new platform administrator and supply an Open Horizon Exchange base URL plus
a hub-level super-account. Do not reuse the platform administrator password as
the Exchange credential. Setup validates Exchange reachability and privileges.

Configure Forge and ESS endpoints only after their actual endpoints exist.
Pattern/agreement delivery and ESS model delivery are separate later steps.

**Current empty-cluster stop point:** accept Identity, Sphere, and Horizon,
record their health, and stop here until §7.2's independent pre gate is
satisfied. The separate NF gate applies only after pre acceptance.

## 7. Phase 3 — pre-NereidForge and NereidForge

Forge has two independently versioned parts. `pre-nereidforge` owns the five
supporting-service charts and the ordered Kubeflow Kustomize installation.
NereidForge owns only its 23 application images and three OCI charts. Do not use
the retired monolithic Forge installer, a Kubeflow umbrella chart, or an NF
source-tree installation.

### 7.1 Development artifact gate

Use the `PRE_VERSION=0.0.0-dev` and `NEREIDFORGE_VERSION=0.0.0-dev` selections
already loaded from `deployment.env`. The two resolved versions are independent
and need not match. Record each resolved `0.0.0-dev-<short-sha>` identity, OCI
digest, and source commit.

**Section 7.2 requires only the pre publication gate**:
`pre-nereidforge-publish-dev` must have anonymously verified the ORAS pre
installer and all five supporting charts, each with matching floating and
immutable identities. A missing or partial NF image publication does not block
a pre-only installation.

**Sections 7.3–7.5 additionally require the complete selected-profile NF gate**.
With `image_profile=full`, `publish-dev` must anonymously verify all 23 NF-owned
images. With `image_profile=cpu-xpu`, it must verify 18 core/CPU/Intel-XPU
images; only the five AMD/NVIDIA trainer images are excluded, and every Intel
XPU image remains required. Both profiles require exactly three NF OCI charts,
including manifest and chart pull/render checks. Record the selected profile and
its run summary with the resolved version, digests, and source commit. Stop
after §7.2 acceptance while that evidence is absent, and do not start Link.

There is no NF source-installer asset or formal-release prerequisite. The
third NF chart, `nereidforge-tenant-check`, is verification-only and is not an
application release. The commands below remain manual operator steps.

### 7.2 Install and accept pre-NereidForge

Resolve and pull the ORAS pre installer anonymously, verify its digest, file
set, and checksum, then extract it outside Git. The helper persists the resolved
non-secret version and source commit so a later shell can restore `PRE_ROOT`:

```bash
PRE_ROOT="$(pull_pre_nereidforge_installer "$PRE_VERSION")"
test -s "$PRE_ROOT/install-lock.json"
if [[ ! -e "$PRE_ENV_FILE" ]]; then
  install -m 600 /dev/null "$PRE_ENV_FILE"
fi
```

Edit `site.env` before installing. It is a private pre input file, not a Helm
values handoff. Set these non-secret site and NF handoff inputs:

```bash
BASE_DOMAIN=example.org
STORAGE_CLASS=nfs-csi
POD_CIDR=10.42.0.0/16
SERVICE_CIDR=10.43.0.0/16
DEX_STATIC_EMAIL=admin@nereidforge.local
FRONTEND_HOST=nereidforge.example.org
SSO_MODE=ns
SSO_NS_BASE_URL=https://nereidsphere.example.org
```

The current pre installer uses `admin@nereidforge.local` in its Dex config,
Kubeflow Profile, and RBAC. Do not substitute an email based on `BASE_DOMAIN`
unless the installer first makes that identity configurable everywhere.

Current pre-NereidForge does not read or populate `secret-store/suite-secrets.json`.
Its PostgreSQL, SeaweedFS, and Dex inputs live in `site.env`; back up that file
and the live Kubernetes Secrets separately. The suite store later supplies only
the applicable Identity Forge client and Sphere Forge ticket secret.

#### First-installation secrets

Run the following block only for a **genuine first installation**, before any
PostgreSQL or SeaweedFS credential Secret exists. For an existing or partially
installed environment, skip to the recovery procedure below instead of
generating replacements. The helper preserves existing non-empty site values,
appends only missing assignments, and never prints a credential. On Ubuntu,
`sudo apt-get install apache2-utils` provides `htpasswd`:

```bash
(
  set -euo pipefail
  source scripts/load-deployment-env.sh
  command -v htpasswd >/dev/null
  umask 077
  install -d -m 700 "$(dirname "$PRE_ENV_FILE")"
  if [[ ! -e "$PRE_ENV_FILE" ]]; then
    install -m 600 /dev/null "$PRE_ENV_FILE"
  fi
  chmod 600 "$PRE_ENV_FILE"

  unset PG_ADMIN_PASSWORD SEAWEEDFS_S3_ACCESS_KEY SEAWEEDFS_S3_SECRET_KEY
  unset DEX_STATIC_PASSWORD DEX_STATIC_PASSWORD_HASH
  set -a
  source "$PRE_ENV_FILE"
  set +a

  # A surviving hash without its plaintext is not a recoverable Dex identity.
  if [[ -n "${DEX_STATIC_PASSWORD_HASH:-}" && -z "${DEX_STATIC_PASSWORD:-}" ]]; then
    echo "Restore DEX_STATIC_PASSWORD from backup; do not generate a different one" >&2
    exit 1
  fi

  record_secret() {
    local name="$1" value="$2"
    if [[ -z "${!name:-}" ]]; then
      printf '%s=%q\n' "$name" "$value" >> "$PRE_ENV_FILE"
      printf -v "$name" '%s' "$value"
    fi
  }
  record_secret PG_ADMIN_PASSWORD "$(openssl rand -hex 32)"
  record_secret SEAWEEDFS_S3_ACCESS_KEY "$(openssl rand -hex 16)"
  record_secret SEAWEEDFS_S3_SECRET_KEY "$(openssl rand -hex 40)"
  record_secret DEX_STATIC_PASSWORD "$(openssl rand -hex 24)"
  if [[ -z "${DEX_STATIC_PASSWORD_HASH:-}" ]]; then
    DEX_HASH="$(
      printf '%s\n' "$DEX_STATIC_PASSWORD" |
        htpasswd -inBC 12 "" | tr -d ':\n'
    )"
    record_secret DEX_STATIC_PASSWORD_HASH "$DEX_HASH"
    unset DEX_HASH
  fi
  printf 'Private pre inputs retained in %s\n' "$PRE_ENV_FILE"
)
```

Do not leave `PG_ADMIN_PASSWORD` empty: older verified pre installers do not
write their random fallback back to `site.env`. Keep an encrypted off-cluster
backup. In particular, Link must later reuse the exact first-installation
SeaweedFS identity rather than generating another one.

#### Existing PostgreSQL Secret recovery

On a rerun, `nereidforge/pg-${PG_CLUSTER_NAME}-credentials` is the retained
identity. Never overwrite its data merely because `site.env` is missing or
contains a different password. The following read-only check prints only match
states. It sources the same defaults as the installer and sends the retained
password to the database probe over stdin:

```bash
(
  set -euo pipefail
  source scripts/load-deployment-env.sh
  source "$PRE_ROOT/scripts/lib/config.sh"
  SECRET_NAME="pg-${PG_CLUSTER_NAME}-credentials"
  SECRET_PASSWORD="$(
    kubectl get secret "$SECRET_NAME" -n nereidforge \
      -o jsonpath='{.data.password}' | base64 -d
  )"
  SECRET_USERNAME="$(
    kubectl get secret "$SECRET_NAME" -n nereidforge \
      -o jsonpath='{.data.username}' | base64 -d
  )"
  [[ "$SECRET_USERNAME" == "$PG_DB_USER" ]] ||
    { echo 'SECRET_USERNAME=MISMATCH'; exit 1; }
  if [[ "$SECRET_PASSWORD" == "${PG_ADMIN_PASSWORD:-}" ]]; then
    echo 'SITE_VS_SECRET=MATCH'
  else
    echo 'SITE_VS_SECRET=MISMATCH'
  fi
  PG_POD="$(
    kubectl get pods -n nereidforge \
      -l "cnpg.io/cluster=$PG_CLUSTER_NAME,cnpg.io/instanceRole=primary" \
      -o jsonpath='{.items[0].metadata.name}'
  )"
  test -n "$PG_POD"
  if printf '%s\n' "$SECRET_PASSWORD" |
    kubectl exec -i -n nereidforge "$PG_POD" -c postgres -- \
      sh -c '
        IFS= read -r PGPASSWORD
        export PGPASSWORD
        psql -h 127.0.0.1 -U "$1" -d "$2" -tAc "SELECT 1" >/dev/null
      ' sh "$PG_DB_USER" "$PG_DB_NAME"
  then
    echo 'DB_VS_SECRET=MATCH'
  else
    echo 'DB_VS_SECRET=MISMATCH'
  fi
)
```

If `DB_VS_SECRET=MATCH` but `SITE_VS_SECRET=MISMATCH`, restore only the site
assignment from the retained Secret. Do not change the Secret or database. This
snippet also removes duplicate later password assignments and prints no value:

```bash
(
  set -euo pipefail
  source scripts/load-deployment-env.sh
  source "$PRE_ROOT/scripts/lib/config.sh"
  RETAINED_PG_PASSWORD="$(
    kubectl get secret "pg-${PG_CLUSTER_NAME}-credentials" -n nereidforge \
      -o jsonpath='{.data.password}' | base64 -d
  )"
  export RETAINED_PG_PASSWORD PRE_ENV_FILE
  python3 - <<'PY'
import os
from pathlib import Path
import re
import shlex

path = Path(os.environ["PRE_ENV_FILE"])
assignment = "PG_ADMIN_PASSWORD=" + shlex.quote(os.environ["RETAINED_PG_PASSWORD"])
pattern = re.compile(r"^\s*(?:export\s+)?PG_ADMIN_PASSWORD\s*=")
lines = path.read_text(encoding="utf-8").splitlines()
output = []
for line in lines:
    if pattern.match(line):
        if assignment not in output:
            output.append(assignment)
    else:
        output.append(line)
if assignment not in output:
    output.append(assignment)
temporary = path.with_name(f".{path.name}.recovery")
temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
print(f"Retained PostgreSQL site input in {path}; value not displayed")
PY
)
```

Stop for operator-assisted recovery if `DB_VS_SECRET=MISMATCH`; changing a CNPG
bootstrap Secret after initialization does not safely prove or rotate the
existing database role password. The SeaweedFS canonical Secret
`nereidforge/seaweedfs-s3-credentials` is likewise authoritative on reruns.
Never generate replacement S3 site values when it exists; retain or recover the
same identity for the later Link handoff.

#### Fail-closed preflight

Register the locked CloudNativePG dependency repository before the stages:

```bash
helm repo add cloudnative-pg https://cloudnative-pg.io/charts --force-update
helm repo update cloudnative-pg
```

Then run this local/read-only preflight as one fail-closed block. PostgreSQL
site input is required only when its canonical Secret is absent. S3 site input
is required only when the canonical Secret and both legacy config sources are
absent. Query errors other than `NotFound` stop the check. The Dex check proves
that the retained plaintext and bcrypt hash form a pair without printing either
one:

```bash
(
  set -euo pipefail
  source scripts/load-deployment-env.sh
  command -v helm kubectl oras python3 openssl base64 sha256sum tar
  command -v htpasswd
  command -v envsubst
  source "$PRE_ROOT/scripts/lib/config.sh"
  missing=()
  for name in \
    BASE_DOMAIN STORAGE_CLASS POD_CIDR SERVICE_CIDR \
    PG_CLUSTER_NAME PG_DB_NAME PG_DB_USER \
    DEX_STATIC_EMAIL DEX_STATIC_PASSWORD DEX_STATIC_PASSWORD_HASH \
    SSO_MODE SSO_NS_BASE_URL
  do
    [[ -n "${!name:-}" ]] || missing+=("$name")
  done

  resource_exists() {
    local kind="$1" name="$2" output
    if output="$(kubectl get "$kind" "$name" -n nereidforge -o name 2>&1)"; then
      return 0
    fi
    if [[ "${output%%$'\n'*}" == "Error from server (NotFound):"* ]]; then
      return 1
    fi
    printf 'Could not query %s/%s in nereidforge\n' "$kind" "$name" >&2
    return 2
  }

  if resource_exists secret "pg-${PG_CLUSTER_NAME}-credentials"; then
    :
  else
    status=$?
    (( status == 1 )) || exit "$status"
    missing+=(PG_ADMIN_PASSWORD)
  fi

  S3_CREDENTIALS_EXIST=false
  for resource in \
    secret:seaweedfs-s3-credentials \
    secret:seaweedfs-s3-config \
    configmap:seaweedfs-s3-config
  do
    IFS=: read -r kind name <<< "$resource"
    if resource_exists "$kind" "$name"; then
      S3_CREDENTIALS_EXIST=true
      break
    else
      status=$?
      (( status == 1 )) || exit "$status"
    fi
  done
  if [[ "$S3_CREDENTIALS_EXIST" == false ]]; then
    for name in SEAWEEDFS_S3_ACCESS_KEY SEAWEEDFS_S3_SECRET_KEY; do
      [[ -n "${!name:-}" ]] || missing+=("$name")
    done
  fi
  if (( ${#missing[@]} )); then
    printf 'Missing required pre input: %s\n' "${missing[@]}" >&2
    exit 1
  fi
  test "$DEX_STATIC_EMAIL" = admin@nereidforge.local
  test "$SSO_MODE" = ns
  kubectl get storageclass "$STORAGE_CLASS" >/dev/null

  PY=python3
  if [[ -x "$PRE_ROOT/.venv/bin/python" ]] &&
     "$PRE_ROOT/.venv/bin/python" -c 'import boto3' >/dev/null 2>&1; then
    PY="$PRE_ROOT/.venv/bin/python"
  fi
  "$PY" -c 'import boto3'

  DEX_HASH_FILE="$(mktemp)"
  chmod 600 "$DEX_HASH_FILE"
  trap 'rm -f "$DEX_HASH_FILE"' EXIT
  printf 'dex:%s\n' "$DEX_STATIC_PASSWORD_HASH" > "$DEX_HASH_FILE"
  if printf '%s\n' "$DEX_STATIC_PASSWORD" |
    htpasswd -iv "$DEX_HASH_FILE" dex >/dev/null 2>&1
  then
    echo 'Password for user dex correct'
  else
    echo 'DEX_CREDENTIALS=MISMATCH' >&2
    exit 1
  fi
  echo 'PRE_PREFLIGHT=PASS'
)
```

If `boto3` is missing, install it into the interpreter selected above, or use
`python3 -m venv "$PRE_ROOT/.venv"` and
`"$PRE_ROOT/.venv/bin/pip" install boto3`. Do not bypass a failed preflight.

Run every stage manually and stop on the first failure:

```bash
bash "$PRE_ROOT/scripts/10_infra.sh"
bash "$PRE_ROOT/scripts/30_install-kubeflow.sh"
bash "$PRE_ROOT/scripts/60_verify/infra-check.sh"
bash "$PRE_ROOT/scripts/60_verify/kubeflow-check.sh"
bash "$PRE_ROOT/scripts/60_verify/mr-check.sh"
```

The Kubeflow stage must finish with all 18 targets applied. It renders each
target once and makes up to four apply attempts, 15 seconds apart by default,
because CRDs and admission webhooks can reject resources while their controllers
are still starting. If those bounded retries are exhausted, do not delete
namespaces or rerun infrastructure. Inspect the
Knative, Kubeflow, KServe, JobSet, and LWS Pods; wait for
`deployment/kserve-controller-manager` in `kserve` and confirm that
`kserve-webhook-server-service` has an endpoint before rerunning only
`30_install-kubeflow.sh`. Stop for diagnosis on image-pull, crash-loop, or
persistent webhook failures:

```bash
kubectl get pods -n knative-serving
kubectl get pods -n kubeflow
kubectl get pods -n kserve
kubectl get pods -A | grep -E 'jobset|leaderworkerset|lws-system'
kubectl wait --for=condition=Available \
  deployment/kserve-controller-manager -n kserve --timeout=600s
kubectl get endpoints -n kserve kserve-webhook-server-service
```

The successful Kubeflow stage automatically finalizes the NF handoff. It:

- retains only the Label Studio/CVAT token keys in
  `nereidforge/nereidforge-service-credentials` without replacing NF-owned keys;
- copies only the public `ca.crt` to `nereidforge/nereid-internal-ca`; and
- writes deterministic, non-secret
  `$PRE_HANDOFF_DIR/values.generated.yaml` using schema
  `pre-nereidforge-handoff/v1`.

Do not put credentials in that generated file. It contains endpoints, Secret
names and keys, ingress paths, `namespace.create=false`, and post-install
settings shared by the two NF application releases (the consolidated
`nereidforge` release and `ml-backend`).

### 7.3 Retain NF-owned Secrets and create a non-secret overlay

The Sphere installation in §6.1 must contain the `forge` product, its
`https://nereidforge.example.org` URL, and its independent `ssoSecret`. Keep the
Identity `nereidforge` client for the optional direct-OIDC configuration; the
default generated handoff uses Sphere `ns` mode.

Create a private directory for first-time NF secrets. Preserve all three files
on upgrades. The JWT and admin password may be generated once as shown; copy
the SSO secret from the existing Sphere `forge` product secret store instead of
inventing a different value:

```bash
install -d -m 700 "$NF_SECRET_DIR"
test -s "$NF_SECRET_DIR/jwt" || openssl rand -hex 32 | tr -d '\n' > "$NF_SECRET_DIR/jwt"
test -s "$NF_SECRET_DIR/admin-password" || \
  openssl rand -hex 24 | tr -d '\n' > "$NF_SECRET_DIR/admin-password"
# Copy the exact Sphere config.products[id=forge].ssoSecret into this file.
# Create the placeholder only on the first run; never truncate a retained value.
if [[ ! -e "$NF_SECRET_DIR/sso-client" ]]; then
  install -m 600 /dev/null "$NF_SECRET_DIR/sso-client"
fi
chmod 600 "$NF_SECRET_DIR/jwt" "$NF_SECRET_DIR/admin-password"
test -s "$NF_SECRET_DIR/sso-client"
```

Merge the NF-owned keys through a private patch file. This adds no credential
to Helm values, command arguments, or logs, and leaves the two pre-owned token
keys intact:

```bash
python3 - "$NF_SECRET_DIR" <<'PY'
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
patch = {
    "stringData": {
        "NEREIDFORGE_AUTH_JWT_SECRET": (root / "jwt").read_text().strip(),
        "NEREIDFORGE_SSO_NS_CLIENT_SECRET": (root / "sso-client").read_text().strip(),
    }
}
destination = root / "runtime-secret-patch.json"
destination.write_text(json.dumps(patch) + "\n")
destination.chmod(0o600)
PY
kubectl -n nereidforge patch secret nereidforge-service-credentials \
  --type=merge --patch-file="$NF_SECRET_DIR/runtime-secret-patch.json"
```

Create the administrator Secret only after an explicit server `NotFound`
response; every other query failure stops before mutation. The consolidated
release's post-install Helm hook uses its `password` key to seed `admin` when
no such user exists; it does not rotate an existing password by default:

```bash
nereidforge_admin_output=""
if nereidforge_admin_output="$(kubectl -n nereidforge \
  get secret nereidforge-admin-credentials -o name 2>&1)"; then
  :
elif [[ "${nereidforge_admin_output%%$'\n'*}" == "Error from server (NotFound):"* ]]; then
  kubectl -n nereidforge create secret generic nereidforge-admin-credentials \
    --from-file=password="$NF_SECRET_DIR/admin-password" \
    --dry-run=client -o yaml | kubectl apply -f -
else
  printf 'Could not query secret/nereidforge-admin-credentials; refusing to mutate it\n' >&2
  exit 1
fi
if [[ ! -e "$PRE_HANDOFF_DIR/operator-values.yaml" ]]; then
  printf '{}\n' > "$PRE_HANDOFF_DIR/operator-values.yaml"
fi
chmod 600 "$PRE_HANDOFF_DIR/operator-values.yaml"
```

Add only non-secret site overrides to `operator-values.yaml`; `{}` selects the
generated defaults. Never use its `secrets`, `stringData`, `password`,
`jwt_secret`, `client_secret`, `lsToken`, or token/access-key fields. Never pass
credentials with Helm `--set`. The read-only preflight rejects these literal
credential fields and requires all existing Secrets and keys, including the
CNPG, SeaweedFS, KFP artifact, CA, runtime, and administrator contracts.

### 7.4 Run preflight and install the two NF application releases

Run this as one fail-closed block. It stops at the first failed pull, metadata
check, preflight, or Helm command instead of continuing with an empty chart
path. The resolved version is persisted for the later acceptance stage.

```bash
(
  set -euo pipefail
  NEREIDFORGE_APP_CHART="$(pull_nereid_chart nereidforge "$NEREIDFORGE_VERSION")"
  NEREIDFORGE_ML_BACKEND_CHART="$(pull_nereid_chart nereidforge-ml-backend "$NEREIDFORGE_VERSION")"
  test -s "$NEREIDFORGE_APP_CHART"
  test -s "$NEREIDFORGE_ML_BACKEND_CHART"
  NEREIDFORGE_RESOLVED_VERSION="$(helm show chart "$NEREIDFORGE_APP_CHART" | awk '/^version:/ {print $2; exit}')"
  for chart in "$NEREIDFORGE_ML_BACKEND_CHART"; do
    test "$(helm show chart "$chart" | awk '/^version:/ {print $2; exit}')" = \
      "$NEREIDFORGE_RESOLVED_VERSION"
  done
  printf '%s\n' "$NEREIDFORGE_RESOLVED_VERSION" \
    > "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt"
  chmod 600 "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt"
  bash "$PRE_ROOT/scripts/40_check-nf-handoff.sh"

  helm upgrade --install nereidforge "$NEREIDFORGE_APP_CHART" \
    --namespace nereidforge \
    -f "$NF_VALUES_FILE" -f "$NF_OPERATOR_VALUES_FILE" \
    --wait --timeout 10m
  helm upgrade --install ml-backend "$NEREIDFORGE_ML_BACKEND_CHART" \
    --namespace nereidforge \
    -f "$NF_VALUES_FILE" -f "$NF_OPERATOR_VALUES_FILE" \
    --wait --timeout 10m
)
```

An anonymous `denied` response means that the selected chart is not publicly
available at that version. Do not authenticate to bypass the anonymous gate or
continue with an empty archive variable; return to §7.1 and complete the NF
artifact gate instead.

Do not add `--create-namespace`; pre owns that namespace and the handoff
prevents Helm from adopting it (`namespace.create: false` in the generated
values). The single consolidated `nereidforge` release runs the API, worker,
and embedded SPA frontend Deployments while preserving every live object name
through the chart's nameOverride pins. Its post-install/post-upgrade hooks
seed the administrator without implicit password rotation and synchronize the
existing KFP pipeline definitions. A failed hook fails the Helm operation. Do
not continue to the ML backend after the consolidated release fails.

### 7.5 Final NF acceptance and Link handoff

Confirm rollouts and archive the running image evidence:

```bash
NEREIDFORGE_RESOLVED_VERSION="$(cat "$PRE_RELEASE_DIR/nf-resolved-version-$NEREIDFORGE_VERSION.txt")"
kubectl -n nereidforge rollout status deploy/nereidforge-api --timeout=5m
kubectl -n nereidforge rollout status deploy/nereidforge-worker --timeout=5m
kubectl -n nereidforge rollout status deploy/nereidforge-frontend --timeout=5m
kubectl -n nereidforge rollout status deploy/ml-backend --timeout=5m
kubectl -n nereidforge get jobs,pods
record_nereid_images nereidforge
```

Run the NF fail-closed verifier from a verification-only checkout of the exact
resolved development commit. This checkout supplies test tooling only; it is not
an installation package and installs nothing:

```bash
NEREIDFORGE_SHORT_SHA="${NEREIDFORGE_RESOLVED_VERSION#0.0.0-dev-}"
[[ "$NEREIDFORGE_SHORT_SHA" =~ ^[0-9a-f]{7}$ ]]
NF_VERIFIER_DIR="$DEPLOYMENT_ROOT/verifiers/nereidforge-$NEREIDFORGE_RESOLVED_VERSION"
install -d -m 700 "$DEPLOYMENT_ROOT/verifiers"
prepare_nf_verifier_checkout() {
  local checkout="$1"
  if ! git -C "$checkout" cat-file -e "${NEREIDFORGE_SHORT_SHA}^{commit}"; then
    git -C "$checkout" fetch --filter=blob:none origin || return 1
  fi
  git -C "$checkout" cat-file -e "${NEREIDFORGE_SHORT_SHA}^{commit}" || return 1
  git -C "$checkout" checkout --detach "$NEREIDFORGE_SHORT_SHA" || return 1
  [[ "$(git -C "$checkout" rev-parse HEAD)" == "$NEREIDFORGE_SHORT_SHA"* ]] || return 1
}
if [[ ! -d "$NF_VERIFIER_DIR/.git" ]]; then
  [[ ! -e "$NF_VERIFIER_DIR" ]] || {
    printf 'Verifier path exists but is not a Git checkout\n' >&2
    exit 1
  }
  NF_VERIFIER_TMP="$(mktemp -d "$DEPLOYMENT_ROOT/verifiers/.nereidforge-$NEREIDFORGE_RESOLVED_VERSION.XXXXXX")"
  if ! git clone --filter=blob:none --no-checkout \
    https://github.com/NereidAI/NereidForge.git "$NF_VERIFIER_TMP"; then
    rm -rf "$NF_VERIFIER_TMP"
    exit 1
  fi
  if ! prepare_nf_verifier_checkout "$NF_VERIFIER_TMP"; then
    rm -rf "$NF_VERIFIER_TMP"
    exit 1
  fi
  mv "$NF_VERIFIER_TMP" "$NF_VERIFIER_DIR"
else
  prepare_nf_verifier_checkout "$NF_VERIFIER_DIR"
fi
NF_ENV_FILE="$PRE_ENV_FILE" NF_HANDOFF_DIR="$PRE_HANDOFF_DIR" \
  bash "$NF_VERIFIER_DIR/scripts/60_verify/nf-check.sh"
```

A fresh clone is checked out and verified in a temporary sibling before its
atomic move. If an interrupted clone already left `.git` without the commit,
`fetch` repairs the same checkout; resume never treats `.git` alone as proof of a
usable verifier.

The verifier reads the administrator password from the existing Secret when no
legacy local credential file is present and never prints the login response.
Complete browser acceptance as well: NS login and logout, real administrator
login, a KFP training run, Label Studio/CVAT integration, and a notebook route
including WebSockets. Require all four SeaweedFS buckets and their authenticated
list access to remain healthy. Any failed health, login, SSO, pipeline,
integration, frontend, notebook, or object-store check blocks Link.

Forge must leave these Link inputs in the operator's private handoff; the
non-secret `values.generated.yaml` deliberately does not contain the credential
values:

- reachable SeaweedFS S3 endpoint;
- a public S3 endpoint if browsers or edge hosts need presigned downloads;
- bucket access key and secret key from the retained
  `nereidforge/seaweedfs-s3-credentials` Secret; and
- the CA/TLS settings for both endpoints.

## 8. NereidLink (after Forge)

**Stop unless Forge and its final verification are complete.** Link requires
Forge SeaweedFS from its first installation. There is no supported temporary
object store. Reuse the exact Forge credentials; do not create a different
credential pair for Link.

The verified Link development chart is listed in §1. Create
`$DEPLOY_VALUES_ROOT/nereidlink/site-values.yaml` from this structure only after
the Forge gate:

```yaml
imagePullSecrets: []
registryCredentials:
  create: false
replicaCount: 1
auth:
  jwtSecret: "<new-strong-link-jwt-secret>"
ingress:
  enabled: true
  className: traefik
  host: nereidlink.example.org
  tls:
    enabled: true
    secretName: nereidlink-tls
postgresql:
  mode: bundled
  password: "<new-strong-link-postgres-password>"
  storageClass: local-path
nats:
  enabled: true
  replicas: 1
  jetstreamReplicas: 1
  storageClass: local-path
persistence:
  storageClass: nfs-csi
blob:
  endpoint: seaweedfs-s3.nereidforge.svc.cluster.local:8333
  publicEndpoint: seaweedfs-s3.nereidforge.example.org:443
  bucket: nereidlink
  accessKey: "<Forge SEAWEEDFS_S3_ACCESS_KEY>"
  secretKey: "<Forge SEAWEEDFS_S3_SECRET_KEY>"
  secure: false
  publicSecure: true
sso:
  enabled: true
  nsBaseURL: https://nereidsphere.example.org
  clientID: link
  ssoSecret: "<Sphere config.products[id=link].ssoSecret>"
  callbackPath: /auth/ns-callback
  caBundleSecret: nereid-internal-ca-tls
  caBundleKey: ca.crt
pki:
  serverHosts:
    - localhost
    - nereidlink
    - nereidlink.nereidlink.svc.cluster.local
    - nereidlink.example.org
    - "<edge-facing-node-dns-name>"
```

Create the Link namespace and copy only the CA public certificate into it:

```bash
kubectl create namespace nereidlink
kubectl -n nereidlink create secret generic nereid-internal-ca-tls \
  --from-file=ca.crt="$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  --dry-run=client -o yaml | kubectl apply -f -
chmod 600 "$DEPLOY_VALUES_ROOT/nereidlink/site-values.yaml"
if [[ ! -e "$DEPLOY_VALUES_ROOT/nereidforge/seaweedfs-credentials.yaml" ]]; then
  install -m 600 /dev/null "$DEPLOY_VALUES_ROOT/nereidforge/seaweedfs-credentials.yaml"
fi
```

Edit `seaweedfs-credentials.yaml` to contain exactly the credentials handed off
by the healthy Forge installation, then render Link's private values:

```yaml
accessKey: "<exact-Forge-SEAWEEDFS_S3_ACCESS_KEY>"
secretKey: "<exact-Forge-SEAWEEDFS_S3_SECRET_KEY>"
```

Install and verify both tiers:

```bash
NEREIDLINK_CHART="$(pull_nereid_chart nereidlink "$NEREIDLINK_VERSION")"
test -s "$NEREIDLINK_CHART"
python3 scripts/generate-suite-secrets.py render \
  --deployment-root "$DEPLOYMENT_ROOT" \
  --product nereidlink \
  --input "$DEPLOY_VALUES_ROOT/nereidlink/site-values.yaml" \
  --forge-credentials "$DEPLOY_VALUES_ROOT/nereidforge/seaweedfs-credentials.yaml"
helm upgrade --install nereidlink "$NEREIDLINK_CHART" \
  --namespace nereidlink --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidlink/values.generated.yaml"
kubectl -n nereidlink rollout status deploy/nereidlink --timeout=240s
kubectl -n nereidlink rollout status deploy/nereidlink-frontend --timeout=240s
kubectl -n nereidlink get svc nereidlink-mqtt
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidlink.example.org/healthz
record_nereid_images nereidlink
kubectl -n nereidlink exec deployment/nereidlink -c nereidlink -- \
  cat /var/lib/nereidlink/pki/ca.pem \
  > "$DEPLOYMENT_ROOT/nereidlink-device-ca.pem"
openssl x509 -in "$DEPLOYMENT_ROOT/nereidlink-device-ca.pem" \
  -noout -subject -fingerprint -sha256
```

A fresh chart creates `admin@nereidai.local` with an empty password; nobody can
log in until the one-time bootstrap API sets it. Complete that bootstrap over a
loopback-only Pod forward (the product's `post-deploy.sh` uses the same flow).
The quick installer runs this automatically inside the `link` stage; the manual
equivalent is:

```bash
LINK_STATE_DIR="$DEPLOY_VALUES_ROOT/nereidlink"
LINK_CREDENTIALS="$LINK_STATE_DIR/admin-credentials.env"
APP_POD="$(kubectl -n nereidlink get pod -l app.kubernetes.io/component=app \
  -o jsonpath='{.items[0].metadata.name}')"
kubectl -n nereidlink port-forward "pod/$APP_POD" 127.0.0.1:18081:8080 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT
sleep 3
STATUS="$(curl --noproxy '*' -fsS http://127.0.0.1:18081/v1/auth/bootstrap-status)"
if grep -q '"required":true' <<<"$STATUS"; then
  ADMIN_PASSWORD="$(openssl rand -hex 24)"
  printf '{"password":"%s"}' "$ADMIN_PASSWORD" \
    | curl --noproxy '*' -fsS -X POST \
      http://127.0.0.1:18081/v1/auth/bootstrap \
      -H 'Content-Type: application/json' --data-binary @- \
      -o /tmp/nereidlink-bootstrap-response.json
  grep -q '"access_token"' /tmp/nereidlink-bootstrap-response.json
  rm -f /tmp/nereidlink-bootstrap-response.json
  umask 077
  printf '%s\n' \
    '# NereidLink built-in platform admin; save securely and never commit.' \
    'LINK_ADMIN_EMAIL=admin@nereidai.local' \
    "LINK_ADMIN_PASSWORD=$ADMIN_PASSWORD" > "$LINK_CREDENTIALS"
  chmod 600 "$LINK_CREDENTIALS"
else
  echo 'Link admin is already initialized; existing password left unchanged'
fi
```

Never print the password, bootstrap response, or token to the console. If
bootstrap was already completed through the web UI or another tooling path, do
not POST again: the API fails with "bootstrap already complete" and the existing
password is retained. Re-running the status call must report
`{"required":false}`.

Link generates its own device CA and signs the MQTT server leaf with it. The
exported `ca.pem` is the public CA certificate for edge MQTT verification; it is
not the suite Ingress CA. Never export `ca-key.pem` or `server-key.pem`. Preserve
the Link data PVC and back it up under the site's encryption policy so the CA
and issued credentials survive restarts.

The migration init container must complete in the non-terminating Pods owned by
the ReplicaSet that matches the current `nereidlink` Deployment template. An old
ReplicaSet's success or failure is not current-revision evidence. The application
must create the `nereidlink` bucket through Forge SeaweedFS. Check logs and
storage before accepting the rollout. The one-time administrator bootstrap must
also be complete: the quick installer performs it through the loopback
bootstrap API and retains the generated password in
`$DEPLOY_VALUES_ROOT/nereidlink/admin-credentials.env` (mode `0600`); an
administrator initialized out of band is never reset. Import any site license
through the product's supported runtime interface; no signing private key is
part of chart installation.

## 9. Open Horizon edge delivery

Perform these operations separately for each edge host after Link is healthy.
Use the operator-generated Open Horizon registration inputs and the verified
Nereid service definitions; this guide does not invent public edge-package
coordinates.

1. **Register the edge host.** Install the site-approved Open Horizon agent,
   register the node with the Exchange organization, and confirm `hzn node
   list` reports the intended node and organization.
2. **Deliver the Pattern.** Publish/select the NereidEdge/NereidInference
   Pattern in Horizon, wait for an agreement, and confirm `hzn agreement list`
   plus the edge service health. An agreement alone is not application
   acceptance.
3. **Connect NereidEdge to Link.** Create one gateway credential pair per edge
   host in Link. Set `NEREID_BROKER_URL` to
   `tls://nereidlink.example.org:31884`, mount the exported Link public device CA
   read-only on the edge, and set `NEREID_ROOT_CA_FILE` to its in-container path.
   Configure the unique edge ID, credentials, and device map through the edge
   service configuration. Keep credentials out of Patterns, shell history, and
   committed files; do not substitute the suite Ingress CA or disable TLS
   verification.
4. **Verify the data path.** Check the NereidEdge health endpoint and confirm
   the same edge ID reports heartbeats and telemetry in Link. Verify the MQTT
   server certificate against Link's public device CA and check its SANs.
5. **Deliver a model through ESS.** As a separate Horizon operation, publish an
   immutable model object with its expected SHA-256, deliver it to the selected
   edge destination, and verify the received object and inference status.
   Record the ESS object ID and digest; a Pattern agreement does not prove ESS
   delivery.

## 10. Final acceptance and troubleshooting

Complete [`reference/fresh-cluster-checklist.md`](reference/fresh-cluster-checklist.md)
and archive non-secret evidence under `$DEPLOY_LOG_ROOT`. Minimum product gates:

- every selected selector, resolved chart OCI digest/internal version, running
  image ID/digest, and source commit is recorded;
- Identity discovery, Sphere login, and product SSO redirects succeed;
- every product certificate chains to the intended CA;
- Link uses Forge SeaweedFS and its bucket survives an application restart;
- MQTT connect, heartbeat, and telemetry succeed with one edge-specific
  credential pair; and
- the ESS object ID, SHA-256, edge receipt, and inference result are recorded
  independently of the service agreement.

| Symptom | Check |
|---|---|
| OCI pull fails anonymously | Confirm the exact version is listed in §1 or has separately passed public verification; check outbound GHCR access. |
| Chart rendering names a missing required value | Complete the named field in the site's values file; do not substitute a shared placeholder. |
| `ImagePullBackOff` | Compare the Pod's image/tag with the selected chart `appVersion` and verify public registry/DNS access from that node. |
| TLS verification fails | Confirm the Ingress host/SAN and copy the current CA public certificate into the consumer namespace. |
| PVC remains pending | Check the selected StorageClass, NFS export, node NFS client, and whether the workload requires node-local block storage. |
| Link cannot create its bucket | Stop and verify Forge SeaweedFS health, endpoint, exact credentials, bucket policy, and TLS mode. |
| Edge agreement exists but no telemetry | Check NereidEdge-to-Link credentials, edge ID, device map, MQTT reachability, and service logs. |
| Edge service is healthy but the model is absent | Perform the independent ESS delivery and verify its object ID and SHA-256. |
