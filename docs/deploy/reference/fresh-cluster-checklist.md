# Public Internet K3s Fresh-Cluster Checklist

Use the [manual suite installation guide](../install-suite.md), the optional
[resumable quick installer](../quick-install.md), or an equivalent independent
procedure as the command source, together with the
[accounts, DNS, and connections reference](accounts-dns-connections.md) for value
names and endpoints. The operator remains responsible for every command and
acceptance result, including those performed by automation.

Follow this order without overlap or substitution:

**Shared prerequisites → Identity → Sphere → Horizon → Forge → Link → Open
Horizon edge → separate ESS model delivery**

Stop at the first failed gate. Do not install a downstream product to bypass a
failed dependency. Replace placeholders such as `<chart-version>` in the
operator's untracked values and replace every reserved `.example.org` name with the
site's real DNS name.

## 1. Shared prerequisites

- [ ] Record the selected public artifact references and source revisions. For
      each floating `0.0.0-dev` chart, also record its resolved OCI digest and
      internal `0.0.0-dev-<short-sha>` version; after installation, record the
      running image IDs/digests. Confirm anonymous public retrieval for every
      selected artifact before using it; a naming pattern does not prove
      availability.
- [ ] Confirm the operator host and every K3s node have working DNS and HTTPS
      access to all referenced public artifact locations.
- [ ] Confirm K3s nodes are Ready, `kubectl` targets the intended cluster, Helm
      is available, time is synchronized, and the ingress and storage networks
      are reachable.
- [ ] Keep site values and generated values under the untracked
      `<deployment-root>/deploy-values/<product>/` directories and the persistent
      store under `<deployment-root>/secret-store/`. Use mode 0700 for private
      directories and 0600 for files, disable shell tracing, and keep encrypted
      off-cluster vault copies. Never place real values in documentation, Git,
      logs, or acceptance output.
- [ ] For the manual path, run `scripts/generate-suite-secrets.py init` once and
      render each product's `values.generated.yaml` from its non-secret
      `site-values.yaml`; the quick runner performs these steps from its one
      non-secret environment file. Confirm repeated initialization/rendering
      preserves existing secrets. Supply external systems' actual credentials
      separately; never generate a replacement Forge S3 credential. Generate a
      separate Link gateway credential pair per edge host.
- [ ] Create DNS records for `sso.example.org`, `nereidsphere.example.org`,
      `nereidhorizon.example.org`, `nereidforge.example.org`, and `nereidlink.example.org`,
      plus the Forge service names and inference wildcard required by the
      selected release. Point them at the intended ingress address.
- [ ] Install and verify the shared prerequisites from the command source:
      cert-manager, the Ready `internal-ca` ClusterIssuer, the `nfs-csi`
      StorageClass using `<nfs-server>` and `<nfs-share>`, and only the device
      plugins required by the available hardware.
- [ ] Create `nereid-internal-ca-tls` in product namespaces from only the public
      `ca.crt`; never copy the CA `tls.key` outside `cert-manager`. Configure the
      operator and edge trust stores with that certificate. Confirm a test PVC
      becomes Bound and mounts successfully, then remove the test resources.
- [ ] Confirm Traefik serves HTTPS and that required cluster certificates are
      Ready before installing a product.

**Stop if** a selected public artifact cannot be retrieved, storage is not writable,
required hardware resources are absent, or the CA/StorageClass is not Ready.

## 2. NereidIdentity

- [ ] Install release `nereididentity` in namespace `nereididentity` using the
      selected public artifact and values procedure in the command source. Ensure
      the CNPG CRDs are present before installation.
- [ ] Confirm the generator supplied strong PostgreSQL, Keycloak master-admin,
      suite-admin, and `nereidsphere-admin` credentials, plus distinct client
      secrets for Sphere, Horizon, Forge, and Link. Set the suite-admin identity
      fields, preserve the secret store for subsequent renders, and set
      `identity.seedUsers=false`.
- [ ] Use realm `nereidai` and external issuer
      `https://sso.example.org/auth/realms/nereidai`. Register only the callbacks for
      the selected product authentication modes listed in the connection
      reference.
- [ ] Verify the CNPG cluster and Keycloak pods are Ready, realm import/bootstrap
      completes, and
      `https://sso.example.org/auth/realms/nereidai/.well-known/openid-configuration`
      returns the same external issuer.
- [ ] Verify a confidential-client authentication flow and the certificate chain.
      Store the bootstrap credentials in the encrypted vault.

