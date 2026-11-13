# NereidAI Cluster Bootstrap Guide (from zero): Bare Metal → k3s → Rancher-managed

- Date: 2026-10-19
- Version anchors: Rancher **v2.15.0** (Docker single-container management server), k3s **v1.36.2+k3s1**,
  rancher-system-agent **v0.15.0** (delivered by Rancher internally, not installed manually)
- Verified environment: the Rancher container runs on `server1` (192.0.2.10); downstream cluster
  name **nereidai**, 2 servers (embedded etcd HA), built on 2026-10-13 following this guide. Worker
  nodes are optional and can be added whenever capacity requires (see §5.2)
- Image registry: Harbor `<harbor-host>` (192.0.2.20, HTTPS, Let's Encrypt certificate)
- This guide installs no NereidAI product. Hand-off:

  | Phase | Guide/Directory | Output |
  |---|---|---|
  | **-1 (this guide)** | `docs/deploy/cluster-bootstrap.md` | Rancher management server + a managed empty k3s cluster |
  | 0 Cluster shared prerequisites | [`../../deploy/prereqs/`](../../deploy/prereqs/README.md) + [`install-suite.md`](install-suite.md) §4 | cert-manager/internal-ca, nfs-csi StorageClass, GPU device plugins |
  | 1+ Suite products | [`install-suite.md`](install-suite.md) §6 onward | NereidIdentity / NereidSphere / NereidLink / NereidHorizon … |

## 1. Target topology (lab reference)

```
┌────────────────────────────────────────────────────────────────┐
│ Management server (Docker; in the lab co-located on server1; production must separate, see §9) │
│   rancher:v2.15.0 container  :28443(HTTPS) :28880(HTTP)         │
│   Persistence /srv/rancher → container /var/lib/rancher (incl. embedded etcd) │
└──────────────┬─────────────────────────────────────────────────┘
               │ Registration command delivery /system-agent-install.sh + /assets (Rancher self-service)
               │ Nodes only need access to 192.0.2.10:28443
               ▼
┌ Downstream k3s cluster nereidai (v1.36.2+k3s1, embedded etcd HA) ─────────┐
│ server1   192.0.2.10  server(etcd/cp/worker)  cluster-init          │
│ server2      192.0.2.11    server(etcd/cp/worker)                        │
│ (+ optional worker nodes, added as capacity requires)                    │
│ All nodes: --system-default-registry <harbor-host>                    │
└──────────────────────────────────────────────────────────────────────────┘
```

| Role | Hostname | IP | OS (live) | Notes |
|---|---|---|---|---|
| Management server + NFS + server1 | server1 | 192.0.2.10 | Ubuntu 26.04 LTS | Deployment host; needs docker-ce |
| server2 | server2 | 192.0.2.11 | Ubuntu 24.04.5 LTS | |

Worker nodes are optional. Add them with the worker registration command in §5.2 whenever the
cluster needs more capacity; the minimum HA cluster is the two servers above.

> Rancher v2.15 brings nodes under management using the **Cluster API (Turtles) Custom
> (bring your own host)** flow: the UI generates a one-time registration command for each host;
> the host runs `rancher-system-agent`, which pulls its plan from Rancher and installs/maintains
> k3s using the `system-agent-installer-k3s` image on Harbor. **You do not run the k3s install
> script manually, nor pass token/server parameters by hand.**

## 2. External prerequisites (this guide does not install them, only verifies)

1. **Harbor**: `<harbor-host>` (192.0.2.20) reachable, HTTPS certificate trusted. The
   **`rancher` project must exist and be public (anonymous pull allowed)** — this is the key to
   offline bootstrap: k3s system images and the Rancher agent are all pulled from
   `<harbor-host>/rancher/...`, so no node needs registry credentials during bootstrap.
   The image list is in Appendix §11; every image must be in place before creating the cluster.
2. **NFS**: the lab uses local NFS on server1 (exported in §3.3); production uses independent storage.
3. The **chart repository** (optional, air-gapped redistribution only; see
   install-suite §9) is **not used** at this phase; it belongs to the next phase.
4. All hosts can resolve/reach: `<harbor-host>:443`, the management server
   `192.0.2.10:28443`, and NFS `192.0.2.10:2049`.

## 3. Host preparation (all nodes)

### 3.1 OS, network, accounts

- Ubuntu 24.04 / 26.04 (live: two machines on 26.04, one on 24.04.5, all amd64); static IP; set
  hostnames per the topology table.
- Each node's `/etc/hosts` contains at least (use internal DNS when available):

  ```text
  192.0.2.20  <harbor-host>
  192.0.2.10  <management-server>
  ```

- The deployment host (server1) has SSH + passwordless sudo to the other nodes (for file
  distribution and troubleshooting).
- Time sync: confirm with `timedatectl` that an NTP service is active and the clock is
  synchronized. etcd is clock-sensitive; unsynced clocks cause repeated warnings.
- swap: recommended off in production (`swapoff -a` and comment out `/etc/fstab`). The live lab
  keeps a 16G swapfile; measured usage is about 0 and the cluster runs fine — this is a lab
  exception, not a recommended configuration.
- All **downstream nodes** install the NFS client (CSI mounts need `mount.nfs`):
  `sudo apt install -y nfs-common`.

### 3.2 Ports to open (when a firewall is enabled)

| Direction | Port | Purpose |
|---|---|---|
| Nodes/browser → server1 | TCP 28443, 28880 | Rancher management UI/API (container mappings; non-standard live ports) |
| Nodes → <harbor-host> | TCP 443 | Harbor image pulls |
| server ↔ server | TCP 2379-2381 | Embedded etcd |
| agent/worker → server | TCP 6443, 9345 | Kubernetes API, k3s supervisor |
| Between nodes | UDP 8472 | Flannel VXLAN |
| Between nodes | TCP 10250 | kubelet |
| Node inbound | TCP 30000-32767 | NodePort (incl. MQTT 31883/31884) |
| Nodes → NFS | TCP 2049 | NFSv4 |

In the live lab ufw is inactive on both hosts; production must converge per this table and must
not rely on an "everything open on the internal network" assumption.

### 3.3 NFS server (server1)

```bash
sudo apt install -y nfs-kernel-server
sudo mkdir -p /data/nereidai
echo '/data/nereidai *(rw,sync,no_subtree_check,no_root_squash)' | sudo tee -a /etc/exports
sudo exportfs -arv
sudo systemctl enable --now nfs-server
```

Verify from another node: `sudo mount -t nfs 192.0.2.10:/data/nereidai /mnt && sudo umount /mnt`.

> `/data/nereidai` is the suite-shared export (this phase only creates the directory; the nfs-csi
> StorageClass is created in Phase 0, with subdirectories isolated automatically by the CSI as
> `<namespace>-<pvc>`). The live site also has a Forge-specific `/data/nereidforge_share`, which
> is unrelated to this guide. `no_root_squash` + world-writable suits a trusted lab only;
> production should narrow the source network and use a squash policy.

### 3.4 Install Docker on the management server (server1 only)

Live version: docker-ce 29.5.3 (Docker official apt repository, Ubuntu 26.04 package). Install
docker-ce / containerd.io from the official Docker repository; for an offline environment,
prepare the deb set in advance with `apt-get download`.

Pre-pull the Rancher image (the `rancher` project is public, no docker login needed; offline,
`docker save` on an internet-connected machine then `docker load`):

```bash
sudo docker pull <harbor-host>/rancher/rancher:v2.15.0
```

## 4. Start the Rancher management server

### 4.1 Start the container (official image, stock entrypoint)

```bash
sudo mkdir -p /srv/rancher
sudo docker run -d --name rancher --restart=unless-stopped --privileged \
  -p 28443:443 -p 28880:80 \
  -v /srv/rancher:/var/lib/rancher \
  -e TZ=Asia/Shanghai \
  <harbor-host>/rancher/rancher:v2.15.0
```

Key points:

- **`--privileged` is required**: the Docker form of Rancher runs an embedded k3s (the local
  management cluster) inside the container.
- `/srv/rancher` is the only volume that must persist; it holds management state and the embedded
  etcd (about 3.7G live). If the container is deleted/upgraded but this directory is kept,
  management state is not lost.
- Use the **official stock entrypoint**; do not bind-mount a custom entrypoint (repair scripts are
  for troubleshooting only, see §10.4).
- Wait for readiness (about 1-2 minutes):

  ```bash
  curl -sk https://192.0.2.10:28443/ping   # returns pong
  sudo docker logs -f rancher                  # shows Listening on :443
  ```

### 4.2 First boot

1. Open `https://192.0.2.10:28443` in a browser (self-signed certificate; the trust warning is
   expected — the cert is the Rancher dynamic-listener self-signed CA, valid for 10 years).
2. Set the `admin` bootstrap password (a one-time opportunity on first login; if lost, follow the
   official Rancher password-reset procedure).
3. Confirm **Server URL = `https://192.0.2.10:28443`**: this is where every downstream agent
   dials back, and it **must be confirmed before creating a downstream cluster** — changing the
   URL after the cluster exists requires re-managing it. Do not use the browser's
   localhost/127.0.0.1.

### 4.3 Set the global default registry (required before creating the cluster)

In the Rancher UI: **Global Settings → system-default-registry**, set it to:

```text
<harbor-host>
```

This single setting affects both:

- The `/etc/rancher/k3s/config.yaml.d/50-rancher.yaml` rendered on every downstream node carries
  `--system-default-registry <harbor-host>`, so system images (pause/coredns/traefik/metrics)
  are all pulled from `<harbor-host>/rancher/...`;
- Components subsequently deployed into Rancher's local cluster (fleet / turtles / webhook) also
  go through this registry.

Live verification: both node k3s arguments and the crictl image list show
`<harbor-host>/rancher/*`, with no docker.io pulls.

## 5. Create the downstream k3s cluster nereidai

### 5.1 Create the cluster in Rancher (Custom / bring your own host)

Cluster Management → Create → **Custom** (bring your own host; Cluster API custom-host flow):

| Setting | Value | Notes |
|---|---|---|
| Cluster name | `nereidai` | Written into the node label `plan.cattle.io/cluster-name` on every node |
| Kubernetes Version | **v1.36.2+k3s1** | The Rancher v2.15.0 image defaults to v1.36.1+k3s1; the live standard is pinned to v1.36.2, so select it explicitly in the dropdown |
| Ingress controller | traefik | k3s default; the product guides depend on it |
| etcd snapshot schedule | `0 */5 * * *` | Live value: local snapshot every 5 hours |
| etcd snapshot retention | `5` | |
| Networking | default (Flannel VXLAN) | |

First create the cluster object (no hosts yet; it waits for registration).

### 5.2 Register hosts one at a time

After the cluster is created, the UI generates **a one-time registration command per host** (the
token is one per host; to re-register or retry after failure, regenerate the command to get a new
token). Command shape (token/ca-checksum as generated by the UI):

```bash
# Server nodes (run once each on server1 and server2, each with its own generated command)
curl --insecure -fL https://192.0.2.10:28443/system-agent-install.sh | \
  sudo sh -s - --server https://192.0.2.10:28443 \
  --label 'cattle.io/os=linux' \
  --token <one-time-token-for-this-host> \
  --ca-checksum <CA-SHA256-from-UI> \
  --etcd --controlplane --worker

# Optional worker node (run on each additional worker host; generate a fresh
# one-time command per host — future workers use the same shape)
curl --insecure -fL https://192.0.2.10:28443/system-agent-install.sh | \
  sudo sh -s - --server https://192.0.2.10:28443 \
  --label 'cattle.io/os=linux' \
  --token <one-time-token-for-this-host> \
  --ca-checksum <same-as-above> \
  --worker
```

Order and observation points:

1. **server1 first**: it is the `--cluster-init` node (the plan decides this automatically; no
   manual flag needed). The `rancher-system-agent.service` appears on the host; the plan pulls
   `<harbor-host>/rancher/system-agent-installer-k3s:v1.36.2-k3s1` to install k3s. Wait in the
   Rancher UI until the first server is Ready (about 3-5 minutes).
2. **server2 next**: the plan joins it automatically as a second server into the same embedded etcd
   (2 voters). This completes the minimum HA cluster.
3. **(Optional) Add workers**: for each additional worker host, generate a fresh command and run it
   with `--worker` — a pure agent, no etcd/control-plane role.
4. The install script and the system-agent binary are both self-served by the Rancher container
   (`/system-agent-install.sh`, `/assets/...`, verified 200 live); nodes need **no public internet
   during registration**, only network access to Rancher and Harbor.

Troubleshooting entry points on a node:

```bash
sudo systemctl status rancher-system-agent
sudo journalctl -u rancher-system-agent -f
sudo ls /var/lib/rancher/agent/applied/      # applied plans (incl. rendered k3s config)
```

### 5.3 Private registry authentication (live projects are public; normally skippable)

Live, the `rancher` / `nereidai` / `nereidforge` Harbor projects are all **public**, so bootstrap
and system images pull anonymously and **cluster bootstrap needs no** registries auth file. If a
site's Harbor projects are private, choose one of:

- **Recommended**: in the cluster-creation wizard's Registries settings, fill in the mirror and
  credentials for `<harbor-host>`; Rancher renders them into each host's plan (managed with the
  cluster lifecycle; rebuilt nodes pick them up automatically).
