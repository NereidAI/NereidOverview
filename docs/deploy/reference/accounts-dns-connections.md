# Public K3s Accounts, DNS, and Connection Reference

This reference defines values and connection contracts for the public-internet
K3s installation. Use the [suite installation guide](../install-suite.md) as the
command source and the [fresh-cluster checklist](fresh-cluster-checklist.md) as
the acceptance sequence. All commands are executed manually by the operator.

The required order is:

**Shared prerequisites → Identity → Sphere → Horizon → Forge → Link → Open
Horizon edge → separate ESS model delivery**

All `<...>` values are operator inputs. Domains ending in `.example.org` are reserved
examples; replace them consistently in DNS, Ingress, callbacks, certificates, and
client configuration. No real credential appears in this document.

## 1. Shared prerequisites and global contracts

### Public artifacts and secret storage

- Use only chart selectors and image versions whose anonymous public retrieval
  has been verified. Record the artifact reference, resolved chart OCI digest
  and internal version, running image digests, and source revision. A coordinate
  pattern or publication job is not evidence of public availability.
- Keep site values and generated values in untracked
  `<deployment-root>/deploy-values/<product>/` files and the persistent store in
  `<deployment-root>/secret-store/`. Use mode 0700 directories and 0600 files.
  Keep an encrypted off-cluster vault copy and restrict Kubernetes Secret read
  access to authorized operators and workloads.
- Use the suite secret generator for unique database passwords, OIDC client
  secrets, ticket secrets, and session/JWT keys. Supply actual external S3 and
  Open Horizon credentials rather than generating replacements. Use one Link
  gateway credential pair per edge host.
- Never put secret values in Git, documentation, command traces, deployment logs,
  health output, or tickets. Rotate any value that enters one of those locations.
- The suite CA trust key is `ca.crt`. Create `nereid-internal-ca-tls` in each
  consumer namespace from that public certificate only, as shown in the command
  source; never copy the CA `tls.key` outside `cert-manager`. Install the public
  CA in operator and edge trust stores used for suite TLS.

### Cluster and DNS contracts

Install and verify cert-manager, ClusterIssuer `internal-ca`, StorageClass
`nfs-csi`, and required device plugins before any product. Use `<nfs-server>` and
`<nfs-share>` for storage inputs. The ingress class is `traefik`; each product
Ingress requires its own TLS Secret and a Ready certificate.

| Phase | Public example endpoint | TLS / network contract |
|---|---|---|
| Identity | `https://sso.example.org/auth` | TLS Secret `keycloak-tls`; HTTPS 443 |
| Sphere | `https://nereidsphere.example.org` | TLS Secret `nereidsphere-tls`; HTTPS 443 |
| Horizon | `https://nereidhorizon.example.org` | TLS Secret `nereidhorizon-tls`; HTTPS 443 |
| Forge | `https://nereidforge.example.org` | TLS Secret `nereidforge-frontend-tls`; HTTPS 443 |
| Forge integrations | `https://labelstudio.nereidforge.example.org`, `https://cvat.nereidforge.example.org` | Certificate per host; HTTPS 443 |
| Forge model routing | `<model>-<version>.inference.example.org` | DNS wildcard `*.inference.example.org` when enabled by the selected release |
| Link | `https://nereidlink.example.org` | TLS Secret `nereidlink-tls`; HTTPS 443 |
| Link MQTT | `tls://nereidlink.example.org:31884` | MQTT TLS NodePort; Link device-CA chain and Link DNS SAN required |
| Open Horizon edge | No suite Ingress | Outbound Exchange/ESS and Link MQTT connectivity |
| ESS model delivery | `<exchange-url>`, `<ess-url>` | Operator-supplied endpoints and CA trust |

Link's MQTT Service also defines NodePort `31883` for port 1883. Use the TLS
endpoint on `31884` for edge delivery and restrict its network sources to the
intended edge networks.

**Stop condition:** do not continue while public artifacts, DNS, CA trust,
storage, or required hardware resources fail their checks.

## 2. NereidIdentity

| Contract | Value |
|---|---|
| Release / namespace | `nereididentity` / `nereididentity` |
| Realm / issuer | `nereidai` / `https://sso.example.org/auth/realms/nereidai` |
| Discovery | `https://sso.example.org/auth/realms/nereidai/.well-known/openid-configuration` |
| Keycloak Service | `nereididentity-keycloak-http.nereididentity.svc:80` |
| CNPG read-write Service | `keycloak-db-rw.nereididentity.svc:5432` |
| Master-admin Secret | `nereididentity-admin`, keys `KEYCLOAK_ADMIN`, `KEYCLOAK_ADMIN_PASSWORD` |
| Realm/bootstrap Secret | `nereididentity-realm`, including `suite-admin-password` and `admin-client-secret` |
| PostgreSQL bootstrap Secret | `pg-keycloak-credentials`, keys `username`, `password` |

