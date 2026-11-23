# NereidAI Public Suite Installation Guide (k3s + Rancher)

Start with a ready, empty, Rancher-managed k3s cluster from
[`cluster-bootstrap.md`](cluster-bootstrap.md). Every phase is executed manually
by the operator and accepted before the next phase starts.

Products install directly from versioned public GHCR OCI charts. No product
source checkout is needed. NereidOverview supplies the shared prerequisite
manifests and this runbook; product repositories remain the chart sources of
truth.

> **Current stop point:** Forge has no complete public installation channel.
> On an empty cluster, complete §§4–6 (shared prerequisites, Identity, Sphere,
> and Horizon) and stop at §7. Do not install Link until a complete Forge release has passed the gate
> and supplied healthy SeaweedFS credentials.

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

Set the normal development selections once; no per-commit version edit is
needed:

```bash
export NEREIDIDENTITY_VERSION=0.0.0-dev
export NEREIDSPHERE_VERSION=0.0.0-dev
export NEREIDHORIZON_VERSION=0.0.0-dev
export NEREIDLINK_VERSION=0.0.0-dev
```

Record each resolved chart OCI digest and internal version, the running image
IDs/digests, selected kubecontext, and installation date in the deployment
hand-off. For deliberate reproduction, replace a floating selector with its
resolved `0.0.0-dev-<short-sha>` version only after anonymously verifying that
snapshot. For a formal deployment, use a selected bare-SemVer release only
after that exact chart and all its images have passed anonymous verification.
Do not infer a release version from these examples.

## 2. Operator environment

Required tools on the operator host: Helm with OCI support, `kubectl`, `tar`,
`curl`, `openssl`, and Python 3 with PyYAML. The operator host and every cluster
node must reach all public artifact registries referenced by the charts. DNS and
TLS must be valid for every product endpoint.

Run the shell examples from the NereidOverview repository root. Keep all site
state outside Git:

```bash
export DEPLOYMENT_ROOT="${DEPLOYMENT_ROOT:-$HOME/.nereidai-deployment}"
export DEPLOY_VALUES_ROOT="$DEPLOYMENT_ROOT/deploy-values"
export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"
umask 077
install -d -m 700 "$DEPLOYMENT_ROOT" "$DEPLOY_VALUES_ROOT" "$DEPLOY_LOG_ROOT" \
  "$DEPLOYMENT_ROOT/chart-archives"
for product in nereididentity nereidsphere nereidhorizon nereidforge nereidlink; do
  install -d -m 700 "$DEPLOY_VALUES_ROOT/$product" "$DEPLOY_LOG_ROOT/$product"
done

# Resolve a floating selector once. The log records its OCI digest and internal
# version; only the archive path is returned for use by values and installation.
pull_nereid_chart() (
  set -euo pipefail
  local product="$1" selector="$2" pull_dir archive
  pull_dir="$(mktemp -d "$DEPLOYMENT_ROOT/chart-archives/${product}.XXXXXX")"
  helm pull "oci://ghcr.io/nereidai/charts/${product}" \
    --version "$selector" --destination "$pull_dir" 2>&1 \
    | tee "$DEPLOY_LOG_ROOT/$product/chart-pull.txt" >&2
  archive="$(find "$pull_dir" -maxdepth 1 -type f -name "${product}-*.tgz" -print -quit)"
  test -s "$archive"
  helm show chart "$archive" | tee "$DEPLOY_LOG_ROOT/$product/chart-metadata.txt" >&2
  printf '%s\n' "$archive"
)

record_nereid_images() (
  set -euo pipefail
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

kubectl config current-context
kubectl get nodes
kubectl get namespaces
helm version
```

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
| `nereidforge.example.org` | Forge console, after its release gate |
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
values. Running `init` again preserves every existing value and only adds fields
introduced by a newer tool version. Keep an encrypted off-cluster backup of this
store. Do not delete it during an upgrade or attempt to use it as a rotation
tool.

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

Prepare the NFS export and node NFS client support first. Reuse the exact
`NFS_SERVER` and `NFS_EXPORT` values recorded in
[`cluster-bootstrap.md` §3.4](cluster-bootstrap.md#34-nfs-service-and-clients).
If this is a new shell, export those actual site values again before running
this block:

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
if ! kubectl get crd clusters.postgresql.cnpg.io >/dev/null 2>&1; then
  helm pull cloudnative-pg --repo https://cloudnative-pg.io/charts \
    --version 0.29.0 --destination "$DEPLOYMENT_ROOT/chart-archives"
  tar -xOzf "$DEPLOYMENT_ROOT/chart-archives/cloudnative-pg-0.29.0.tgz" \
    cloudnative-pg/templates/crds/crds.yaml | sed '1d;$d' \
    | kubectl apply --server-side --force-conflicts -f -
fi
kubectl get crd clusters.postgresql.cnpg.io
```

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
record their health, and stop here until §7's Forge gate can be satisfied.

## 7. Forge availability gate

Do not run a Forge installation from the rolling channel. A complete public
Forge installation requires all of the following for one selected formal
version:

1. successful publication of all 23 suite-owned image jobs;
2. all nine active OCI charts, with independent upstream wrapper metadata
   preserved;
3. anonymous verification of every chart and image;
4. the versioned Forge installer, checksum, image manifest, and chart manifest;
5. anonymous retrieval and extraction verification of that installer; and
6. a documented source commit and formal tag.

Those artifacts do not currently exist as a verified complete set. This guide
therefore provides no Forge package URL or installation command. When the gate
is met, use the selected Forge release's staged infrastructure, Kubeflow,
application, and verification procedure; require its final verification to pass
before creating Link values.

Forge must leave these Link inputs in the operator's private hand-off:

- reachable SeaweedFS S3 endpoint;
- a public S3 endpoint if browsers or edge hosts need presigned downloads;
- bucket access key and secret key; and
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
install -m 600 /dev/null "$DEPLOY_VALUES_ROOT/nereidforge/seaweedfs-credentials.yaml"
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

Link generates its own device CA and signs the MQTT server leaf with it. The
exported `ca.pem` is the public CA certificate for edge MQTT verification; it is
not the suite Ingress CA. Never export `ca-key.pem` or `server-key.pem`. Preserve
the Link data PVC and back it up under the site's encryption policy so the CA
and issued credentials survive restarts.

The migration init container must complete and the application must create the
`nereidlink` bucket through Forge SeaweedFS. Check logs and storage before
accepting the rollout. Complete the one-time administrator bootstrap through
the web UI. Import any site license through the product's supported runtime
interface; no signing private key is part of chart installation.

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
