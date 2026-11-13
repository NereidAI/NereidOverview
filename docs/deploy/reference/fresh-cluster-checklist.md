# Fresh k3s Cluster Manual Deployment Checklist

> 2026-10-27. Personal checklist for manually deploying a fresh cluster. Ordering
> red line: **cert-manager → NereidIdentity → NereidSphere → NereidLink/NereidHorizon**;
> NereidForge may proceed in parallel but is verified separately; the edge stack goes last.
> The dev password `<dev-password>` must never appear in this environment — generate strong
> passwords on site (`openssl rand -hex 32`) and store them only in a password vault and
> in local values files (never committed to git).

## L0 Host preparation
- [ ] Two (or more) clean Ubuntu hosts; plan hostnames/IPs; time sync between nodes (chrony)
- [ ] Open ports (6443/8472/10250/2379-2381/30000-32767), configure/disable firewalls, disable swap
- [ ] Export the NFS share (`192.0.2.x:/data/nereidai`, `no_root_squash`)
- [ ] Install Docker on the management server (for the Rancher container)
- [ ] Both nodes can pull from Harbor `<harbor-host>` via containerd (registries.yaml + trusted CA)

## L1 k3s + Rancher
- [ ] Start Rancher v2.15.0 in Docker on the management server (offline images; set system-default-registry=<harbor-host>)
- [ ] Rancher first boot (set a strong admin password) → create downstream cluster **nereidai** as Custom (k3s v1.36.2+k3s1)
- [ ] Register 2× servers (control-plane,etcd,worker) and N× workers
- [ ] Verify: nodes Ready, cattle-agent healthy, `crictl images` all come from Harbor
- [ ] Back up the Rancher container data volume

## L2 chartmuseum (optional, air-gapped only)
- [ ] Build host: `helm pull chartmuseum/chartmuseum --version 3.10.3`; image `library/chartmuseum:v0.16.2`
- [ ] Namespace `chartmuseum`; local-path PVC 8Gi pinned to one node; Ingress `<chartmuseum-host>`
- [ ] `/health` returns 200 → push all suite tgz packages → `helm repo add nereidai http://<chartmuseum-host>`
- [ ] Verify index: nereididentity/sphere/link/horizon, nereidforge-*, labelstudio 1.23.0,
      cvat 2.73.0, seaweedfs 4.34, nfs-csi, keycloakx 7.0.1, cloudnative-pg 0.29.0

> When every product repository is cloned locally, L2 is skipped — charts install directly
> from local sibling-repository paths (deploy-standards §15.5). The `nereidai/<chart>` repo form below
> applies only to sites that redistribute via chartmuseum.

## L3 Cluster prerequisites
- [ ] hosts (every node + office workstations): sso / nereidsphere / nereidlink / nereidhorizon / nereidforge /
      labelstudio/cvat/seaweedfs-s3.nereidforge / chart / hub → entry node
- [ ] cert-manager v1.15.3 → selfsigned + Certificate `nereid-internal-ca` + ClusterIssuer **internal-ca**
- [ ] Copy Secret `nereid-internal-ca-tls` from `cert-manager` into every core product namespace
- [ ] nfs-csi v4.7.0 → StorageClass **nfs-csi** (test PVC lands in an NFS subdirectory, then delete it)
- [ ] GPU plugins (as needed: NVIDIA/AMD/Intel + node drivers)
- [ ] Air-gapped only: `harbor-sync.sh node-mirror --apply` on every node and k3s restarted (install-suite §2.4)
- [ ] Create the core namespaces; add a `harbor-registry-secret` per namespace and patch the default SA
      **only when Harbor projects are private** — public projects plus the node mirror need no pull secret
      (install-suite §3.2). Forge namespaces are created by its own scripts

## L4 Core products (strict order)
- [ ] **NereidIdentity** — install from the local chart path with `--skip-crds --timeout 10m`; first ensure
      the CNPG CRDs exist cluster-wide; values require 7 strong secrets (Postgres, master admin,
      service account, 4 client secrets) and `seedUsers=false`; image overrides for Keycloak/CNPG
      are untracked operator site values needed only when the node mirror cannot serve those
      upstream paths (install-suite §6.1, §2.1)
  - If Keycloak 26.1.5 drops the built-in client scopes and the hook reports
    `built-in 'roles' client scope not found`, run the scope-repair workaround in install-suite §6.1,
    then rerun the same Helm command
  - Verify: CNPG healthy; `https://sso.example/auth/realms/nereidai/.well-known/openid-configuration`
    shows the correct issuer; the SA client-credentials flow can call the Admin REST API