Required values include strong PostgreSQL and master-admin credentials, the
`identity.suiteAdmin` identity fields, `identity.adminClient.secret`, and
`identity.clients.{nereidsphere,nereidhorizon,nereidforge,nereidlink}.secret`.
The suite generator supplies a strong `identity.suiteAdmin.password`; preserve
the same stored value across later renders. The chart retains it in Secret
`nereididentity-realm`, key `suite-admin-password`. Set
`identity.seedUsers=false`. The service-account client ID is
`nereidsphere-admin`; its Secret must match Sphere's admin-client value.

Register only callbacks required by the selected authentication mode:

| Product | Identity callback |
|---|---|
| Sphere | `https://nereidsphere.example.org/auth/callback` |
| Horizon | `https://nereidhorizon.example.org/api/oidc/callback` |
| Forge | `https://nereidforge.example.org/auth/callback` when direct OIDC is enabled |
| Link | `https://nereidlink.example.org/v1/auth/oidc/callback` when direct OIDC is enabled |

Identity does not copy client credentials into product namespaces. Supply each
product's own secret through its untracked values and provide the suite CA where
that product validates Identity TLS.

**Health:** CNPG and Keycloak Ready; bootstrap complete; discovery returns the
external issuer; confidential-client authentication succeeds.

**Stop condition:** an issuer/callback mismatch, failed realm bootstrap, failed
client authentication, or untrusted TLS blocks Sphere installation.

## 3. NereidSphere

| Contract | Value |
|---|---|
| Release / namespace | `nereidsphere` / `nereidsphere` |
| Service | `nereidsphere.nereidsphere.svc:8081` |
| Readiness | `https://nereidsphere.example.org/readyz` |
| OIDC issuer | `https://sso.example.org/auth/realms/nereidai` |
| Admin REST root | `https://sso.example.org/auth/admin/realms/nereidai` |
| Rendered configuration Secret | `nereidsphere-config`, key `config.yaml`, unless `config.existingSecret` is selected |

Set `config.oidc.clientId=nereidsphere`, its Identity client secret, admin client
ID `nereidsphere-admin`, and the matching admin-client secret. Set
`config.oidc.caBundleSecret=nereid-internal-ca-tls` and
`config.session.secretKey` to exactly 32 bytes.

For one replica, use `valkey.enabled=false` and `tickets.replayStore=memory`.
For multiple replicas, enable Valkey, set `valkey.auth.password`, and use its
shared replay store. Ingress is enabled explicitly with its TLS block.

### Sphere ticket and tenant contracts

Each `config.products[]` entry has a unique `ssoSecret` that exactly matches the
corresponding product value:

| Product ID, in installation order | Product base URL | NS callback | Tenant route |
|---|---|---|---|
| `horizon` | `https://nereidhorizon.example.org` | `/auth/ns-callback` | `/v1/integration/ns/tenants` |
| `forge` | `https://nereidforge.example.org` | `/auth/ns-callback` | `/v1/integration/ns/tenants` |
| `link` | `https://nereidlink.example.org` | `/auth/ns-callback` | `/v1/integration/ns/tenants` |

Browser entry is `GET /auth/enter/{product}`. Sphere issues a short-lived,
single-use ticket; the product receives it at its NS callback and its backend
verifies it with `POST {sphere-base-url}/api/v1/auth/ticket/verify`, using headers
`X-NS-Client-Id` and `X-NS-Client-Secret`. Product tenant calls use the configured
route and `X-NS-Integration-Secret`; that integration secret must follow the same
product-specific value rather than being shared across products.

**Health:** rollout and `/readyz` succeed, TLS is trusted, Identity administration
works, and a ticket round trip succeeds.

**Stop condition:** session-key, Valkey/replay-store, ticket-secret, or tenant-route
mismatches block the next product.

## 4. NereidHorizon

With release/fullname `nereidhorizon`, the K3s contracts are:

| Contract | Value |
|---|---|
| Namespace | `nereidhorizon` |
| Frontend / backend Services | `nereidhorizon-frontend.nereidhorizon.svc:80` / `nereidhorizon-backend.nereidhorizon.svc:3001` |
| PostgreSQL Service | `nereidhorizon-postgres.nereidhorizon.svc:5432` |
| Application Secret | `nereidhorizon`, including `session-enc-key`, `postgres-password`, and `database-url` |
| Optional SSO Secret keys | `oidc-client-secret`, `ns-client-secret` when enabled |
| Health / setup status | `/api/health`, `/api/setup-status` on `https://nereidhorizon.example.org` |