- **Manual (adopted live later)**: place `/etc/rancher/k3s/registries.yaml` on every node:

  ```yaml
  mirrors:
    <harbor-host>:
      endpoint:
        - "https://<harbor-host>"
  configs:
    <harbor-host>:
      auth:
        username: admin
        password: "<harbor-password>"
  ```

  Note: this path is also managed by the Rancher plan (when the plan's config is empty it writes
  `{"configs":{},"mirrors":null}`), so cluster reconfiguration/node rebuild can overwrite the
  manual file and it must be replaced. The long-term approach is the first one (in-wizard config).
  Product-image mirror rewrites (docker.io/ghcr.io/quay.io/... to the internal registry) are
  rendered separately by `deploy/scripts/harbor-sync.sh node-mirror --apply` (deploy-standards §15.3).

## 6. Acceptance

On any server node (live, from server1):

```bash
sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get nodes -o wide
# Expected: server1/server2 both have role control-plane,etcd,worker (plus any optional workers with role worker); version v1.36.2+k3s1

sudo env KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl get pods -A | grep -E 'cattle|fleet'
# cattle-cluster-agent(2), rancher-webhook, fleet-agent, system-upgrade-controller Running

sudo k3s crictl images | grep <harbor-host>/rancher
# System images all come from Harbor (cross-check against the Appendix §11 list)

sudo ls /var/lib/rancher/k3s/server/db/snapshots    # etcd local snapshots appear on servers
```