**Stop if** discovery reports another issuer, bootstrap is incomplete, a client
secret does not authenticate, or the certificate is not trusted.

## 3. NereidSphere

- [ ] Install release `nereidsphere` in namespace `nereidsphere` with Ingress and
      TLS explicitly enabled for `https://nereidsphere.example.org`.
- [ ] Set the Identity issuer, `nereidsphere` client secret, and
      `nereidsphere-admin` secret to the values created in Identity. Set
      `config.session.secretKey` to exactly 32 bytes.
- [ ] Generate distinct `config.products[].ssoSecret` values for Horizon, Forge,
      and Link. Record them for their later installations; never reuse one
      product's ticket secret for another.
- [ ] For one replica, set `valkey.enabled=false` and
      `tickets.replayStore=memory`. For multiple replicas, keep Valkey enabled,
      supply its strong password, and use its shared replay store.
- [ ] Verify Deployment rollout, `https://nereidsphere.example.org/readyz`, trusted
      TLS, Identity login, and ticket verification. Confirm the product catalog
      contains only the intended Horizon, Forge, and Link entries.

**Stop if** readiness fails, the session key length is wrong, Identity administration
fails, or a ticket cannot be verified.

## 4. NereidHorizon

- [ ] Install release `nereidhorizon` in namespace `nereidhorizon` with a strong
      PostgreSQL password and the selected Identity and/or Sphere credentials.
      Confirm the chart-generated session encryption key is retained across an
      upgrade and archive the release Secret securely.
- [ ] Expose `https://nereidhorizon.example.org` with TLS. Complete the one-time
      `POST /api/setup` flow using `<horizon-admin-password>`, the Open Horizon
      `<exchange-url>`, and `<exchange-root-user>` / `<exchange-root-password>`.
      Do not rerun setup against an initialized system.
- [ ] Configure the ESS base URL and runtime organization settings required by
      the selected release. This configuration does not deliver a model.
- [ ] Verify the frontend and backend roll out,
      `https://nereidhorizon.example.org/api/health` succeeds, setup-status reports
      initialization complete, and the Exchange organization list can be read.
- [ ] Verify the selected Identity or Sphere login path and trusted TLS. Store
      the Horizon and Exchange credentials in the encrypted vault.

**Stop if** setup is incomplete, Exchange authentication or organization access
fails, or health and SSO checks do not pass.

## 5. NereidForge

**Independent stop points:** pre-only installation and NF application
installation have separate artifact requirements.

- [ ] **Pre artifact gate:** use `PRE_VERSION=0.0.0-dev` from the persistent
      operator environment. Confirm the pre installer plus five supporting
      charts passed anonymous publication verification, and record the resolved
      `0.0.0-dev-<short-sha>` version, OCI digest, and source commit. This alone
      permits §7.2.