Use a strong PostgreSQL password. The chart generates a 64-hex-character session
encryption key on first installation and retains it in the release Secret on
upgrades; archive that Secret securely and never regenerate the key casually.
For Sphere authentication, set `ns.baseUrl=https://nereidsphere.example.org`, product
ID `horizon`, and `ns.clientSecret` to Sphere's `horizon` ticket secret. For direct
Identity authentication, use the Identity issuer, the `nereidhorizon` client, and
callback `/api/oidc/callback`.

The chart does not create the platform administrator or model Exchange/Forge/ESS
settings. Complete `POST /api/setup` once with `<horizon-admin-password>`,
`<exchange-url>`, `<exchange-root-user>`, and `<exchange-root-password>`. Horizon
calls Exchange REST `{exchange-url}/v1/...` with the configured Basic credentials.
Configure `<ess-url>` at runtime as required; ESS delivery remains a separate
final phase.

Horizon's later Forge pull uses runtime settings `forge_base_url`,
`forge_username`, `forge_password`, `forge_namespace`, and `forge_tenant`, with
`/api/v1/auth/login` and `/api/v1/models/.../packages`. Use a dedicated Forge
account and store its password in the vault.

**Health:** backend/frontend Ready, health succeeds, setup-status is complete,
Exchange organizations are readable, and the selected SSO path succeeds.

**Stop condition:** do not start Forge while Horizon setup, Exchange access, or
SSO is unhealthy.

## 5. NereidForge

**Artifact gate:** this reference does not assert that a complete Forge
development snapshot is available. Use the suite guide's ORAS/chart helpers to
record and anonymously verify the complete pre and NF artifact sets, their
resolved immutable versions, and their source commits before starting. Absence
of that verification stops the deployment before Link.

### Accounts and storage

Supply strong values for PostgreSQL administration, JWT signing, Dex, integration
service tokens, and the enabled Identity/Sphere clients. Forge's NS product ID is
`forge`; its NS secret must exactly match Sphere's `forge` entry. Store generated
admin credentials and service tokens only in the approved secret stores.

The first Forge installation establishes the object-store contract consumed by
Link:

| Input | Contract |
|---|---|
| S3 endpoint | `seaweedfs-s3.nereidforge.svc.cluster.local:8333` |
| TLS mode for this in-cluster endpoint | `secure=false` |
| Access key | Exact first-installation `SEAWEEDFS_S3_ACCESS_KEY`, stored as `<forge-s3-access-key>` |
| Secret key | Exact first-installation `SEAWEEDFS_S3_SECRET_KEY`, stored as `<forge-s3-secret-key>` |
| Link bucket | `nereidlink`, created idempotently by Link |

Do not regenerate, rename, or substitute these credentials when installing Link.
Other useful K3s Services are `nereidforge-api.nereidforge.svc:8080`,
`nereidforge-frontend.nereidforge.svc:80`, and
`nereidforge-postgresql-rw.nereidforge.svc:5432`.

**Health:** all selected Forge stages complete; infrastructure, Kubeflow, and
application workloads are Ready; `https://nereidforge.example.org/`, SSO status,
Label Studio, CVAT, and model-registry routes pass; Sphere login and authenticated
S3 access succeed.

**Stop condition:** any failed Forge stage, unhealthy dependency, failed S3 check,
or missing first-installation S3 record blocks Link.

## 6. NereidLink

Link requires Forge SeaweedFS and its exact first-installation credentials on its
first installation. No temporary backend is permitted.

```yaml
blob:
  endpoint: "seaweedfs-s3.nereidforge.svc.cluster.local:8333"
  bucket: "nereidlink"
  accessKey: "<forge-s3-access-key>"
  secretKey: "<forge-s3-secret-key>"
  secure: false
sso:
  enabled: true
  nsBaseURL: "https://nereidsphere.example.org"
  clientID: "link"
  ssoSecret: "<sphere-link-sso-secret>"
  callbackPath: "/auth/ns-callback"
  caBundleSecret: "nereid-internal-ca-tls"
  caBundleKey: "ca.crt"
```

Also supply strong PostgreSQL and JWT secrets. `sso.enabled` and direct
`oidc.enabled` are mutually exclusive; configure only the selected mode. The
chart's `<release>-config-secret` contains sensitive configuration in
`90-secret.yaml`; restrict access to it.

