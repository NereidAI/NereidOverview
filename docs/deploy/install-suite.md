# NereidAI Suite Installation Guide (k3s + Rancher)

> **Prerequisite**: a Rancher-managed k3s cluster built per
> [`cluster-bootstrap.md`](cluster-bootstrap.md). This guide starts from that
> ready, empty cluster.
>
> **Principle**: every layer is installed manually in order with human
> confirmation. Products install from **local sibling chart paths**
> (deploy-standards §15.5), never from a hand-maintained chart fork.
>
> **Scope**: this guide contains the full commands for shared prerequisites and
> the four core products. NereidForge (Kubeflow stack) and the field gateways
> are deployed from their own repositories — this guide gives only the order,
> preflight checks, and pointers (§7).

## Table of contents

1. [Workspace layout](#1-workspace-layout)
2. [Image delivery and registries](#2-image-delivery-and-registries)
3. [Cluster preparation](#3-cluster-preparation)
4. [Phase 0 — shared prerequisites](#4-phase-0--shared-prerequisites)
5. [Prepare product values](#5-prepare-product-values)
6. [Phase 1 — core products](#6-phase-1--core-products)
7. [Phase 1b — Forge, Link and field gateways](#7-phase-1b--forge-link-and-field-gateways)
8. [Phase 2 — end-to-end verification](#8-phase-2--end-to-end-verification)
9. [ChartMuseum (optional, air-gapped only)](#9-chartmuseum-optional-air-gapped-only)
10. [Production deltas](#10-production-deltas)
11. [Troubleshooting](#11-troubleshooting)

## 1. Workspace layout

A **full deployment requires every NereidAI product repository cloned locally**,
side by side with NereidOverview — charts install from local sibling paths, not
from a remote chart repository (deploy-standards §15.5). A single-product deployment needs
only that product's repository.

```text
nereid-workspace/
├── .deployment/
│   ├── deploy-values/   # per-product site inputs, hand-offs, keys, licenses
│   └── deploy-logs/     # per-product deployment and verification logs
├── NereidOverview/      # this guide, prerequisites, helper scripts
├── NereidIdentity/      # identity (Keycloak)
├── NereidSphere/        # portal / SSO / API gateway
├── NereidLink/          # IoT connection platform
├── NereidHorizon/       # edge application distribution
├── NereidForge/         # AI model factory
├── NereidEdge/          # field gateway (compose, not in-cluster)
├── NereidInference/     # edge inference (compose, not in-cluster)
└── …                    # every other NereidAI repository you will deploy
```

The complete repository list is on the [organization page](https://github.com/NereidAI).
All commands below assume this layout and are run from the workspace root
unless stated otherwise.

## 2. Image delivery and registries

This chapter is the operator-facing counterpart of
deploy-standards §15.2/§15.3/§15.8/§15.9. The installation steps below never
change between an online and an air-gapped site; only image delivery differs,
and it is handled entirely at the registry/node layer.

### 2.1 Two image classes and the one hard rule

| Class | Examples | Canonical coordinates | Air-gapped handling |
|---|---|---|---|
| Suite business images | `nereididentity-bootstrap`, `nereidsphere`, `nereidhorizon-*`, `nereidlink`, `nereidedge`, `nereidinference`, `nereidforge-*`, `face-service` | `ghcr.io/nereidai/<image>:<VERSION>` | Mirrored into the `<harbor-host>/nereidai` project; charts and Deployments keep the public coordinate and resolve it via the node mirror |
| Third-party / infrastructure images | cert-manager, CSI sidecars, GPU device plugins, Keycloak, CNPG, Postgres, NATS, Kubeflow/Knative stack | `docker.io`, `quay.io`, `registry.k8s.io`, `nvcr.io`, … | Bulk-mirrored per `images.txt`/product manifests; a small number of charts that cannot express a mirror-only path accept an explicit override in **untracked operator site values** |

The hard rule (deploy-standards §15.3): the internal registry hostname and credentials
exist only in the git-ignored `deploy/scripts/harbor.env` and in untracked
operator site values. No committed chart, manifest, script, or Makefile names
the internal host, and no suite business image is ever rewritten to an
explicit `<harbor-host>` coordinate or an `@sha256` reference. A 2026-10-30
live-node check verified the resulting k3s mirror configuration: a `*`
endpoint at the site registry with no path rewrite, so the GHCR repository
path resolves to the same registry project without duplicating `nereidai`.

### 2.2 How suite images are produced and versioned (summary)

- **Local builds are build-only.** Every product Makefile exposes an image
  target — `image` (NereidIdentity, NereidSphere, NereidLink, NereidHorizon
  with `image-backend`/`image-frontend` splits, NereidInference) or `docker`
  (NereidEdge, face-service) — that loads the image into the local daemon (or
  writes an OCI archive for NereidEdge/NereidInference) with exactly three
  tags and never pushes: bare `VERSION` (e.g. `0.0.1`), `VERSION-<utc-timestamp>`,
  `VERSION-<git-short-sha>`. No `latest` tag and no push target exist anywhere
  (deploy-standards §15.8/§15.9). Regional network acceleration uses a git-ignored
  `local.mk` only (deploy-standards §15.2).
- **Publication is tag-triggered.** Pushing a SemVer-shaped `v*` git tag
  (deploy-standards §15.9; there is no VERSION file) runs the GitHub Actions release
  workflow, which strips the leading `v`, builds the `linux/amd64` +
  `linux/arm64` index (registered single-arch vendor images excepted) and
  publishes the same three bare-SemVer tags to GHCR. Branch CI warms the
  shared buildx cache; the separate default-branch dev workflow publishes
  only the rolling `0.0.0-dev` channel, and pull requests cannot publish.
- **Only the bare `VERSION` tag is deployment-referenced.** The timestamp and
  git-sha tags exist for audit and rollback. An air-gapped mirror therefore
  needs only the `VERSION` tag of each suite image; copying the trace tags is
  optional.

### 2.3 The single registry tool: harbor-sync.sh

All operations that name the internal registry go through
[`deploy/scripts/harbor-sync.sh`](../../deploy/scripts/harbor-sync.sh)
(deploy-standards §15.3). Setup, once per operator machine:

```bash
cd NereidOverview/deploy/scripts
cp harbor.env.example harbor.env       # git-ignored; fill HARBOR_HOST and credentials
chmod 600 harbor.env
./harbor-sync.sh check                 # validates host config and skopeo/crane
DRY_RUN=1 ./harbor-sync.sh mirror ../../deploy/prereqs/images.txt   # preview first
```

| Subcommand | Purpose |
|---|---|
| `check` | Validate `harbor.env`, tooling, and dry-run mode |
| `login` | Authenticate the local skopeo/crane to Harbor |
| `mirror <manifest>` | Bulk-copy public refs into Harbor; the prerequisite manifest is [`deploy/prereqs/images.txt`](../../deploy/prereqs/images.txt) (human counterpart [`images.md`](../../deploy/prereqs/images.md)) |
| `push <image-ref> [rel-target]` | Copy one image. A plain public ref derives its Harbor-relative target; a transport-prefixed source (`docker-daemon:…`, `oci-archive:…`) requires the explicit relative target |
| `node-mirror [--apply]` | Render the k3s `registries.yaml` to stdout, or write `/etc/rancher/k3s/registries.yaml` (mode 600) as root; k3s must be restarted afterward |

### 2.4 Site scenarios

**Scenario A — online (cluster has internet).** Do nothing: charts pull the
public coordinates directly. Install charts from local sibling repository
paths regardless (deploy-standards §15.5).

**Scenario B — air-gapped site with a connected jump host.** The jump host
has internet and can reach both GHCR/upstream registries and the site Harbor:

```bash
# 1. Third-party prerequisite images (cert-manager, CSI, device plugins)
./harbor-sync.sh login
./harbor-sync.sh mirror ../../deploy/prereqs/images.txt

# 2. Suite business images, copied straight from GHCR (plain ref => target derived)
for img in nereididentity-bootstrap nereidsphere nereidhorizon-backend \
           nereidhorizon-frontend nereidlink; do
  ./harbor-sync.sh push ghcr.io/nereidai/${img}:0.0.1
done
# NereidForge additionally: nereidforge-backend, nereidforge-frontend, nf-runtime,
# trainer-*, ml-backend*, prediction-jupyter-base, inference-model-server-* —
# enumerate from its publish-images.yml; field gateway images (nereidedge,
# nereidinference, face-service) follow the same pattern.

# 3. On EVERY cluster node (run as root; included in cluster-bootstrap §5.3)
sudo ./harbor-sync.sh node-mirror --apply
sudo systemctl restart k3s          # or k3s-agent on worker nodes
```

**Scenario C — fully offline build (no jump-host access to GHCR).** Build on
a connected build machine, transfer via the local daemon or an OCI archive,
and push from the transport-prefixed source with an explicit target:

```bash
# On the build machine, inside each product repository (build-only, no push):
make image                                          # or `make docker`; see §2.2
                                                    # three tags in the local daemon
sudo ./harbor-sync.sh push \
  docker-daemon:ghcr.io/nereidai/nereidsphere:0.0.1 \
  nereidai/nereidsphere:0.0.1
# Or move an archive across the gap:
skopeo copy docker-daemon:ghcr.io/nereidai/nereidsphere:0.0.1 \
  oci-archive:/tmp/nereidsphere-0.0.1.tar:nereidsphere
./harbor-sync.sh push oci-archive:/tmp/nereidsphere-0.0.1.tar:nereidsphere \
  nereidai/nereidsphere:0.0.1
```

When the source repositories themselves cannot reach the site, package the
charts with `helm package` from the sibling product checkouts and transfer
the `.tgz` files together with the image bundle (see §9 for a generic
ChartMuseum flow). The on-site source-build tier table (which products are
buildable on site versus delivered prebuilt) is deploy-standards §15.11.

### 2.5 Node mirror, pull secrets, and same-tag rollouts

- The containerd mirror rendered by `node-mirror --apply` is the only
  rewriting mechanism. Apply it on every node before installing products;
  the Rancher-managed equivalent (registries settings in the cluster wizard)
  is described in cluster-bootstrap §5.3.
- With public Harbor projects no pull secret is needed. For private projects
  create `harbor-registry-secret` per namespace and patch the default
  ServiceAccount (commands in §3.2).
- For a same-tag rebuild rollout, set `imagePullPolicy: Always`, wait for
  every Deployment, and compare the ready Pod's resolved `imageID` digest
  against the publication record rather than the tag string.
- Explicit `<harbor-host>` coordinates may appear only in untracked operator
  site values for third-party images whose chart cannot use the mirror path;
  keep generated secrets outside Git.

## 3. Cluster preparation

### 3.1 DNS / hosts

Every product Ingress uses the naming in the
[accounts/DNS reference](reference/accounts-dns-connections.md) (pattern
`nereid<product>.example`; `sso.example` is the sole historical
exception). Until internal DNS exists, add the lab entry node to `/etc/hosts` on
every node and every operator workstation:

```text
192.0.2.10 sso.example nereidsphere.example nereidlink.example \
               nereidhorizon.example nereidforge.example \
               labelstudio.nereidforge.example cvat.nereidforge.example \
               seaweedfs-s3.nereidforge.example
```

### 3.2 Namespaces and registry pull secret

Create the core namespaces (Forge creates its own via its scripts):

```bash
kubectl create namespace nereididentity
kubectl create namespace nereidsphere
kubectl create namespace nereidlink
kubectl create namespace nereidhorizon
```

With the node-level containerd mirror (§2.4 step 3, §2.5) and public Harbor
projects, no pull secret is needed. For private Harbor projects, create one per namespace
and attach it to the default ServiceAccount:

```bash
kubectl -n nereididentity create secret docker-registry harbor-registry-secret \
  --docker-server=<harbor-host> --docker-username=<user> --docker-password='<harbor-password>'
kubectl -n nereididentity patch serviceaccount default -p \
  '{"imagePullSecrets":[{"name":"harbor-registry-secret"}]}'
# repeat for nereidsphere / nereidlink / nereidhorizon
```

No real password is committed anywhere; use a `<harbor-password>` placeholder
and supply the value at install time.

### 3.3 Distribute the internal CA

Products verify each other's TLS using the suite internal CA. After Phase 0
creates `nereid-internal-ca-tls` in `cert-manager`, copy it into each product
namespace:

```bash
for ns in nereididentity nereidsphere nereidlink nereidhorizon; do
  kubectl -n cert-manager get secret nereid-internal-ca-tls -o yaml \
    | sed 's/namespace: cert-manager/namespace: '$ns'/' \
    | kubectl apply -n "$ns" -f -
done
```

(Run this again after §4.1–4.2; it is documented here so the preparation order
is clear.)

## 4. Phase 0 — shared prerequisites

Install strictly in the order below. These components are owned by NereidOverview
under [`deploy/prereqs/`](../../deploy/prereqs/); product charts only preflight-check
them and never install them.

### 4.1 cert-manager v1.15.3

Online, via the upstream jetstack chart with CRDs:

```bash
helm repo add jetstack https://charts.jetstack.io
helm repo update
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version v1.15.3 --set installCRDs=true
```

Air-gapped: mirror the five cert-manager images per
[`images.md`](../../deploy/prereqs/images.md) and install the same chart version
from a packaged tgz (the chart itself is a third-party chart, not vendored in
this repository).

> The live lab cluster was installed via the Rancher Apps catalog; the Helm CLI
> above is the standard path and renders an equivalent release. Do not install
> cert-manager twice — if a release already exists, adopt/upgrade it rather than
> adding a second one.

### 4.2 internal-ca ClusterIssuer

Apply the suite CA manifest (a selfsigned issuer → CA certificate → the
`internal-ca` ClusterIssuer):

```bash
kubectl apply -f deploy/prereqs/manifests/00-internal-ca.yaml
kubectl wait --for=condition=Ready clusterissuer internal-ca --timeout=60s
```

Then run the §3.3 CA-distribution loop. Every product Ingress uses
`cert-manager.io/cluster-issuer: internal-ca`.

### 4.3 nfs-csi StorageClass

Install the wrapper chart from this repository (the upstream subchart tgz is
vendored, so no network fetch is needed):

```bash
helm upgrade --install nfs-csi deploy/prereqs/charts/nfs-csi \
  --namespace kube-system
```

The wrapper renders the suite-contract StorageClass named `nfs-csi` while the
subchart's own StorageClass stays disabled. The committed defaults target the
lab (NFS `192.0.2.10:/data/nereidai`, mirrored images); a production site
overrides with the overlay, never by editing defaults:

```bash
helm upgrade --install nfs-csi deploy/prereqs/charts/nfs-csi \
  --namespace kube-system -f deploy/prereqs/charts/nfs-csi/values-prod.yaml
```

Verify with a test PVC (it lands in an isolated
`<namespace>-<pvc>` subdirectory of the export), then delete it:

```bash
kubectl get storageclass nfs-csi
```

> 2026-10-29 live-cluster note: the existing `nfs-csi` release predates the
> current wrapper values and still renders `registry.k8s.io/...` image specs;
> pulls resolve through the node mirror. It was deliberately not upgraded during
> product deployment because NFS CSI is shared infrastructure. Treat changing
> that live release as a separate storage change with its own verification
> window.

### 4.4 GPU/NPU device plugins (only on GPU hosts)

Install only the plugins matching the node hardware, following
[`deploy/prereqs/device-plugins/README.md`](../../deploy/prereqs/device-plugins/README.md).
Node drivers/container-toolkit are node prerequisites covered there, not part of
this guide:

```bash
kubectl apply -f deploy/prereqs/device-plugins/nvidia-gpu-plugin.yaml   # NVIDIA
kubectl apply -f deploy/prereqs/device-plugins/amd-gpu-plugin.yaml      # AMD
# Intel requires NFD first: intel/nfd.yaml, node-feature-rules.yaml,
# intel-gpu-plugin.yaml, then optionally intel-npu-plugin.yaml
```

Confirm the extended resources are advertised before installing Forge:

```bash
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.status.allocatable}{"\n"}{end}' \
  | grep -E 'nvidia.com/gpu|amd.com/gpu|gpu.intel.com'
```

## 5. Prepare product values

Keep every operator-supplied input outside Git in the workspace-level
`.deployment/deploy-values/<product>/` directory. Deployment and verification
logs belong separately in `.deployment/deploy-logs/<product>/`. Product charts,
placeholder examples, and canonical templates remain in their owning
repositories. From the workspace root, initialize the layout without
truncating existing values:

```bash
export DEPLOYMENT_ROOT="${DEPLOYMENT_ROOT:-$PWD/.deployment}"
export DEPLOY_VALUES_ROOT="$DEPLOYMENT_ROOT/deploy-values"
export DEPLOY_LOG_ROOT="$DEPLOYMENT_ROOT/deploy-logs"
install -d -m 700 "$DEPLOYMENT_ROOT" "$DEPLOY_VALUES_ROOT" "$DEPLOY_LOG_ROOT"
for product in nereididentity nereidsphere nereidlink nereidhorizon nereidforge; do
  install -d -m 700 "$DEPLOY_VALUES_ROOT/$product" "$DEPLOY_LOG_ROOT/$product"
  touch "$DEPLOY_VALUES_ROOT/$product/values.yaml"
done
cp -n NereidIdentity/deploy/helm/nereididentity/values-k3s-example.yaml \
  "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml"
chmod 600 "$DEPLOY_VALUES_ROOT"/nereid*/values.yaml
```

Use the Identity example as a starting point; keep the other files as minimal
overrides populated from the verified snippets in §6 rather than copying chart
defaults.

Rules:

- Every chart fails rendering with a `required` message naming the missing
  field, so a dry template is the fastest way to find an incomplete values file.
  Generate strong values with `openssl rand -hex 32`; the dev password
  `<dev-password>` must never appear here.
- The exact Secret names and runtime wiring are in the
  [accounts/DNS/connections reference](reference/accounts-dns-connections.md)
  (§3). Verified required inputs per chart (`helm template` checked 2026-10-29):

  | Product | Minimum values that must be supplied |
  |---|---|
  | NereidIdentity | Seven strong values: Postgres bootstrap, master admin password, suite-admin/service-account secret, four product client secrets; `identity.seedUsers=false`. With an explicit Harbor registry, override the four image coordinates (§6.1). Install with `--timeout 10m`. |
  | NereidSphere | For a single-replica lab: `valkey.enabled=false` + `tickets.replayStore=memory`; `config.session.secretKey` (exactly 32 bytes); OIDC `clientSecret` + `adminClientSecret`; the three `products[].ssoSecret`; `ingress.enabled=true` **plus** the `cert-manager.io/cluster-issuer` annotation and a `tls` entry (shipped disabled, with no TLS block). Multi-replica deployments keep built-in Valkey and require `valkey.auth.password`. |
  | NereidLink | `blob.endpoint` (an in-cluster FQDN `svc.namespace.svc[:port]`), `blob.accessKey`, `blob.secretKey`; S3 is mandatory and uses Forge SeaweedFS, so complete §7.1 first. Override the bundled TimescaleDB/NATS image coordinates for an explicit registry; enable SSO with the `sso` block. Postgres/NATS are bundled by default. |
  | NereidHorizon | Override the bundled `postgres.image` for an explicit registry; the admin user is created post-install via `POST /api/setup` (§6.4). |

- Set the site domains per §3.1.

> **Image-coordinate rule (deploy-standards §15.2/§15.3):** every product chart and the
> nfs-csi wrapper now carries public coordinates only; the internal Harbor host
> appears in no committed file. The node containerd mirror (§2.4/§2.5) performs
> the host swap, so a missing Harbor tag surfaces as an `ImagePullBackOff`
> instead of being hidden by a chart edit. The only sanctioned explicit
> overrides are untracked site values for third-party dependency images whose
> upstream path the site mirror cannot serve (examples in §6); never edit
> product charts from this repository.

## 6. Phase 1 — core products

Phase-1 order is **NereidIdentity → NereidSphere → NereidHorizon**. Then
complete Forge in §7.1 before installing Link in §7.2: Link's suite SSO points
at Sphere and its permanent blob store is Forge SeaweedFS. Field gateways come
last.

No product repository carries a VERSION file: the signed `v*` git tag is the
single version source and every artifact coordinate uses bare SemVer with the
leading `v` stripped (deploy-standards §15.9); branch builds use the `0.0.0-dev` channel.
Release and namespace names follow each product's convention below.

### 6.1 NereidIdentity

The CNPG and Keycloak chart dependencies are vendored as tgz files in the
product chart's `charts/` directory; do not run `helm dependency update` on an
offline host.
CNPG treats its CRDs as cluster-wide resources. On a clean host, install them
once from the vendored dependency (server dry-run verified 2026-10-29):

```bash
if ! kubectl get crd clusters.postgresql.cnpg.io >/dev/null 2>&1; then
  tar -xOzf NereidIdentity/deploy/helm/nereididentity/charts/cloudnative-pg-0.29.0.tgz \
    cloudnative-pg/templates/crds/crds.yaml \
    | sed '1d;$d' \
    | kubectl apply --server-side --force-conflicts -f -
fi
```

These third-party dependency images are normally resolved through the node
containerd mirror with no value changes (§2.1). Add the following overrides
only to untracked operator site values when a site's Harbor cannot serve the
upstream paths — never commit them, and never override the suite's own
`bootstrap` business image away from its `ghcr.io/nereidai` coordinate. The
Harbor `library/python` project has no `3.12-alpine` tag; use `3.12-slim`
(pull-tested 2026-10-29):

```yaml
postgresql:
  image:
    repository: <harbor-host>/cloudnative-pg/cloudnative-pg
    tag: "1.30.0"
  cluster:
    imageName: <harbor-host>/cloudnative-pg/postgresql:16.4
keycloak:
  image:
    repository: <harbor-host>/keycloak/keycloak
    tag: "26.1"
  dbchecker:
    image:
      repository: <harbor-host>/library/busybox
      tag: "1.36.1"
bootstrap:
  image:
    repository: <harbor-host>/library/python
    tag: "3.12-slim"
```

Install with a long client timeout. The post-install hook waits through database
initialization, Keycloak startup, and realm import; a 120-second client timeout
can leave the Kubernetes resources progressing while the Helm release is marked
failed:

```bash
helm upgrade --install nereididentity NereidIdentity/deploy/helm/nereididentity \
  --namespace nereididentity --create-namespace --skip-crds --timeout 10m \
  --values "$DEPLOY_VALUES_ROOT/nereididentity/values.yaml"
```

> **Known NereidIdentity chart defect on Keycloak 26.1.5 (live check
> 2026-10-29).** A fresh realm import can leave only the `groups` and
> `offline_access` client scopes. The bootstrap hook then fails with
> `built-in 'roles' client scope not found`. This is a cross-repo chart bug; do
> not edit the sibling repository from NereidOverview. The lab workaround is to
> copy the missing built-in scopes from `master`, attach them to the imported
> clients, then rerun the same `helm upgrade`.
>
> ```bash
> cat > /tmp/keycloak-scope-repair.yaml <<'EOF'
> apiVersion: v1
> kind: Pod
> metadata:
>   name: keycloak-scope-repair
>   namespace: nereididentity
> spec:
>   restartPolicy: Never
>   containers:
>     - name: repair
>       image: <harbor-host>/library/python:3.12-slim
>       command: ["sleep", "600"]
>       env:
>         - name: KEYCLOAK_ADMIN
>           valueFrom:
>             secretKeyRef:
>               name: nereididentity-admin
>               key: KEYCLOAK_ADMIN
>         - name: KEYCLOAK_ADMIN_PASSWORD
>           valueFrom:
>             secretKeyRef:
>               name: nereididentity-admin
>               key: KEYCLOAK_ADMIN_PASSWORD
> EOF
> kubectl apply -f /tmp/keycloak-scope-repair.yaml
> kubectl -n nereididentity wait --for=condition=Ready pod/keycloak-scope-repair --timeout=60s
> kubectl -n nereididentity exec -i keycloak-scope-repair -- python3 - <<'PY'
> import json, os, urllib.error, urllib.parse, urllib.request
>
> BASE = "http://nereididentity-keycloak-http:80/auth"
> REALM = "nereidai"
> BUILTIN = ["web-origins", "roles", "profile", "email"]
> ALL_DEFAULT = BUILTIN + ["groups"]
>
> form = urllib.parse.urlencode({
>     "client_id": "admin-cli",
>     "grant_type": "password",
>     "username": os.environ["KEYCLOAK_ADMIN"],
>     "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
> }).encode()
> req = urllib.request.Request(BASE + "/realms/master/protocol/openid-connect/token", form)
> token = json.load(urllib.request.urlopen(req))["access_token"]
> headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
>
> def call(method, path, body=None):
>     data = json.dumps(body).encode() if body is not None else None
>     request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
>     try:
>         with urllib.request.urlopen(request, timeout=20) as response:
>             raw = response.read()
>             return response.status, json.loads(raw) if raw else None
>     except urllib.error.HTTPError as error:
>         if error.code == 409 and method == "PUT":
>             return error.code, None  # already attached
>         raise RuntimeError(f"{method} {path}: {error.code} {error.read().decode()}")
>
> _, master_scopes = call("GET", "/admin/realms/master/client-scopes")
> _, realm_scopes = call("GET", f"/admin/realms/{REALM}/client-scopes")
> existing = {scope["name"] for scope in realm_scopes}
> for name in BUILTIN:
>     if name in existing:
>         continue
>     source = next(scope for scope in master_scopes if scope["name"] == name)
>     _, full = call("GET", "/admin/realms/master/client-scopes/" + source["id"])
>     representation = {
>         key: full.get(key)
>         for key in ("name", "description", "protocol", "attributes")
>     }
>     representation["protocolMappers"] = [
>         {key: mapper.get(key) for key in (
>             "name", "protocol", "protocolMapper", "consentRequired", "config")}
>         for mapper in full.get("protocolMappers", [])
>     ]
>     call("POST", f"/admin/realms/{REALM}/client-scopes", representation)
>
> _, realm_scopes = call("GET", f"/admin/realms/{REALM}/client-scopes")
> scope_ids = {scope["name"]: scope["id"] for scope in realm_scopes}
> for name in ALL_DEFAULT:
>     call("PUT", f"/admin/realms/{REALM}/default-default-client-scopes/{scope_ids[name]}")
>
> _, clients = call("GET", f"/admin/realms/{REALM}/clients")
> product_clients = {
>     "nereidsphere", "nereidsphere-admin", "nereidlink", "nereidhorizon", "nereidforge"
> }
> for client in clients:
>     if client["clientId"] not in product_clients:
>         continue
>     wanted = ["roles"] if client["clientId"] == "nereidsphere-admin" else ALL_DEFAULT
>     _, current = call("GET", f"/admin/realms/{REALM}/clients/{client['id']}/default-client-scopes")
>     current_names = {scope["name"] for scope in current}
>     for name in wanted:
>         if name not in current_names:
>             call("PUT", f"/admin/realms/{REALM}/clients/{client['id']}/default-client-scopes/{scope_ids[name]}")
> PY
> kubectl -n nereididentity delete pod keycloak-scope-repair --force
> ```
>
> Then rerun the `helm upgrade` command above.

Verify:

```bash
kubectl -n nereididentity get clusters.postgresql.cnpg.io
kubectl -n nereididentity get pod -l app.kubernetes.io/name=keycloak
curl -sk https://sso.example/auth/realms/nereidai/.well-known/openid-configuration
```

The external issuer must be `https://sso.example/auth/realms/nereidai`, and
`identity.seedUsers=false` must be set in a central deployment.

### 6.2 NereidSphere

The chart ships Ingress disabled and defaults to a multi-replica Valkey
deployment. For the single-replica lab, use in-memory ticket replay instead of
deploying Valkey:

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
  tls:
    - hosts: [nereidsphere.example]
      secretName: nereidsphere-tls
config:
  session:
    # 32 ASCII bytes; generate with: openssl rand -hex 16
    secretKey: "<32-byte-session-key>"
  oidc:
    clientSecret: "<identity.clients.nereidsphere.secret>"
    adminClientSecret: "<identity.adminClient.secret>"
    caBundleSecret: nereid-internal-ca-tls
```

Also replace every product `ssoSecret` under `config.products`. The Link entry
must match Link's `sso.ssoSecret`; the Horizon entry must later match Horizon's
`ns.clientSecret`.

For multi-replica deployments, keep built-in Valkey and supply
`valkey.auth.password`. The chart's default `<harbor-host>/nereidai/valkey`
tag was absent during the 2026-10-29 Harbor check; override it to the
pull-tested coordinate:

```yaml
valkey:
  image:
    repository: <harbor-host>/valkey/valkey
    tag: "8.0-alpine"
```

Install and verify:

```bash
helm upgrade --install nereidsphere NereidSphere/deploy/helm \
  --namespace nereidsphere --create-namespace --timeout 5m \
  --values "$DEPLOY_VALUES_ROOT/nereidsphere/values.yaml"

kubectl -n nereidsphere rollout status deploy/nereidsphere --timeout=180s
curl -sk https://nereidsphere.example/readyz
echo | openssl s_client -connect nereidsphere.example:443 \
  -servername nereidsphere.example 2>/dev/null | openssl x509 -noout -issuer
```

The issuer must be `CN=nereid-internal-ca`. Enabling Ingress without the
`cert-manager.io/cluster-issuer` annotation and `tls` entry leaves Traefik
serving its default self-signed certificate (observed during the live install).

### 6.3 NereidHorizon

The chart's bundled Postgres value is a single image string (not
`registry`/`repository` split). Online sites keep the public
`postgres:16-alpine` coordinate and rely on the node mirror; set an explicit
override only in untracked site values for a private/mirrored site (lab form):

```yaml
postgres:
  image: <harbor-host>/library/postgres:16-alpine
```

Install and verify:

```bash
helm upgrade --install nereidhorizon NereidHorizon/deploy/helm/nereidhorizon \
  --namespace nereidhorizon --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidhorizon/values.yaml"

kubectl -n nereidhorizon rollout status deploy/nereidhorizon-backend --timeout=240s
curl -sk https://nereidhorizon.example/api/health
curl -sk https://nereidhorizon.example/api/setup-status
```

The chart creates no admin user. After install, complete setup through the
product's documented `POST /api/setup` flow (port-forward if the route is not
yet exposed):

```bash
kubectl -n nereidhorizon port-forward svc/nereidhorizon-backend 3001:3001
# then POST http://localhost:3001/api/setup with the platform admin and Exchange
# super-account credentials (see NereidHorizon's own documentation)
```

Configure Exchange/Forge/ESS endpoints at runtime (the chart deliberately does
not model them). The certificate must also chain to `CN=nereid-internal-ca`.

## 7. Phase 1b — Forge, Link and field gateways

### 7.1 NereidForge (infra + Kubeflow + business layer)

Validated end-to-end on the `nereidai` lab cluster 2026-10-29 (`60_verify.sh`
all green). Forge owns its own namespaces (`nereidforge`, `kubeflow`, `auth`,
`istio-system`, `knative-*`, `kserve`, `kubeflow-system`, `default` MR server);
the suite layer only supplies the prerequisites.

**Preflight (all must hold before starting):**

- `nfs-csi` StorageClass and `internal-ca` ClusterIssuer exist (§4); the NFS
  export `/data/nereidforge_share` is live with `no_root_squash`.
- `infra/third_party/kubeflow-manifests/` is present in the NereidForge checkout
  with pinned upstream references and NF patches. An online source install needs
  GitHub access when stage 30 materializes JobSet/LWS into its temporary render
  tree. An air-gapped install must use NereidForge's generated offline package,
  which reuses those verified upstream assets without storing them in Git.
- The node-level containerd mirror (§2.4/§2.5) must resolve every image the
  charts name — NF no longer has any registry/profile switch or internal-host
  variable; its resolver always renders public refs
  (`ghcr.io/nereidai/<flat>:<VERSION>`, upstream registries unchanged). The
  self-built set includes the flat refs `nereidforge-backend`,
  `nereidforge-frontend`, `ml-backend`, `nf-runtime` and the `trainer-*` /
  `train-*` families (the complete list is NF's
  `.github/workflows/publish-images.yml`); mirror them with `harbor-sync.sh`
  per §2.4. Lab observation 2026-10-29: three upstream refs were missing from
  the mirror and had to be copied first (`skopeo copy --all`):
  `library/alpine:3.23` (KFP pods),
  `knative-releases/knative.dev/serving/cmd/queue:v1.22.0` (the manifests pin
  its digest) and `filebrowser/filebrowser:v2.32.0` (volume viewer).
- Central `.deployment/deploy-values/nereidforge/site.env` sets
  `BASE_DOMAIN`/`FRONTEND_HOST=nereidforge.example`,
  `NFS_SERVER`/`NFS_SHARE`, `PG_INSTANCES=2` (lab), `PG_ADMIN_PASSWORD`,
  `JWT_SECRET`, `DEX_STATIC_PASSWORD`, a unique `SEAWEEDFS_S3_ACCESS_KEY` plus
  strong `SEAWEEDFS_S3_SECRET_KEY`, and the SSO block `SSO_MODE=ns`,
  `SSO_OIDC_*` (client `nereidforge`), `SSO_NS_*` (product `forge`). The
  deployment scripts load this file by default; `NF_ENV_FILE` overrides it.

**Staged install (run from the NereidForge repo root; no registry environment
is needed — every image stays at its public coordinate and the node mirror
from §2.4 does the host swap):**

```bash
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
COMMON_ENV=(HOME=/root KUBECONFIG=$KUBECONFIG KUBECTL=kubectl)

# 1. Infra: CNPG cluster + business DBs, Valkey, SeaweedFS, Label Studio, CVAT,
#    LS/CVAT token bootstrap. The central site.env must supply a unique S3
#    access key and a strong SEAWEEDFS_S3_SECRET_KEY; do not use the dev default.
sudo env "${COMMON_ENV[@]}" bash infra/scripts/10_infra.sh

# 2. Kubeflow: 18 kustomize targets + profile/RBAC/mlpipeline-bucket/tenant wiring.
#    On a fresh cluster the first passes report ordering failures (CRDs/webhooks
#    not ready yet) — that is expected; rerun until every target says Applied.
sudo env "${COMMON_ENV[@]}" bash infra/scripts/30_install-kubeflow.sh
sudo env "${COMMON_ENV[@]}" bash infra/scripts/30_install-kubeflow.sh   # converge

# 3. Business layer (ml-backend, api+worker, frontend, TLS). A fresh admin gets
#    a random 48-hex password; existing passwords stay unchanged unless
#    NF_ADMIN_PASSWORD is explicitly supplied for rotation.
sudo env "${COMMON_ENV[@]}" bash infra/scripts/40_nereidforge.sh nereidforge

# 4. Acceptance: infra / Kubeflow / Model Registry (Dex login included) /
#    business layer (real admin login, SSO ns mode) / tenant provisioning
sudo env "${COMMON_ENV[@]}" bash infra/scripts/60_verify.sh
```

A clean final `30_install-kubeflow.sh` pass applies all 18 targets (`kserve` and
`trainer` via server-side apply). Do not use the interactive `00_deploy-all.sh`
for an unattended install.

**Verify externally:** `https://nereidforge.example/` (200),
`/api/v1/auth/sso/status` returns `{"mode":"ns","enabled":true,...}`,
`https://labelstudio.nereidforge.example/` and
`https://cvat.nereidforge.example/` respond, and every certificate chains to
`CN=nereid-internal-ca`. Kubeflow's Dex login uses the site
`DEX_STATIC_EMAIL / DEX_STATIC_PASSWORD`; the NF local admin is `admin` plus the
strong password in `../.deployment/deploy-values/nereidforge/admin-credentials.env`
(mode 0600). SSO login uses the suite realm admin (reference §3.1). Forge writes
mode-0600 stage logs under `../.deployment/deploy-logs/nereidforge/`; save an
encrypted off-cluster backup of the credential and service-token hand-offs. To
rotate a legacy admin, run stage 40 with
`NF_ADMIN_PASSWORD="$(openssl rand -hex 24)"`, save the updated credential
file, and rerun stage 60.

### 7.2 NereidLink

Link uses Forge SeaweedFS from the first install; there is no temporary or
`emptyDir` backend. Complete §7.1 and reuse the exact
`SEAWEEDFS_S3_ACCESS_KEY` / `SEAWEEDFS_S3_SECRET_KEY` from Forge's central
`site.env`. Link's blob store creates the `nereidlink` bucket idempotently when
it starts.

Set the Link site values. The chart-default bundled images
`<harbor-host>/nereidai/postgres:16-timescale` and
`<harbor-host>/nereidai/nats:2.10-alpine` were absent in Harbor on
2026-10-29; these pull-tested overrides work:

```yaml
postgresql:
  password: "<strong-password>"
  image:
    registry: <harbor-host>
    repository: timescale/timescaledb
    tag: "2.17.2-pg16"
nats:
  image:
    registry: <harbor-host>
    repository: library/nats
    tag: "2.10-alpine"
blob:
  endpoint: "seaweedfs-s3.nereidforge.svc.cluster.local:8333"
  bucket: "nereidlink"
  accessKey: "<Forge SEAWEEDFS_S3_ACCESS_KEY>"
  secretKey: "<Forge SEAWEEDFS_S3_SECRET_KEY>"
  secure: false
sso:
  enabled: true
  nsBaseURL: "https://nereidsphere.example"
  clientID: "link"
  ssoSecret: "<Sphere config.products[id=link].ssoSecret>"
  callbackPath: "/auth/ns-callback"
  caBundleSecret: "nereid-internal-ca-tls"
  caBundleKey: "ca.crt"
```

Install and verify:

```bash
helm upgrade --install nereidlink NereidLink/deploy/kubernetes/helm/nereidlink \
  --namespace nereidlink --create-namespace --timeout 8m \
  --values "$DEPLOY_VALUES_ROOT/nereidlink/values.yaml"

kubectl -n nereidlink rollout status deploy/nereidlink --timeout=240s

# Idempotent first-run hand-off: bootstrap a random 48-hex admin password when
# required, then generate/install a default signed license only when none exists.
# Requires Go and the offline vendor key under deploy-values/nereidlink/license/private/.
NereidLink/deploy/kubernetes/scripts/deploy.sh post-deploy

curl -sk https://nereidlink.example/healthz
kubectl -n nereidlink get svc nereidlink-mqtt   # NodePorts 31883/31884
```

The bundled migration init-container must complete successfully before the app
starts; `Init:Error` can be transient while the last init container exits, but a
repeated failure requires the init-container logs. A successful rollout also
proves authenticated access to Forge SeaweedFS and creation of the Link bucket.

First login is the bootstrap admin `admin@nereidai.local`. The post-deploy CLI
uses the one-time bootstrap API, writes the strong password to
`.deployment/deploy-values/nereidlink/admin-credentials.env` (mode 0600), and
prints a save reminder. The signed default license and final license status are
in the same product values directory; deployment logs are under
`.deployment/deploy-logs/nereidlink/`. Existing passwords and licenses are
preserved on reruns; the vendor private key never enters the cluster. Confirm
unauthenticated API calls return 401.

### 7.3 Field gateways

| Component | Order / preflight | Authoritative procedure |
|---|---|---|
| **Field gateways** (EdgeX 4.0.2 + NereidInference + NereidEdge) | Last; not in the cluster (compose). Preflight: Link NodePorts 31883/31884 reachable; a one-secret-per-gateway credential pair created in the Link console. | NereidInference / NereidEdge repositories' compose docs; credential keys in the [reference](reference/accounts-dns-connections.md) §3.6–3.7 |

## 8. Phase 2 — end-to-end verification

Work through the full sign-off checklist:
[reference/fresh-cluster-checklist.md](reference/fresh-cluster-checklist.md)
(sections L6–L7). Minimum end-to-end gates:

- SSO loop: open a product domain unauthenticated → redirect to NereidIdentity
  → back with a session; single sign-on into another product in the same browser.
- MQTT: a client completes connect/hello/heartbeat over NodePort 31883 (TLS 31884).
- Every product domain serves a certificate chained to `internal-ca`.
- NFS subdirectories are separated per `<namespace>-<pvc>`.
- No `changeme*`/dev default password remains; retrieve and archive every Secret
  per the reference §5 commands.

## 9. ChartMuseum (optional, air-gapped only)

Skip entirely when product repositories are cloned locally — local chart paths
are the standard (deploy-standards §15.5). ChartMuseum only serves sites that
redistribute charts without source access. Bring your own ChartMuseum instance
(or any OCI/chart registry reachable on the site network) and publish the
charts packaged from the sibling product checkouts:

```bash
# Run from the workspace root; every product chart lives in its own repo.
helm package ../NereidIdentity/deploy/helm/nereididentity
helm package ../NereidSphere/deploy/helm/nereidsphere
# …repeat for each product chart, then upload the tgz files.
curl -fsS --data-binary "@nereididentity-0.0.1.tgz" \
  "http://<chartmuseum-host>/api/charts"
helm repo add nereidai http://<chartmuseum-host>
```

The ChartMuseum host is site infrastructure, named only in untracked operator
configuration; no committed document carries a real chart-registry hostname.

## 10. Production deltas

- Set every password explicitly at install time; no generated default flows out.
- Override the nfs-csi lab defaults (NFS server/share, image coordinates) with
  `values-prod.yaml`; narrow NFS sources and remove `no_root_squash`.
- Private Harbor projects with per-namespace pull secrets; default-deny
  NetworkPolicy; firewall per the [bootstrap guide](cluster-bootstrap.md) §3.2.
- Replace bootstrap/admin accounts and rotate NereidEdge gateway credentials
  one secret per gateway.

## 11. Troubleshooting

| Symptom | Check |
|---|---|
| Chart fails with `required` message | A secret/value field is empty in the values file; the message names it (§5). |
| `ImagePullBackOff` on a product pod | Node containerd mirror (§2.5) or the namespace pull secret (§3.2); confirm the image exists in Harbor. |
| Product cannot validate another product's TLS | The `nereid-internal-ca-tls` copy is missing in that namespace (§3.3); check the chart's CA secret key `ca.crt`. |
| Certificate stays `False`/not issued | `kubectl get clusterissuer`; `internal-ca` must be Ready (§4.2); inspect cert-manager logs. |
| PVC Pending on nfs-csi | `nfs-csi` StorageClass exists (§4.3); node `mount.nfs` present; NFS export reachable on TCP 2049. |
| Gateway never connects | NodePort 31883/31884 open; one-time Link gateway token regenerated if re-registered. |