- [ ] **NereidSphere** — namespace `nereidsphere`; OIDC issuer=sso, client/admin secrets, 32-byte session
      key, 3 product ssoSecrets, explicit Ingress + `internal-ca` TLS block
  - Single-replica lab: `replicaCount=1`, `valkey.enabled=false`, `tickets.replayStore=memory`;
    multi-replica deployments keep Valkey and set its password/image override
  - Verify: /readyz returns 200; certificate issuer is `CN=nereid-internal-ca`; login through
    NereidIdentity succeeds
- [ ] **NereidHorizon** — namespace `nereidhorizon`; bundled Postgres image override only for
      private/mirrored sites (lab form `<harbor-host>/library/postgres:16-alpine`, untracked site
      value; online sites keep the public coordinate); chart creates no admin user
  - After install, port-forward and call `POST /api/setup`: create admin (**admin / a strong install-time
    password**; `<dev-password>` is dev only) + the Exchange address/root credentials; configure NS SSO there
    or through chart values according to the product documentation
  - Verify: /api/health, setup-status, internal-ca certificate, and (after setup) the Exchange org list

## L5 NereidForge, then NereidLink (strict dependency order)
- [ ] Forge `.env` supplies the registry/site values, strong PG/JWT/Dex secrets, strong
      `SEAWEEDFS_S3_SECRET_KEY` plus its access key, and both SSO secrets; no delivery default passwords
- [ ] Forge order: `10_infra.sh` → `30_install-kubeflow.sh` (longest) → `40_nereidforge.sh` → `60_verify.sh`
- [ ] Verify Forge: workloads Ready in nereidforge + kubeflow/auth/istio-system namespaces; 4 domains
      (forge/LS/CVAT/S3) reachable; /model-registry reachable; Dex login and the real Sphere ticket flow work
- [ ] Save Forge's mode-0600 admin credential, service-token and stage-log hand-off outside Git
- [ ] **NereidLink after Forge** — namespace `nereidlink`; strong Postgres password, the exact Forge S3
      blob keys and endpoint, TimescaleDB/NATS image overrides, and SSO ticket settings
      (nsBaseURL=nereidsphere, clientID=link, CA secret); never create a temporary `emptyDir` backend
  - Run `deploy/kubernetes/scripts/deploy.sh post-deploy`; save the strong admin credential, signed license,
    license status and mode-0600 logs from the gitignored runtime hand-off
  - Verify: /healthz; 31883/31884 reachable; `admin@nereidai.local` login succeeds; license is installed;
    unauthenticated API requests return 401

## L6 Field gateways (not in the cluster)
- [ ] Bring up EdgeX 4.0.2 compose stack (network `edgex_edgex-network`, non-secure mode)
- [ ] NereidInference: `docker compose up -d device-inference`; verify :59992 ping and :28080 preview
- [ ] Create a gateway credential pair in the Link console (one secret per device) → NereidEdge `.env` (chmod 600), 5 values:
  - `NEREID_BROKER_URL=tcp://nereidlink.example:31883` (TLS uses 31884)
  - `NEREID_CRED_ID` / `NEREID_CRED_SECRET`, `NEREID_EDGE_ID`, `NEREID_DEVICE_MAP`
- [ ] Verify: :59750 returns pong; Link shows heartbeats/telemetry; a model bundle dropped into ESS is watched and loaded

## L7 End-to-end + sign-off
- [ ] SSO loop: opening the link domain unauthenticated → redirect to NereidIdentity → back to the product with a session;
      single sign-on into Horizon in the same browser
- [ ] MQTT client completes hello/heartbeat over the NodePort
- [ ] Every domain's certificate chain is internal-ca (import the CA on office workstations)
- [ ] NFS subdirectories are separated per `<ns>-<pvc>`
- [ ] **Password sign-off**: confirm no `changeme*`/default password reached the delivery environment;
      run through the secret-retrieval commands; archive Keycloak master, per-product admin, and
      Postgres passwords in an offline password vault
- [ ] Back up: NereidIdentity Postgres, Link application PVCs (PKI/KEK), chartmuseum PVC, Forge Postgres
