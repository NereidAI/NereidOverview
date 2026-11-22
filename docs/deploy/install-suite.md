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

## 1. Verified versions and installation scope

These immutable Lab/POC versions passed anonymous chart pull/render and
image-manifest verification on 2026-11-22:

| Product | OCI chart | Version | Source commit |
|---|---|---|---|
| Identity | `oci://ghcr.io/nereidai/charts/nereididentity` | `0.0.0-dev-7c2797d` | `7c2797ddec13d6fcef72a535069738d247173e61` |
| Sphere | `oci://ghcr.io/nereidai/charts/nereidsphere` | `0.0.0-dev-90379cb` | `90379cbec953c51b5807cf60f53c17fb736da1ff` |
| Horizon | `oci://ghcr.io/nereidai/charts/nereidhorizon` | `0.0.0-dev-05aaf97` | `05aaf97bb5d3119f00ccc2ea90d3e8bb86dda49d` |
| Link | `oci://ghcr.io/nereidai/charts/nereidlink` | `0.0.0-dev-6da29bd` | `6da29bdca204510bd4b8560c503ead28bc231c0b` |

Each chart's `version` and `appVersion` are identical, and its suite images use
that same version. Third-party images retain their public upstream coordinates
and pinned versions.

The floating `0.0.0-dev` version is not reproducible. For a formal deployment,
replace every version below with the same selected bare-SemVer release only
after that exact chart and all its images have passed anonymous verification.
Do not infer a release version from these examples.

Set the verified Lab/POC selections explicitly:

```bash
export NEREIDIDENTITY_VERSION=0.0.0-dev-7c2797d
export NEREIDSPHERE_VERSION=0.0.0-dev-90379cb
export NEREIDHORIZON_VERSION=0.0.0-dev-05aaf97
export NEREIDLINK_VERSION=0.0.0-dev-6da29bd
```

Record these versions, their source commits, the selected kubecontext, and the
installation date in the deployment hand-off.

## 2. Operator environment

Required tools on the operator host: Helm with OCI support, `kubectl`, `tar`,
`curl`, and `openssl`. The operator host and every cluster node must reach all
public artifact registries referenced by the charts. DNS and TLS must be valid
for every product endpoint.

Run the shell examples from the NereidOverview repository root. Keep all site
state outside Git:

```bash
export DEPLOYMENT_ROOT="${DEPLOYMENT_ROOT:-$HOME/.nereidai-deployment}"
export DEPLOY_VALUES_ROOT="$DEPLOYMENT_ROOT/deploy-values"
export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"
install -d -m 700 "$DEPLOYMENT_ROOT" "$DEPLOY_VALUES_ROOT" "$DEPLOY_LOG_ROOT" \
  "$DEPLOYMENT_ROOT/chart-archives"
for product in nereididentity nereidsphere nereidhorizon nereidforge nereidlink; do
  install -d -m 700 "$DEPLOY_VALUES_ROOT/$product" "$DEPLOY_LOG_ROOT/$product"
done

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

## 3. Secret policy

- Generate every password, OIDC client secret, session key, and object-store
  credential independently, for example with `openssl rand -hex 32`. Where a
  chart generates a value once, retain and archive that generated value instead.
- Use a separate secret for each field; never reuse a product client secret as
  a session key or database password.
- Keep values files at mode `0600` under `$DEPLOY_VALUES_ROOT` and store an
  encrypted backup in the operator's password vault.
- Do not print secrets in acceptance output or shell tracing.
- Values shown as `<...>` are instructions to supply a value, not literals to
  install.

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

Prepare the NFS export and node NFS client support first. Replace both values
with the site's actual NFS server and export:

```bash
helm upgrade --install nfs-csi deploy/prereqs/charts/nfs-csi \
  --namespace kube-system \
  --set nfs.nfs.server=nfs.example.org \
  --set nfs.nfs.share=/export/nereidai
kubectl get storageclass nfs-csi
kubectl -n kube-system rollout status deploy/csi-nfs-controller --timeout=180s
```

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
helm pull oci://ghcr.io/nereidai/charts/nereididentity \
  --version "$NEREIDIDENTITY_VERSION" \
  --destination "$DEPLOYMENT_ROOT/chart-archives"
test -s "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml" || \
  tar -xOzf "$DEPLOYMENT_ROOT/chart-archives/nereididentity-${NEREIDIDENTITY_VERSION}.tgz" \
    nereididentity/values-k3s-example.yaml \
    > "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml"
chmod 600 "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml"
```