In the Rancher UI the cluster `nereidai` is **Active**, and the Machine Inventory shows all three
hosts Present/Ready.

kubeconfig: on a server node it is `/etc/rancher/k3s/k3s.yaml` (root-readable); sudo drops
KUBECONFIG, so consistently use
`sudo env HOME=/root KUBECONFIG=/etc/rancher/k3s/k3s.yaml kubectl ...`. For distribution, prefer
downloading a read-only kubeconfig from the Rancher UI over copying the superuser config off a
server.

## 7. Backup

| Object | Backup method | Recovery notes |
|---|---|---|
| Rancher management state | After `docker stop rancher`, archive `/srv/rancher` (holds embedded etcd/management-state) | Restart with the same image mounting this directory; note the entrypoint issue in §10.4 for recovery scenarios |
| Downstream etcd | Rancher takes scheduled snapshots automatically (`0 */5 * * *`, retention 5), stored locally on servers at `/var/lib/rancher/k3s/server/db/snapshots`; trigger/restore from the Rancher UI | **Prefer the Rancher UI/snapshot restore flow**; do not run k3s etcd-snapshot subcommands manually on managed nodes |

## 8. Node rebuild / re-management

When a host must be reinstalled or a failed registration retried, run on that host (live historical
commands; note these wipe local k3s data):

