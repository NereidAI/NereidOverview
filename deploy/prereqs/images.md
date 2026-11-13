# Cluster-shared Prerequisite Components — Offline Image Manifest

> Migrated 2026-10-19 from NereidForge's
> `infra/scripts/01_prepare-offline-images.sh`, `lib/images.sh`, `lib/config.sh`. These services
> are **shared by multiple products** and enter the suite-level offline bundle; they are not
> duplicated in any single product's offline image list.
>
> All tags/paths below were checked on 2026-10-19. Entries marked "already mirrored" existed on
> the live cluster (`crictl images`) or in the internal registry at the check date; entries
> marked "not mirrored" were verified only at the upstream source, and must be mirrored before
> deploying to corresponding nodes.
>
> **Host-free manifest (deploy-standards §15.3):** this file names no internal registry hostname. The
> machine-readable counterpart [`images.txt`](images.txt) carries each public coordinate plus
> its registry-relative target path; `deploy/scripts/harbor-sync.sh mirror` injects the site
> registry hostname from the untracked `harbor.env` / `HARBOR_HOST` at run time. Cluster nodes
> resolve the public coordinates through the containerd mirror rendered by
> `harbor-sync.sh node-mirror`.

| Category | Upstream image | Registry-relative target | Version | Remarks |
|---|---|---|---|---|
| cert-manager | `quay.io/jetstack/cert-manager-controller` | `nereidai/cert-manager-controller` | v1.15.3 | Suite-standard version; see install-suite prerequisites |
| cert-manager | `quay.io/jetstack/cert-manager-webhook` | `nereidai/cert-manager-webhook` | v1.15.3 | |
| cert-manager | `quay.io/jetstack/cert-manager-cainjector` | `nereidai/cert-manager-cainjector` | v1.15.3 | |
| cert-manager | `quay.io/jetstack/cert-manager-startupapicheck` | `nereidai/cert-manager-startupapicheck` | v1.15.3 | helm install validation Job |
| cert-manager | `quay.io/jetstack/cert-manager-acmesolver` | `nereidai/cert-manager-acmesolver` | v1.15.3 | ACME issuer scenarios; unused by the internal CA but kept complete per chart version |
| csi-driver-nfs | `registry.k8s.io/sig-storage/nfsplugin` | `nereidai/csi-driver-nfs` | v4.7.0 | Referenced by `charts/nfs-csi`; see install-suite prerequisites |
| csi-driver-nfs | `registry.k8s.io/sig-storage/csi-provisioner` | `nereidai/csi-provisioner` | v5.0.1 | |
| csi-driver-nfs | `registry.k8s.io/sig-storage/csi-snapshotter` | `nereidai/csi-snapshotter` | v8.0.1 | externalSnapshotter disabled by default; image kept anyway |
| csi-driver-nfs | `registry.k8s.io/sig-storage/livenessprobe` | `nereidai/livenessprobe` | v2.13.1 | |
| csi-driver-nfs | `registry.k8s.io/sig-storage/csi-node-driver-registrar` | `nereidai/csi-node-driver-registrar` | v2.11.1 | |
| NVIDIA plugin | `nvcr.io/nvidia/k8s-device-plugin` | `nvidia/k8s-device-plugin` | v0.17.1 | Already mirrored (2026-10-19); manifest `device-plugins/nvidia-gpu-plugin.yaml` |
| AMD plugin | `docker.io/rocm/k8s-device-plugin` | `rocm/k8s-device-plugin` | 1.31.0.10 | Already mirrored (2026-10-19); manifest `device-plugins/amd-gpu-plugin.yaml` |
| Intel GPU plugin | `docker.io/intel/intel-gpu-plugin` | `intel/intel-gpu-plugin` | 0.36.0 | Already mirrored (verified and live 2026-10-19); NFD artifacts in `device-plugins/intel/` |
| Intel NPU plugin | `docker.io/intel/intel-npu-plugin` | `intel/intel-npu-plugin` | 0.36.0 | Mirrored only at sites with NPU hardware; manifests `device-plugins/intel/intel-npu-plugin.yaml` and `intel/npu_plugin/` |
| NFD (Intel dependency) | `registry.k8s.io/nfd/node-feature-discovery` | `nfd/node-feature-discovery` | v0.17.1 | Already mirrored (2026-10-19); version must match the `deployments/nfd` ref required by intel-device-plugins v0.36.0 |

Notes:

- cert-manager is installed uniformly under the registry project `nereidai` (the
  `nereidai/jetstack/...` paths in old lists were never mirrored; the registry also has a separate
  `jetstack` project holding v1.15.3/v1.16.1, but the live cluster actually uses
  `nereidai/cert-manager-*`, and all new deployments follow this table).
- Kubeflow 1.9 upstream manifests pin cert-manager **v1.21.1**, which is **not yet mirrored**. If a
  site needs Kubeflow 1.9: first reuse the existing v1.15.3 + `internal-ca` in the cluster (do not
  install a second copy); only if v1.21.1 is genuinely required, mirror the five-image set under
  the same `nereidai/cert-manager-*` relative paths, smoke-test, and then update the guide.
- When preparing images from scratch at a new site, device-plugin images need mirroring only at
  sites with the corresponding GPU/NPU hardware (skip without that hardware). Run on an
  internet-connected machine (upstream tags verified to exist with `skopeo inspect`
  on 2026-10-19):

  ```bash
  # HARBOR_HOST is read from harbor.env or the environment; never committed.
  ./deploy/scripts/harbor-sync.sh login
  ./deploy/scripts/harbor-sync.sh mirror deploy/prereqs/images.txt
  ```

  If the source registry's full multi-arch index contains variants that cannot be pulled, copy a
  single architecture with skopeo `--override-arch amd64` instead (cannot be combined with
  `--all`); all current lab nodes are amd64.
- CSI sidecar tags are bound to csi-driver-nfs **v4.7.0** (the subchart version vendored in
  `charts/nfs-csi`); when upgrading the driver, this table, `images.txt` and the chart values must
  change and be verified together — never bump a sidecar tag alone.