| Contract | Value |
|---|---|
| Release / namespace | `nereidlink` / `nereidlink` |
| HTTP / in-cluster MQTT Service | `nereidlink.nereidlink.svc:8080` / `:1883` |
| Bundled PostgreSQL / NATS | `nereidlink-postgresql.nereidlink.svc:5432` / `nereidlink-nats.nereidlink.svc:4222` |
| HTTPS health | `https://nereidlink.example.org/healthz` |
| MQTT Service | `nereidlink-mqtt`; NodePorts `31883` → 1883 and `31884` → 8883 |
| Edge topic family | `v1/gateway/*` |
| Initial account | `<link-admin-email>` with a strong first-run password stored in the vault |

NereidEdge initiates the northbound connection to Link; Link has no outbound edge
address to configure. Complete the documented first-run account bootstrap without
printing the generated credential.

Link's init containers create a Link-owned device CA at
`/var/lib/nereidlink/pki/ca.pem` and sign the MQTT server leaf from
`pki.serverHosts`. Export only that public CA certificate as shown in the command
source; never export `ca-key.pem` or `server-key.pem`. The suite CA remains the
trust anchor for Link HTTPS and Sphere/OIDC calls, not for this MQTT leaf.
Preserve and securely back up the Link data PVC to avoid losing the device CA.

**Health:** rollout and `/healthz` succeed; logs and bucket state prove access to
Forge SeaweedFS and idempotent creation of `nereidlink`; protected APIs reject
unauthenticated requests; MQTT TLS validates against Link's public device CA and
the Link DNS SAN.

**Stop condition:** any other blob backend, failed bucket access, incomplete admin
bootstrap, or failed API/MQTT security check blocks edge onboarding.

## 7. Open Horizon edge connections

Perform manual registration, Pattern/agreement delivery, and NereidEdge-to-Link
configuration in that order for each edge host.

### Registration and Pattern delivery

Registration inputs are `<exchange-url>`, `<exchange-org>`, `<edge-node-id>`, and
the generated registration credential. Deliver the selected
`<edge-pattern>` containing the NereidEdge and NereidInference service definitions.
Record its exact version and verify the node, agreement, and service-container
health before configuring northbound traffic. Pattern delivery does not include or
prove ESS model delivery.

### NereidEdge-to-Link values

| Variable | Operator value / contract |
|---|---|
| `NEREID_BROKER_URL` | `tls://nereidlink.example.org:31884` after site DNS replacement |
| `NEREID_ROOT_CA_FILE` | In-container path to a read-only mount of Link's exported public `ca.pem`; do not use the suite CA or disable verification |
| `NEREID_CRED_ID` | Unique `<edge-credential-id>` created in the Link console |
| `NEREID_CRED_SECRET` | Matching `<edge-credential-secret>`; never shared between hosts |
| `NEREID_EDGE_ID` | `<edge-id>` matching the intended Link identity |
| `NEREID_DEVICE_MAP` | `<device-map>` for that host's approved devices |

Keep the generated edge configuration at mode 0600. NereidEdge connects only to
Link over the `v1/gateway/*` topic family; it has no direct Identity, Sphere,
Forge, Horizon, or ESS connection.

**Health:** `GET http://<edge-host>:59750/api/v4/ping` returns pong, Open Horizon
agreement and service containers are healthy, MQTT authentication succeeds, and
Link shows heartbeats/telemetry for the expected edge and devices.

**Stop condition:** registration, agreement, container health, MQTT trust,
credential uniqueness, or telemetry identity failures block model delivery.

## 8. Separate ESS model delivery

Model delivery starts only after the edge health gate passes:

1. Horizon authenticates to Forge through `/api/v1/auth/login` and pulls the
   selected package through `/api/v1/models/.../packages` using its dedicated
   runtime Forge account.
2. The operator delivers one model at a time through ESS to the intended edge
   policy. The package contract is `nereid-model/1` with root `nereid-model.json`.
3. Open Horizon synchronizes the ESS object to the edge. NereidInference watches
   the ESS landing location `/var/horizon/ess-store/sync/local`; NereidEdge does
   not consume model packages.
4. The operator verifies ESS object status, edge receipt, package validation,
   NereidInference model-load status, and a real inference request.

**Health:** the exact model/package version reaches only the intended edge and
passes inference. Record the ESS object identity and edge/model evidence.

**Stop condition:** an agreement without a received model is not acceptance. ESS
synchronization, package validation, model loading, or inference failure keeps
that model delivery open and must be resolved independently.