```bash
sudo rancher-system-agent-uninstall.sh
sudo /usr/local/bin/k3s-uninstall.sh         # server nodes
# The worker-node equivalent is /usr/local/bin/k3s-agent-uninstall.sh
sudo rm -rf /etc/rancher /var/lib/rancher
```

Then regenerate a registration command for that host in the Rancher UI and run it. Delete the old
Machine record in the UI to avoid duplicate machine objects.

## 9. Production form (deltas from the lab)

1. **Independent management server**: the Docker single container (embedded single-node etcd) is
   for lab/POC only. Production uses a dedicated management cluster (an independent 3-node k3s +
   Rancher installed via Helm, HA), physically separate from the downstream business cluster; the
   Server URL points at a stable DNS + load balancer (not a single business node's IP).
2. **Downstream control plane**: an odd number of 3/5 servers, etcd deployed independently on
   control-plane nodes with separate workers; 10GbE/low-latency interconnect.
3. **Storage**: NFS is for shared artifacts/exports only; hot databases use block storage/local
   disks (see the product deployment guide §2).
4. **Network**: default-deny NetworkPolicy; converge the firewall per the §3.2 port table; switch
   Harbor projects to private with per-node/per-namespace credentials; narrow NFS sources and
   remove no_root_squash.
5. **Fully offline**: stage images per Appendix §11; Rancher nodes and downstream nodes have no
   public-internet dependency throughout (the registration script and agent binary are
   self-served by Rancher; system images go through Harbor).

## 10. Troubleshooting

### 10.1 A node never appears / the agent will not start

- Verify the server URL and token in the command (one-time; regenerating invalidates the old
  token) and the ca-checksum.
- `journalctl -u rancher-system-agent`; TCP from the agent to `https://192.0.2.10:28443`
  must work.
- Stuck pulling `system-agent-installer-k3s`: check node access to 443/Harbor and whether the
  `rancher` project images are all present (§11).

### 10.2 System images fall back to docker.io

This means system-default-registry did not take effect: check Rancher Global Settings (§4.3) and
whether the node's `/etc/rancher/k3s/config.yaml.d/50-rancher.yaml` contains
`system-default-registry: <harbor-host>`. That file is rendered by the plan — do not edit it by
hand; change the setting and have Rancher re-deliver the plan.

### 10.3 etcd clock/snapshot anomalies

First check `timedatectl` (NTP sync) and server-to-server 2379/2381 connectivity; under 3-node HA
snapshots land locally on schedule, and recovery always goes through the Rancher UI.

### 10.4 Rancher container crashloops after reusing old data (cluster-reset)

Live experience: when restoring/reusing the `/srv/rancher` data directory, the Rancher **stock
entrypoint** may run `k3s server --cluster-reset` a second time, and k3s refuses a second reset,
crashlooping the container (the live management container was rebuilt for this reason). The
on-site workaround was to bind-mount an entrypoint script that only runs reset when a `reset-flag`
exists (live on server1: `/data/rancher/entrypoint.sh`, for reference only — not part of the
standard install). A fresh install never triggers this; for a formal recovery follow the official
Rancher backup/restore flow and do not directly reuse a data directory in an unknown state.

## 11. Appendix: offline image list (verified live 2026-10-19)

### 11.1 Management server (Docker)

| Image | Purpose |
|---|---|
| `<harbor-host>/rancher/rancher:v2.15.0` | The Rancher container itself (images needed by its embedded local k3s are packaged inside the image) |

### 11.2 Rancher local management cluster components (pulled from Harbor after setting system-default-registry)

| Image | Live tag |
|---|---|
| `rancher/rancher-agent` | v2.15.0 |
| `rancher/rancher-webhook` | v0.11.0 |
| `rancher/fleet` / `rancher/fleet-agent` | v0.16.0 |
| `rancher/turtles` | v0.27.0 |
| `rancher/cluster-api-controller` | v1.13.3 |
| `rancher/remotedialer-proxy` | v0.8.0 |
| `rancher/system-upgrade-controller` | v0.20.1 |

### 11.3 Downstream k3s v1.36.2 cluster (measured on nodes via crictl)

| Image | tag | Purpose |
|---|---|---|
| `rancher/system-agent-installer-k3s` | v1.36.2-k3s1 | Vehicle for plan-driven k3s install/upgrade (contains the k3s binary) |
| `rancher/system-agent` | v0.15.0-suc | system-upgrade-controller upgrades the agent |
| `rancher/rancher-agent` | v2.15.0 | cattle-cluster-agent |
| `rancher/rancher-webhook` | v0.11.0 | |
| `rancher/fleet-agent` | v0.16.0 | |
| `rancher/system-upgrade-controller` | v0.20.1 | |
| `rancher/mirrored-pause` | 3.6 | sandbox |
| `rancher/mirrored-coredns-coredns` | 1.14.4 | DNS |
| `rancher/mirrored-library-traefik` | 3.7.4 | Ingress |
| `rancher/mirrored-library-busybox` | 1.37.0 | helm chart helper container |
| `rancher/mirrored-metrics-server` | v0.8.1 | |
| `rancher/klipper-lb` | v0.4.17 | ServiceLB |
| `rancher/klipper-helm` | v0.11.1-build20260615 | Managed chart jobs |
| `rancher/local-path-provisioner` | v0.0.36 | local-path StorageClass |

> These tags are the combination Rancher v2.15.0 actually selects when rendering the plan for
> v1.36.2+k3s1 (cross-checked live on the nodes' crictl and Harbor). After upgrading
> the Rancher/k3s version, the image-tag combination follows the new plan — do not pre-push images
> from an old list.

Mirror command pattern from an internet-connected machine (the `rancher` project must exist first):

```bash
skopeo copy --all docker://docker.io/rancher/mirrored-pause:3.6 \
  docker://<harbor-host>/rancher/mirrored-pause:3.6
# Same pattern for the rest; copy tags exactly as listed above
```

After the cluster is ready, the next step is [`../../deploy/prereqs/`](../../deploy/prereqs/README.md)
(cert-manager, nfs-csi, GPU device plugins) and [`install-suite.md`](install-suite.md) §4.
