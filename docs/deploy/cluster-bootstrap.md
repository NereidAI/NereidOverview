# NereidAI Rancher + k3s Bootstrap and Acceptance

This guide prepares an **empty, Rancher-managed downstream k3s cluster** using public Internet
services and official upstream sources. It does not install NereidAI products or the suite's shared
prerequisites.

Choose one route:

- **Existing cluster (preferred):** complete §2, verify the common prerequisites in §3, then run the
  read-only acceptance checks in §6.
- **From zero:** complete §3, optionally install Rancher and a downstream cluster with §4–§5, then
  run §6.

All commands below are instructions for the operator. Run them on the host named in the surrounding
text. Replace every example name, address, path, and credential with an approved site value before
running a command. The `example.org` names and `192.0.2.0/24` addresses in this guide are reserved
examples, not a deployable site configuration.

## 1. Scope, versions, and completion criteria

The optional installation path uses these explicit pins:

```bash
RANCHER_VERSION=v2.15.3
K3S_VERSION=v1.36.2+k3s1
```

Both releases have official public release records:

- [Rancher v2.15.3](https://github.com/rancher/rancher/releases/tag/v2.15.3)
- [k3s v1.36.2+k3s1](https://github.com/k3s-io/k3s/releases/tag/v1.36.2%2Bk3s1)

The [Rancher v2.15.3 support matrix](https://www.suse.com/suse-rancher/support-matrix/all-supported-versions/rancher-v2-15-3/)
certifies k3s v1.36. Before installation, confirm that the Rancher cluster creation UI offers the
exact k3s patch selected above. If it does not, stop and select a reviewed, compatible Rancher/k3s
pair; do not silently substitute another version. These pins are not minimum versions and are **not**
an instruction to upgrade an existing cluster.

A bootstrap is complete when:

1. Rancher shows the intended downstream cluster as **Active** and all expected machines as Ready.
2. Every Kubernetes node is Ready and runs the recorded, supported k3s version.
3. Core k3s services, the ingress controller, and Rancher agents are healthy.
4. DNS, required network paths, time synchronization, and NFS client connectivity pass §3 and §6.
5. No NereidAI product workload has been installed. k3s and Rancher system components are expected
   and do not make the cluster non-empty.

## 2. Existing-cluster fast path

Use this route when an empty k3s cluster is already managed by Rancher. Do not run the installation
or registration steps in §4–§5.

1. In **Rancher → Cluster Management**, confirm that:
   - the selected cluster is the intended downstream cluster, not Rancher's own management cluster;
   - its state is **Active**, with no provisioning, update, or error operation still running;
   - all expected nodes are present and Ready; and
   - its Kubernetes version is supported by the installed Rancher version and by the NereidAI suite
     release being planned.
2. Obtain a kubeconfig for that downstream cluster through Rancher. Use an account with only the
   access needed for installation and acceptance; do not copy a node administrator configuration to
   an operator workstation.
3. On the operator workstation, select the downloaded configuration and confirm the context:

   ```bash
   export KUBECONFIG="$HOME/.kube/nereidai.kubeconfig"
   kubectl config current-context
   kubectl get --raw='/healthz'
   ```

   The expected API health response is `ok`. Stop if the context names a different cluster.
4. Review the namespaces in Rancher or with `kubectl get namespaces`. Account for every non-system
   namespace. An empty target has no NereidAI product namespaces and no suite workloads; standard
   k3s and Rancher namespaces are expected.
5. Complete the applicable checks in §3, then go to §6. If the cluster fails a check, hand the
   finding to the cluster owner rather than rebuilding or re-registering it as part of acceptance.

## 3. Common prerequisites

### 3.1 Host identity, DNS, and TLS

Use a Linux release supported by both Rancher and k3s. Each management and downstream node needs a
unique hostname, stable addressing, sufficient disk and memory for its assigned role, and an
administrator with SSH and `sudo` access. Size worker capacity separately for the intended suite
products; the k3s minimums do not include application resources.

Create and verify the site's DNS records before registration. This example topology shows only the
required naming pattern:

| Purpose | Example name | Example address |
|---|---|---|
| Rancher endpoint | `rancher.example.org` | `192.0.2.10` |
| Downstream server 1 | `server1.example.org` | `192.0.2.11` |
| Downstream server 2 | `server2.example.org` | `192.0.2.12` |
| Downstream server 3 | `server3.example.org` | `192.0.2.13` |
| NFS service | `nfs.example.org` | `192.0.2.20` |
| Future suite ingress | `apps.example.org` | `192.0.2.30` |

The Rancher name must remain stable and resolve to the management endpoint from the operator
workstation and every downstream node. Node names must resolve consistently between nodes. Plan the
suite ingress records against the actual ingress external address; use the product naming in
[`install-suite.md`](install-suite.md) when those records are created.

Rancher HTTPS must use a certificate valid for its DNS name and trusted by downstream nodes. A
browser certificate exception is not node trust. If a site CA must be added to a node's trust store,
complete that change before registration and verify it without disabling TLS checks.

Run these read-only checks on the operator workstation and each downstream node after setting the
actual values:

```bash
RANCHER_HOST=rancher.example.org
RANCHER_URL="https://${RANCHER_HOST}"
NFS_SERVER=nfs.example.org

getent hosts "$RANCHER_HOST"
getent hosts "$NFS_SERVER"
curl -fsS "${RANCHER_URL}/ping"
```

The expected Rancher response is `pong`. Do not bypass certificate or hostname errors.

### 3.2 Time synchronization

Use reliable, consistently reachable time sources on the Rancher host, every downstream node, and
the NFS server. Correct clock synchronization is required for TLS, Kubernetes certificates, and
etcd.

Run on every host:

```bash
timedatectl status
timedatectl show --property=NTPSynchronized --value
```

The second command must return `yes`. Investigate clock offset or an inactive synchronization source
before proceeding; matching time-zone labels alone do not prove synchronization.

### 3.3 Firewall and public egress

Permit only the flows required by the selected architecture. The table assumes embedded etcd,
Flannel VXLAN, and the default k3s ingress/service load balancer.

| Source → destination | Protocol/port | Purpose |
|---|---|---|
| Operator and downstream nodes → Rancher | TCP 443 | UI, API, registration, and agent connections |
| Agents → downstream server nodes | TCP 6443 | Kubernetes API and k3s supervisor |
| Server ↔ server | TCP 2379–2380 | Embedded etcd; required for an HA server group |
| All downstream nodes ↔ all downstream nodes | UDP 8472 | Flannel VXLAN |
| All downstream nodes ↔ all downstream nodes | TCP 10250 | Kubelet API and metrics |
| Intended clients → ingress endpoint | TCP 80, 443 | Suite HTTP/HTTPS access when products are installed |
| Downstream nodes → NFS server | TCP 2049 | NFSv4 |
| Hosts → approved DNS resolvers | UDP/TCP 53 | Name resolution |
| Hosts → approved time sources | UDP 123 | Time synchronization |
| Rancher host and downstream nodes → required public services | TCP 443 | Operating-system packages and upstream container images |

Do not expose etcd, VXLAN, or NFS to the public Internet. Restrict every rule to its actual source
network. If the existing cluster uses another CNI, ingress design, or datastore, obtain its port
requirements from the cluster owner instead of applying the example rules unchanged.

The optional installation path pulls `docker.io/rancher/rancher` and Rancher-selected public k3s
images. Permit Docker Hub, its authentication and content-delivery endpoints, the operating system's
official repositories, and any documented redirects. CDN addresses can change, so use the service
names published by the provider rather than fixed resolved addresses.

These read-only requests test two public endpoints from the Rancher host:

```bash
curl -sS -o /dev/null -w 'Docker Hub API HTTP %{http_code}\n' \
  https://registry-1.docker.io/v2/
curl -fsS -o /dev/null \
  https://github.com/rancher/rancher/releases/tag/v2.15.3
```

An HTTP `401` from the Docker Hub API confirms network and TLS reachability; it is the expected
unauthenticated registry API response, not a failed image pull.

For the authoritative network requirements, see the
[Rancher port requirements](https://ranchermanager.docs.rancher.com/v2.15/getting-started/installation-and-upgrade/installation-requirements/port-requirements)
and [k3s requirements](https://docs.k3s.io/installation/requirements).

### 3.4 NFS service and clients

The storage owner must provide an existing NFSv4 service and export for the suite. Record its real
values in place of these examples:

```bash
NFS_SERVER=nfs.example.org
NFS_EXPORT=/srv/nfs/nereidai
```

Before handoff, confirm that:

- the export exists, has an approved access-control and quota policy, and permits the intended suite
  workloads to use it;
- every downstream node can resolve the NFS service and reach TCP 2049; and
- every downstream node has the operating system's NFS client utilities, including `mount.nfs`.

The following checks are read-only. Run them on every downstream node:

```bash
getent hosts "$NFS_SERVER"
command -v mount.nfs
timeout 5 bash -c "</dev/tcp/${NFS_SERVER}/2049"
```

The last command must return status `0`. Export permissions and dynamic provisioning still require a
write-capable test; that test belongs to the shared-storage installation in the next phase, not to
this read-only bootstrap acceptance.

## 4. Optional from-zero path: install Rancher

> Skip this section and §5 when using the existing-cluster fast path.
>
> The following single-container management endpoint is a minimal, non-HA installation. Rancher's
> supported production form is a separate three-node management cluster installed with Helm. For
> production, follow the official
> [Kubernetes/Helm installation](https://ranchermanager.docs.rancher.com/v2.15/getting-started/installation-and-upgrade/install-upgrade-on-a-kubernetes-cluster),
> then continue at §5. Do not place the management endpoint on a downstream workload node.

### 4.1 Prepare the management host and downstream nodes

Use a dedicated Linux management host with Docker Engine installed from
[Docker's official repository](https://docs.docker.com/engine/install/). The management host and all
downstream nodes need the DNS, time, firewall, and public-egress configuration in §3.

Obtain a publicly trusted certificate and private key for the real replacement for
`rancher.example.org`. Make the full certificate chain and key available on the management host as
`/srv/rancher-tls/fullchain.pem` and `/srv/rancher-tls/privkey.pem`, readable only by the
administrator and the Rancher container.

Set the installation values on the management host:

```bash
RANCHER_VERSION=v2.15.3
K3S_VERSION=v1.36.2+k3s1
RANCHER_HOST=rancher.example.org
RANCHER_URL="https://${RANCHER_HOST}"

sudo docker version
sudo test -r /srv/rancher-tls/fullchain.pem
sudo test -r /srv/rancher-tls/privkey.pem
```

On each new Debian or Ubuntu downstream node, install the registration and NFS client utilities from
the operating system's public repositories. For another supported Linux distribution, install the
corresponding packages with its native package manager.

```bash
sudo apt-get update
sudo apt-get install -y curl nfs-common
```

### 4.2 Start and initialize Rancher

Run on the management host:

```bash
sudo install -d -m 0750 /srv/rancher
sudo docker pull "docker.io/rancher/rancher:${RANCHER_VERSION}"

sudo docker run -d \
  --name rancher \
  --restart=unless-stopped \
  --privileged \
  -p 443:443 \
  -v /srv/rancher:/var/lib/rancher \
  -v /srv/rancher-tls/fullchain.pem:/etc/rancher/ssl/cert.pem:ro \
  -v /srv/rancher-tls/privkey.pem:/etc/rancher/ssl/key.pem:ro \
  "docker.io/rancher/rancher:${RANCHER_VERSION}" \
  --no-cacerts
```

`--privileged` is required by Rancher's containerized management cluster. `/srv/rancher` contains
management state and must be included in the site's backup procedure. Use the official Rancher
backup and upgrade procedure for later lifecycle operations.

Wait for startup, then run these read-only checks:

```bash
sudo docker logs --tail 100 rancher
curl -fsS "${RANCHER_URL}/ping"
```

The endpoint must return `pong` without any TLS bypass option.

In a browser:

1. Open the real `RANCHER_URL` and follow Rancher's initial bootstrap-password procedure. Set a
   unique administrator password and store recovery details in the site's approved secret store.
2. Confirm that the Rancher **Server URL** is exactly the stable HTTPS DNS URL used above. Do not use
   a node address, `localhost`, or an address reachable only from the browser.
3. Record the Rancher and k3s pins, certificate owner/expiry, and management-state backup location in
   the site change record.

The full upstream command variants are documented in
[Installing Rancher on a Single Node Using Docker](https://ranchermanager.docs.rancher.com/v2.15/getting-started/installation-and-upgrade/other-installation-methods/rancher-on-a-single-node-with-docker).

## 5. Optional from-zero path: create the downstream k3s cluster

### 5.1 Create the cluster object

In **Rancher → Cluster Management → Create → Custom**, create a Rancher-provisioned k3s cluster with:

| Setting | Required value |
|---|---|
| Cluster name | `nereidai` |
| Kubernetes version | Exactly the reviewed `K3S_VERSION`; `v1.36.2+k3s1` for the documented pin |
| Datastore | Embedded etcd; use three server nodes for HA |
| CNI | Flannel VXLAN, unless the site has reviewed another design and its firewall rules |
| Ingress controller | Traefik, enabled |
| Cloud/provider workloads | None required by this guide |

Keep the default public upstream image coordinates supplied by Rancher and k3s. Configure etcd
snapshots and their protected backup destination according to site policy before production use.
Do not install suite shared components or product applications during cluster creation.

### 5.2 Register nodes

On the cluster's **Registration** tab:

1. Select **etcd**, **control plane**, and **worker** for the first server. Copy the registration
   command generated by Rancher and run it on `server1`. Wait until that machine and the cluster
   become Ready.
2. Generate and run a fresh command with the same roles on `server2`, wait for Ready, and repeat on
   `server3`. Use each command only on its intended host and only while its registration token is
   valid.
3. Add worker-only nodes when additional capacity is required. Select only **worker** in Rancher
   and use a newly generated command for each worker.
4. Use the command exactly as generated for the selected Rancher version. Do not add an insecure TLS
   option or replace the stable Rancher DNS name with an IP address.

Rancher's system agent installs and maintains k3s; do not run a separate k3s installer on these
nodes. The nodes need outbound access to Rancher and the public image sources in §3.3.

If registration stalls, collect only read-only diagnostics on the affected node:

```bash
sudo systemctl status rancher-system-agent --no-pager
sudo journalctl -u rancher-system-agent --since '-15 min' --no-pager
```

Check DNS, certificate trust, time synchronization, token validity, TCP 443 to Rancher, and public
image egress before asking the cluster owner for a new registration command.

When Rancher reports the cluster Active and all machines Ready, download its downstream kubeconfig
and continue with acceptance.

## 6. Read-only acceptance

These checks do not create, patch, delete, drain, upgrade, or restart anything. Run the Kubernetes
commands against the **downstream** cluster from the operator workstation:

```bash
export KUBECONFIG="$HOME/.kube/nereidai.kubeconfig"
kubectl config current-context
```

### 6.1 API, versions, and nodes

```bash
kubectl get --raw='/healthz'
kubectl get --raw='/readyz'
kubectl version --output=yaml
kubectl get nodes -o wide
kubectl get nodes \
  -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\t"}{.status.nodeInfo.kubeletVersion}{"\n"}{end}'
```

Accept only when both API responses are successful, every node reports `True`, and all expected roles
and addresses are present. For a new cluster built with §4–§5, every server version must equal the
selected k3s pin. For an existing cluster, record the actual version and verify its support status;
do not upgrade it during acceptance.

On every downstream node, repeat the external checks:

```bash
RANCHER_HOST=rancher.example.org
RANCHER_URL="https://${RANCHER_HOST}"
NFS_SERVER=nfs.example.org

getent hosts "$RANCHER_HOST" "$NFS_SERVER"
curl -fsS "${RANCHER_URL}/ping"
timedatectl show --property=NTPSynchronized --value
command -v mount.nfs
timeout 5 bash -c "</dev/tcp/${NFS_SERVER}/2049"
```

Expect `pong`, `yes`, a path to `mount.nfs`, and status `0` from the TCP check.

### 6.2 System workloads and Rancher management

```bash
kubectl get pods -A -o wide
kubectl get pods -A \
  --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get deployments -A \
  -o custom-columns='NAMESPACE:.metadata.namespace,NAME:.metadata.name,DESIRED:.spec.replicas,READY:.status.readyReplicas,AVAILABLE:.status.availableReplicas'
kubectl get daemonsets -A
kubectl -n cattle-system get deployments,pods
kubectl -n fleet-system get deployments,pods
```

All long-running pods must be Running and Ready. Completed system jobs are acceptable; Pending,
Failed, crash-looping, or image-pull-failing pods are not. Deployment available replicas must equal
desired replicas, and DaemonSet ready instances must equal desired instances. The Rancher cluster
agent and the agent components installed by the site's Rancher version must be healthy.

In the Rancher UI, confirm once more that the downstream cluster is **Active**, its Machine Inventory
is Ready, and no operation remains in progress.

### 6.3 DNS and ingress readiness

```bash
kubectl -n kube-system get deployments coredns metrics-server traefik
kubectl -n kube-system get service kube-dns traefik
kubectl -n kube-system get endpoints kube-dns
kubectl get ingressclasses
```

CoreDNS, metrics-server, and Traefik must be Available, and `kube-dns` must have ready endpoints.
The `traefik` IngressClass must exist unless the cluster owner has explicitly supplied a suite-
compatible alternative. Record the Traefik service's external address or the address of the external
load balancer that fronts it; future suite DNS records must target that ingress path. An empty
`EXTERNAL-IP` is a handoff blocker until the site's ingress design explains how traffic arrives.

No diagnostic pod is needed for this acceptance. Application-level DNS and HTTPS checks occur after
the shared prerequisites and product ingresses are installed.

### 6.4 Empty-cluster boundary and storage starting point

```bash
kubectl get namespaces
kubectl get storageclasses
```

Verify that there are no NereidAI product namespaces or workloads. The default k3s `local-path`
StorageClass is expected; the suite's `nfs-csi` StorageClass is installed in the next phase rather
than pre-created here. Record the NFS server and export from §3.4 and the successful client/network
checks from §6.1.

Do not create a test namespace, pod, PVC, or Service as part of this acceptance.

## 7. Handoff to suite installation

Record the following in the deployment change record:

- Rancher URL and downstream cluster name;
- actual Rancher and k3s versions;
- node names, roles, and Ready status;
- IngressClass and the external ingress address;
- actual pod/service CIDRs and any site network exceptions;
- NFS server/export and the storage owner's approval;
- kubeconfig owner/location and acceptance output, including any explained exceptions.

Then proceed in this order:

1. **Cluster-shared prerequisites:** follow
   [`../../deploy/prereqs/README.md`](../../deploy/prereqs/README.md) together with
   [`install-suite.md`](install-suite.md) §4. Install and verify cert-manager with `internal-ca`,
   the `nfs-csi` StorageClass, and only the device plugins required by the available hardware.
2. **Suite products:** after all shared-prerequisite checks pass, continue with
   [`install-suite.md`](install-suite.md) §§1–3 for versions and site inputs, then §5 onward for
   product installation.

The cluster owner retains responsibility for Rancher/k3s upgrades, etcd and management-state backups,
node lifecycle, certificate renewal, and capacity changes. Product installation must not silently
change those cluster-level controls.
