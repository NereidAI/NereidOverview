# NereidAI Cluster-Shared Prerequisites

Prepare the cluster with the
[cluster bootstrap guide](../../docs/deploy/cluster-bootstrap.md), then install
these shared components before any product. Continue with the
[suite installation guide](../../docs/deploy/install-suite.md), which provides
the ordered commands and acceptance gates.

This directory contains cluster-level components shared by multiple NereidAI
products. Product charts preflight these contracts; they do not install a second
copy of cluster infrastructure.

## Components

| Component | Source | Contract |
|---|---|---|
| cert-manager and `internal-ca` | [Suite guide §4.1](../../docs/deploy/install-suite.md#41-cert-manager-and-internal-ca) and [`manifests/00-internal-ca.yaml`](manifests/00-internal-ca.yaml) | Ready cert-manager, `internal-ca` ClusterIssuer, and CA public-certificate distribution |
| NFS CSI and StorageClass | [`charts/nfs-csi/`](charts/nfs-csi/) and [suite guide §4.2](../../docs/deploy/install-suite.md#42-nfs-csi-storageclass) | Working `nfs-csi` StorageClass with per-PVC subdirectories |
| GPU/NPU device plugins | [`device-plugins/`](device-plugins/README.md) | Hardware-specific extended resources visible in node capacity |

`charts/cert-manager-kubeflow-hook/` is an optional helper for a parent Kubeflow
Kustomize installation. It renders the selected public upstream manifests and
does not replace the suite cert-manager installation above.

All images retain pinned public upstream coordinates. The operator host and
cluster nodes must be able to retrieve every selected chart and image without
authentication. Verify the exact version before installation.

## Product-side preflight

Run these checks from the NereidOverview repository root after completing the
relevant installation steps:

```bash
kubectl get clusterissuer internal-ca
kubectl get storageclass nfs-csi
kubectl get nodes -o jsonpath='{.items[*].status.allocatable}' \
  | grep -E 'nvidia.com/gpu|amd.com/gpu|gpu.intel.com'
```

The last command is required only for products and workloads that need the
corresponding hardware. Install plugins only for hardware actually present.

When a prerequisite is missing, stop and complete the shared-prerequisite phase.
Do not let a product installer create an independent replacement.
