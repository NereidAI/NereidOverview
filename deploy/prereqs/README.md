# NereidAI Cluster-shared Prerequisites

> Order: the cluster itself (bare metal → k3s → Rancher management) is covered in
> [`../../docs/deploy/cluster-bootstrap.md`](../../docs/deploy/cluster-bootstrap.md);
> once the cluster is ready, install the shared components in this directory; only then do the
> products get deployed ([`../../docs/deploy/install-suite.md`](../../docs/deploy/install-suite.md)).

This directory holds deployment artifacts and docs for **cluster-level components shared by
multiple NereidAI products**. They belong to no single product (NereidForge / NereidLink /
NereidHorizon / NereidSphere …) and are planned and installed uniformly at the suite layer; product
repositories **no longer ship install logic for these components** and only preflight-check them
before deployment.

> Migrated from the NereidForge repository on 2026-10-19. Reason: cert-manager, CSI storage
> drivers, and GPU device plugins are common components almost every product needs; keeping them
> in a single product repository caused duplicate installs, version drift, and the boundary
> inversion of "a product installing cluster infrastructure".

## Component list

| Component | Form | Notes |
|---|---|---|
| **cert-manager** + `internal-ca` ClusterIssuer | Install walkthrough: [`../../docs/deploy/install-suite.md`](../../docs/deploy/install-suite.md) §4.1–§4.2; manifest in [`manifests/00-internal-ca.yaml`](manifests/00-internal-ca.yaml) | Prefer the official jetstack helm chart; `charts/cert-manager-kubeflow-hook/` is only an alternative wrapper for the Kubeflow upstream-manifest approach and is normally unused |
| **csi-driver-nfs** + StorageClass `nfs-csi` | Helm wrapper chart: [`charts/nfs-csi/`](charts/nfs-csi); install-suite prerequisites section | RWX storage prerequisite for product PVCs; the SC name `nfs-csi` is the default contract in product values |
| **GPU device plugins** (NVIDIA / AMD / Intel) | Manifests + guide: [`device-plugins/`](device-plugins/README.md) | Only advertises host GPUs as extended resources; drivers/container-runtime setup are node prerequisites |

## Product-side contract

Product deployers only check, never install:

```bash
kubectl get clusterissuer internal-ca          # cert-manager + internal CA
kubectl get storageclass nfs-csi               # RWX StorageClass (name may change via site values)
kubectl get nodes -o jsonpath='{.items[*].status.allocatable}' | grep -E 'nvidia.com/gpu|amd.com/gpu|gpu.intel.com'
```

When a prerequisite is missing, the product installer must **fail with an error pointing at this
directory/the deployment guide**, never install it itself.

## Offline images

The shared-component image list is in [`images.md`](images.md); these images go into the
suite-level offline bundle and are not duplicated in any single product's offline image list.
