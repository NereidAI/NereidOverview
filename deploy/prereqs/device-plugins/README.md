# GPU Device Plugins (NVIDIA / AMD / Intel)

A device plugin advertises node hardware to the kubelet as Kubernetes extended
resources:

- `nvidia.com/gpu`;
- `amd.com/gpu`;
- `gpu.intel.com/i915` for the legacy i915 kernel driver; and
- `gpu.intel.com/xe` for the xe kernel driver used by newer Intel GPUs.

Install only the plugins matching the prepared hardware. Product repositories
preflight these resources but do not install cluster device plugins themselves.
Vendor userspace stacks inside training images are outside this guide.

## Public artifacts

| Vendor | Manifest | Pinned public images |
|---|---|---|
| NVIDIA | [`nvidia-gpu-plugin.yaml`](nvidia-gpu-plugin.yaml) | `nvcr.io/nvidia/k8s-device-plugin:v0.17.1` |
| AMD | [`amd-gpu-plugin.yaml`](amd-gpu-plugin.yaml) | `docker.io/rocm/k8s-device-plugin:1.31.0.10` |
| Intel | [`intel/`](intel/) | `docker.io/intel/intel-gpu-plugin:0.36.0`, `docker.io/intel/intel-npu-plugin:0.36.0`, `registry.k8s.io/nfd/node-feature-discovery:v0.17.1` |

These are vendored copies of official upstream manifests and Kustomize
artifacts. They retain public image coordinates. When upgrading, update the
manifests and all corresponding pinned versions together, then verify manifest
rendering, anonymous image retrieval, and the resource names below.

Run the commands from this `device-plugins` directory.

## 1. Node prerequisites

| Vendor | Host requirement | Container-runtime requirement |
|---|---|---|
| NVIDIA | Working kernel driver; `nvidia-smi` succeeds | Install `nvidia-container-toolkit`, configure containerd with `nvidia-ctk runtime configure`, and restart containerd |
| AMD | Matching `amdgpu` kernel driver; `/dev/kfd` and `/dev/dri/renderD*` are present | The privileged plugin DaemonSet enumerates device nodes under `/sys`; the default containerd configuration is sufficient |
| Intel | i915/xe kernel driver and the userspace version required by the selected GPU | Correct render-node permissions; compute userspace remains in the workload images |

Stop if the host driver or device nodes are absent. Applying a plugin does not
install or repair a host driver.

## 2. NVIDIA — k8s-device-plugin v0.17.1

```bash
kubectl apply -f nvidia-gpu-plugin.yaml
```

The manifest includes a `nvidia.com/gpu:NoSchedule` toleration and
`system-node-critical` priority. GPU time-slicing is site policy and requires a
separate, deliberately reviewed configuration.

## 3. AMD — ROCm k8s-device-plugin v1.31.0.10

```bash
kubectl apply -f amd-gpu-plugin.yaml
```

The upstream workload is privileged and mounts `/sys` plus the kubelet
device-plugin directory. Those permissions are required for GPU enumeration.

## 4. Intel — GPU/NPU plugins 0.36.0 with NFD

Install Node Feature Discovery (NFD) and its rules before the Intel plugins. NFD
labels suitable nodes, including
`intel.feature.node.kubernetes.io/gpu=true` and
`intel.feature.node.kubernetes.io/npu=true`; the plugin DaemonSets use those
labels instead of starting on every amd64 node.

NFD creates its own `node-feature-discovery` namespace. The Intel plugin
DaemonSets remain in `kube-system`.

```bash
# NFD v0.17.1: CRDs, master Deployment, worker DaemonSet, and garbage collector.
kubectl apply -f intel/nfd.yaml
# Intel GPU/NPU NodeFeatureRules.
kubectl apply -f intel/node-feature-rules.yaml
# Intel GPU plugin 0.36.0.
kubectl apply -f intel/intel-gpu-plugin.yaml
# Optional: install only when Intel NPUs are present.
kubectl apply -f intel/intel-npu-plugin.yaml
```

The vendored artifacts correspond to these upstream Kustomize paths at the
plugin release:

```text
deployments/nfd?ref=v0.36.0
deployments/nfd/overlays/node-feature-rules?ref=v0.36.0
deployments/gpu_plugin/overlays/monitoring_shared-dev_nfd?ref=v0.36.0
```

Suite-specific GPU settings are:

- `-shared-dev-num=10`: advertise ten shareable resources per physical GPU;
- `-allocation-policy=balanced`: spread independent containers across physical
  GPUs; and
- `-enable-monitoring`: expose one `gpu.intel.com/monitoring` resource per node.

The i915 and xe resource names are distinct, so requesting
`gpu.intel.com/xe` restricts scheduling to compatible xe-backed nodes.

## 5. Verification

Wait for the selected workloads, then inspect labels, capacity, and logs:

```bash
kubectl -n node-feature-discovery rollout status deployment/nfd-master --timeout=180s
kubectl -n kube-system rollout status daemonset/intel-gpu-plugin --timeout=180s

kubectl get nodes -o json | python3 -c "
import json,sys
for n in json.load(sys.stdin)['items']:
    labels=n['metadata']['labels']; capacity=n['status']['capacity']
    print(n['metadata']['name'],
          'gpu-label=', labels.get('intel.feature.node.kubernetes.io/gpu'),
          'i915=', capacity.get('gpu.intel.com/i915','-'),
          'xe=', capacity.get('gpu.intel.com/xe','-'))"

kubectl get ds -n kube-system | grep -E 'nvidia-device-plugin|amdgpu-device-plugin|intel-gpu-plugin'
kubectl -n kube-system logs -l name=nvidia-device-plugin-ds --tail=20
kubectl -n kube-system logs -l name=amdgpu-dp-ds --tail=20
kubectl -n kube-system logs -l app=intel-gpu-plugin --tail=20
```

Run only the rollout/log commands for installed components. Acceptance requires
the expected extended resources in node capacity and healthy plugin Pods on the
intended hardware nodes. Record this evidence before installing Forge.
