# GPU Device Plugins (NVIDIA / AMD / Intel)

A device plugin does one thing: advertise the node's GPUs to the kubelet as Kubernetes extended
resources:

- `nvidia.com/gpu`
- `amd.com/gpu`
- `gpu.intel.com/i915` (legacy i915 KMD; integrated/older discrete GPUs), `gpu.intel.com/xe`
  (new xe KMD; Battlemage and newer)

> Migrated from the NereidForge repository on 2026-10-19 and completed with all three vendors'
> artifacts. Product repositories no longer install device plugins; the vendor userspace stacks
> inside training images (CUDA/ROCm userspace, NEO/Level Zero) are out of scope for this file —
> see each product's ADRs.

| Vendor | Artifact | Image | Image status |
|---|---|---|---|
| NVIDIA | [`nvidia-gpu-plugin.yaml`](nvidia-gpu-plugin.yaml) | `<harbor-host>/nvidia/k8s-device-plugin:v0.17.1` | In Harbor (mirrored 2026-10-19) |
| AMD | [`amd-gpu-plugin.yaml`](amd-gpu-plugin.yaml) | `<harbor-host>/rocm/k8s-device-plugin:1.31.0.10` | In Harbor (mirrored 2026-10-19) |
| Intel | [`intel/`](intel/) (NFD + rules + GPU/NPU plugins) | `intel-gpu-plugin:0.36.0`, `intel-npu-plugin:0.36.0`, `nfd/node-feature-discovery:v0.17.1` | All in Harbor (verified 2026-10-19) |

The manifests are vendored copies of the upstream official manifests/kustomize (air-gapped
artifacts; installation never reaches github/helm repo), modified only for suite differences such
as the image address. When upgrading versions, replace the artifacts, images, and `images.md`
together; do not write install commands outside this directory.

## 0. Node prerequisites (a plugin that will not install is usually missing one of these)

| Vendor | Host requirement | Container-runtime requirement |
|---|---|---|
| NVIDIA | Kernel driver (`nvidia-smi` works) | Install **nvidia-container-toolkit** and run `nvidia-ctk runtime configure` for containerd |
| AMD | `amdgpu` kernel driver (matching ROCm version; the node exposes `/dev/kfd`, `/dev/dri/renderD*`) | The plugin is a privileged DaemonSet (enumerating device nodes under `/sys`); the node's default containerd is sufficient |
| Intel | i915/xe KMD (Battlemage needs NEO ≥ 26; userspace apt via the PPA `kobuk-team/intel-graphics`) | render-node permissions; the userspace compute stack lives inside training images, not on the host |

## 1. NVIDIA — k8s-device-plugin v0.17.1

Prerequisite: the node has the NVIDIA driver and nvidia-container-toolkit installed and containerd
restarted.

```bash
kubectl apply -f nvidia-gpu-plugin.yaml
```

The manifest includes a `nvidia.com/gpu:NoSchedule` toleration and `system-node-critical`
priority. When GPU time-slicing is needed (sharing one card between training and serving),
configure a separate config file; that is site policy and not part of the shared defaults.

## 2. AMD — ROCm k8s-device-plugin v1.31.0.10

```bash
kubectl apply -f amd-gpu-plugin.yaml
```

The upstream manifest is itself a privileged Pod (mounting `/sys` and the kubelet device-plugins
directory). Do not "fix" it by de-privileging — without privilege the plugin cannot enumerate GPUs.

## 3. Intel — GPU plugin 0.36.0 (NFD-based, the only supported path)

The Intel plugin **must be installed together with NFD (Node Feature Discovery)**: NFD detects
GPUs/NPUs and labels nodes with `intel.feature.node.kubernetes.io/gpu=true`,
`intel.feature.node.kubernetes.io/npu=true`, and similar labels; the plugin DaemonSet schedules
only onto labeled nodes. Do not use a bare DaemonSet that unconditionally starts a Pod on every
amd64 node.

Vendored under [`intel/`](intel/) (NFD brings its own `node-feature-discovery` namespace; the
plugin DaemonSet is fixed to `kube-system`):

```bash
# 1) NFD v0.17.1 (CRDs, master Deployment, worker DaemonSet, gc)
kubectl apply -f intel/nfd.yaml
# 2) Intel GPU/NPU NodeFeatureRules (cluster-level rules; labels gpu/npu etc.)
kubectl apply -f intel/node-feature-rules.yaml
# 3) GPU plugin 0.36.0 (shared-dev-num=10 + balanced allocation + monitoring)
kubectl apply -f intel/intel-gpu-plugin.yaml
# 4) NPU plugin 0.36.0 (optional, if nodes have an Intel NPU)
kubectl apply -f intel/intel-npu-plugin.yaml
```

Corresponding upstream kustomize refs (provenance only; do not fetch them at deploy time in an
air-gapped environment):

```text
deployments/nfd?ref=v0.36.0
deployments/nfd/overlays/node-feature-rules?ref=v0.36.0
deployments/gpu_plugin/overlays/monitoring_shared-dev_nfd?ref=v0.36.0
```

Suite-fixed parameters (deltas from the upstream overlay):

- `-shared-dev-num=10`: each physical GPU is advertised as 10 shareable devices, allowing GPU
  resource slicing later (Forge's GPU-capacity interface reads exactly this allocatable number).
- `-allocation-policy=balanced`: spread independent containers across physical GPUs instead of
  letting kubelet fill the first available shared devices; each single-device job still uses its
  own container-local `xpu:0`.
- `-enable-monitoring`: additionally registers the `gpu.intel.com/monitoring` resource (one per
  node, for monitoring workloads).
- Images go through Harbor; `i915` (integrated/older discrete) and `xe` (Battlemage/Arc discrete)
  are registered as different resources, so requesting `gpu.intel.com/xe` naturally schedules only
  onto discrete GPUs — no PCI allowlist needed.

Live verification 2026-10-19 (2 server nodes):

| Node | GPU | i915 | xe | monitoring |
|---|---|---|---|---|
| node-1 | Meteor Lake integrated | 10 | - | 1 |
| node-2 | Arrow Lake integrated + 2× Arc B580 | 10 | 20 | 1 |

NFD also labels NPU-equipped nodes with `intel.feature.node.kubernetes.io/npu=true`; if Intel NPUs
are present, install step 4's `intel-npu-plugin.yaml`.

## 4. Verification (common to all three vendors)

```bash
# Intel: inspect NFD labels first
kubectl get nodes -o json | python3 -c "
import json,sys
for n in json.load(sys.stdin)['items']:
    l=n['metadata']['labels']; c=n['status']['capacity']
    print(n['metadata']['name'], 'gpu-label=', l.get('intel.feature.node.kubernetes.io/gpu'),
          'i915=', c.get('gpu.intel.com/i915','-'), 'xe=', c.get('gpu.intel.com/xe','-'))"

# NVIDIA/AMD/Intel common: success means the corresponding extended resource appears in capacity
# (resource names contain a slash; use -o json when custom-columns cannot show them)
kubectl get ds -n kube-system | grep -E 'nvidia-device-plugin|amdgpu-device-plugin|intel-gpu-plugin'
kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail=20    # NVIDIA
kubectl -n kube-system logs -l name=amdgpu-dp-ds --tail=20               # AMD
kubectl -n kube-system logs -l app=intel-gpu-plugin --tail=20            # Intel
```