Supply these required values with unique strong secrets:

- `postgresql.bootstrap.password`;
- `identity.admin.password`;
- `identity.adminClient.secret`;
- `identity.clients.nereidsphere.secret`;
- `identity.clients.nereidhorizon.secret`;
- `identity.clients.nereidforge.secret`; and
- `identity.clients.nereidlink.secret`.

Keep `identity.seedUsers=false`. Set the SSO Ingress host and every product
redirect/web origin to the planned `example.org` replacements. Set the
`identity.suiteAdmin` identity fields deliberately. Either supply a unique
strong `identity.suiteAdmin.password`, or leave only that password empty so the
chart generates it once on first installation. The generated value is retained
in Secret `nereididentity-realm`, key `suite-admin-password`; retrieve and store
it securely after installation. An explicit password is used only when the
suite-admin user is first created.

Install and verify:

```bash
helm upgrade --install nereididentity \
  oci://ghcr.io/nereidai/charts/nereididentity \
  --version "$NEREIDIDENTITY_VERSION" \
  --namespace nereididentity --create-namespace --skip-crds --timeout 10m \
  --values "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml"
kubectl -n nereididentity get clusters.postgresql.cnpg.io
kubectl -n nereididentity get pods
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://sso.example.org/auth/realms/nereidai/.well-known/openid-configuration \
  > "$DEPLOY_LOG_ROOT/nereididentity/openid-configuration.json"
```

Stop until the CNPG cluster, Keycloak, and bootstrap hook are healthy and the
issuer document returns successfully. Do not continue after a failed Helm hook.

## 6. Phase 2 — NereidSphere and NereidHorizon

### 6.1 NereidSphere

For a single-replica Lab/POC, create
`$DEPLOY_VALUES_ROOT/nereidsphere/values.yaml` with the following structure.
Replace all domains and secrets. `config.session.secretKey` must be exactly 32
bytes; `openssl rand -hex 16` produces 32 ASCII characters.

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
`valkey.enabled=true`, supply `valkey.auth.password`, and use the Valkey ticket
replay store. Do not use the in-memory replay store with multiple replicas.

```bash
chmod 600 "$DEPLOY_VALUES_ROOT/nereidsphere/values.yaml"
helm upgrade --install nereidsphere \
  oci://ghcr.io/nereidai/charts/nereidsphere \
  --version "$NEREIDSPHERE_VERSION" \
  --namespace nereidsphere --create-namespace --timeout 5m \
  --values "$DEPLOY_VALUES_ROOT/nereidsphere/values.yaml"
kubectl -n nereidsphere rollout status deploy/nereidsphere --timeout=240s
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidsphere.example.org/readyz
```

Stop until readiness succeeds and an unauthenticated browser visit reaches the
Identity login flow.

### 6.2 NereidHorizon

Create `$DEPLOY_VALUES_ROOT/nereidhorizon/values.yaml`. The chart generates a
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
chmod 600 "$DEPLOY_VALUES_ROOT/nereidhorizon/values.yaml"
helm upgrade --install nereidhorizon \
  oci://ghcr.io/nereidai/charts/nereidhorizon \
  --version "$NEREIDHORIZON_VERSION" \
  --namespace nereidhorizon --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidhorizon/values.yaml"
kubectl -n nereidhorizon rollout status deploy/nereidhorizon-backend --timeout=240s
kubectl -n nereidhorizon rollout status deploy/nereidhorizon-frontend --timeout=240s
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidhorizon.example.org/api/health
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidhorizon.example.org/api/setup-status
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

The verified Link Lab/POC chart is listed in §1. Create
`$DEPLOY_VALUES_ROOT/nereidlink/values.yaml` from this structure only after the
Forge gate:

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
chmod 600 "$DEPLOY_VALUES_ROOT/nereidlink/values.yaml"
```

Install and verify both tiers:

```bash
helm upgrade --install nereidlink \
  oci://ghcr.io/nereidai/charts/nereidlink \
  --version "$NEREIDLINK_VERSION" \
  --namespace nereidlink --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidlink/values.yaml"
kubectl -n nereidlink rollout status deploy/nereidlink --timeout=240s
kubectl -n nereidlink rollout status deploy/nereidlink-frontend --timeout=240s
kubectl -n nereidlink get svc nereidlink-mqtt
curl --fail --cacert "$DEPLOYMENT_ROOT/nereid-internal-ca.crt" \
  https://nereidlink.example.org/healthz
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

- every selected chart/image version and source commit is recorded;
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