- [ ] Follow the [suite installation guide §7](../install-suite.md#71-development-artifact-gate)
      through its ordered infrastructure, Kubeflow, and pre verification stages.
- [ ] **NF artifact gate:** before §§7.3–7.5, use
      `NEREIDFORGE_VERSION=0.0.0-dev` and confirm the selected `publish-dev`
      profile passed anonymous verification: 23 images for `full`, or 18
      core/CPU/Intel-XPU images for `cpu-xpu`, plus exactly three NF charts.
      Record the profile, independent resolved version, digests, and source
      commit. **Stop after pre acceptance if that evidence is absent.** Then
      confirm the three
      application charts and verification stages individually;
      `nereidforge-tenant-check` remains verification-only.
- [ ] Supply the Forge domains, storage settings, strong PostgreSQL/JWT/Dex
      secrets, service-integration tokens, the Identity `nereidforge` client
      secret when used, and an NS ticket secret exactly matching Sphere's
      `forge` entry.
- [ ] Generate the first-installation `SEAWEEDFS_S3_ACCESS_KEY` and strong
      `SEAWEEDFS_S3_SECRET_KEY`. Record them exactly, together with endpoint
      `seaweedfs-s3.nereidforge.svc.cluster.local:8333` and `secure=false`, in
      the encrypted vault for Link. Do not regenerate or substitute them.
- [ ] Verify Forge infrastructure, Kubeflow integration, application workloads,
      and model-registry dependencies are Ready. Verify
      `https://nereidforge.example.org/`, its SSO status, Label Studio, CVAT, and the
      model-registry route respond as documented.
- [ ] Test authenticated S3 access with the recorded first-installation
      credentials and verify Forge login plus the real Sphere ticket flow.

**Stop if** any Forge stage or workload is unhealthy, S3 authentication fails, or
the exact first-installation endpoint and credentials are not recorded.

## 6. NereidLink

- [ ] Confirm every Forge gate is green before installing Link. Link must use
      Forge SeaweedFS from its **first installation**; no temporary backend is
      permitted.
- [ ] Set `blob.endpoint` to
      `seaweedfs-s3.nereidforge.svc.cluster.local:8333`, `blob.bucket` to
      `nereidlink`, `blob.secure=false`, and `blob.accessKey` / `blob.secretKey`
      to the exact first-installation Forge credentials.
- [ ] Supply strong PostgreSQL and JWT secrets. For Sphere ticket authentication,
      set `sso.nsBaseURL=https://nereidsphere.example.org`, `sso.clientID=link`, the
      matching Sphere `link` secret, callback `/auth/ns-callback`, and the
      `nereid-internal-ca-tls` / `ca.crt` trust reference.
- [ ] Install release `nereidlink` in namespace `nereidlink`, expose
      `https://nereidlink.example.org` with TLS, and complete the first-run admin
      bootstrap through the one-time loopback API (the quick installer's `link`
      stage does this automatically). Store the retained mode-`0600`
      `admin-credentials.env` password in the encrypted vault; an admin already
      initialized out of band must not be reset.
- [ ] Verify rollout and `https://nereidlink.example.org/healthz`. Confirm startup
      authenticates to Forge SeaweedFS and creates the `nereidlink` bucket
      idempotently; inspect logs and bucket state rather than assuming success.
- [ ] Confirm `nereidlink-mqtt` exposes the selected MQTT NodePorts (`31883` and
      `31884`), TLS port `31884` presents a certificate chaining to Link's own
      device CA with the Link DNS name in its SAN, and protected API requests
      reject unauthenticated calls. Export only the public
      `/var/lib/nereidlink/pki/ca.pem` for edge trust; never export the CA or
      server private keys.

**Stop if** Link is not using Forge SeaweedFS, bucket access fails, admin bootstrap
is incomplete, or HTTPS/MQTT authentication and authorization checks fail.

## 7. Open Horizon edge onboarding

Perform these steps manually for each edge host after Link is healthy:

- [ ] Register the host with Open Horizon using `<exchange-url>`, the intended
      organization, `<edge-node-id>`, and its generated registration inputs.
      Verify the node is registered before delivering services.
- [ ] Deliver the selected NereidEdge/NereidInference service Pattern. Wait for
      the agreement and all service containers to become healthy.
- [ ] Create one credential pair for this host in the Link console and configure
      NereidEdge with `NEREID_BROKER_URL=tls://nereidlink.example.org:31884`,
      `NEREID_CRED_ID`, `NEREID_CRED_SECRET`, `NEREID_EDGE_ID`, and
      `NEREID_DEVICE_MAP`. Mount Link's exported public device CA read-only and
      set `NEREID_ROOT_CA_FILE` to its in-container path; do not substitute the
      suite CA or disable verification. Keep the configuration at mode 0600 and
      never share a credential pair between hosts.
- [ ] Verify `http://<edge-host>:59750/api/v4/ping` returns pong, the configured
      MQTT connection authenticates, and Link receives heartbeats and telemetry
      from the expected edge ID and devices.

**Stop if** registration or agreement formation fails, a service is unhealthy, the
MQTT CA/credentials are rejected, or Link attributes traffic to the wrong edge.

## 8. Separate ESS model delivery

- [ ] Only after edge onboarding is green, configure Horizon's runtime Forge
      connection with `<forge-base-url>`, its dedicated credentials, namespace,
      and tenant. Select a verified model package with root `nereid-model.json`.
- [ ] Deliver each model as a separate ESS operation to the intended edge policy.
      Do not treat Pattern delivery or an Open Horizon agreement as evidence of
      model delivery.
- [ ] Verify ESS object status and receipt under the edge ESS sync location,
      NereidInference's acceptance and model-load state, and a successful inference
      request using the selected model.
- [ ] Record the model/package version, target edge, ESS object identity, health
      evidence, and exact product versions in the installation record. Confirm
      all credentials remain only in their approved secret stores.

**Stop if** ESS receipt, package validation, model loading, or inference fails;
resolve that delivery independently before signing off the model.
