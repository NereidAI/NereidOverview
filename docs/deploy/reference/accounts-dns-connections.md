# NereidAI Suite Deployment Reference: Default Credentials · DNS/Ingress · Inter-product Connections

Status: **first version 2026-10-27, inventoried from product-repository source/config/charts (not
yet re-verified item by item on the live cluster)**. When this file disagrees with the live system,
the live `kubectl get` / actual `.env` wins; correct this file afterwards.

Applies to: NereidIdentity, NereidSphere, NereidLink, NereidHorizon, NereidForge, NereidEdge,
NereidInference. NereidFleet and NereidMobile are still in design and their entries are **TBD**;
NereidRobot is a planned product with no repository.

## 0. Secrets and password policy (read first)

- This file **records no real password/token value**. Real secrets of lab/customer environments are
  documented only by **storage location and retrieval command**.
- The passwords in the "DEV default" subsections below are the **actual built-in values found in
  product-repository source** at inventory time (2026-10-27); they are for local development/POC
  only and **must never be used in a k3s/delivery deployment**. Per the §1.1 standard they are being
  unified to dev `<dev-password>`; mismatches between inventory and standard are in the §1.4 remediation list.
- In k3s mode every password is injected at install time or randomly generated on first chart
  install; retrieve them uniformly with the `kubectl` commands in §4.
- The lab Harbor admin password for `<harbor-host>` is **never committed**; obtain it offline when needed.
- Default accounts must have forced password changes after deployment; bootstrap accounts created on
  first product start (empty-password guidance) must be closed out in the delivery checklist.

## 1. Suite-wide standards (mandatory baseline)

> Defined 2026-10-27. **Every product (including third-party components) and every delivery form
> must comply.** Deviations in existing repositories are listed in the §1.4 remediation table and are
> aligned by each product owner (NereidOverview only defines the standard; it does not modify sibling
> repositories).

### 1.1 Accounts and passwords

| Rule | Content |
|---|---|
| Login username | Built-in/initial accounts for human login use exactly **`admin`** (plain-username systems: Keycloak master, Label Studio, CVAT, Dex, Grafana, etc.) or **`admin@nereidai.local`** (email systems: Link, Forge, etc.); one component picks one form only. Email addresses uniformly use `@nereidai.local`; product domains such as `@nereidforge.local` / `@nereidlink.local` are **forbidden**. |
| DEV password | The default password for development/CI/POC is uniformly **`<dev-password>`** (used by every product's dev compose, seed scripts, and third-party dev instances; development only). |
| k3s/delivery password | Always **explicitly configured at install time or randomly generated on first install** (chart `required` or a generated hook value); no hardcoded default may flow out; force password set/change on first login after install; every `changeme*`, `admin`, `nereidpass` default must be overridden before delivery. |
| Technical accounts | Database roles (`keycloak`/`nereidlink`/`nereidforge`/`nereid`), MQTT gateway credentials (`gw-*_token`), OIDC client_id (`nereid*`), S3 access keys and other **program accounts keep semantic names** and need not be called admin; but their **dev password is likewise uniformly `<dev-password>`**, and k3s installs set strong passwords. |
| Third-party components | Bootstrap accounts for LS, CVAT, Kubeflow Dex, Grafana, Keycloak follow the same rule: dev `admin/<dev-password>`, strong password set at k3s install; email-type accounts uniformly use `admin@nereidai.local`. |
| Edge side | NereidEdge/Inference have no login accounts; MQTT gateway credentials use one secret per device, created in the Link console and written into the gateway `.env` (gitignored, never committed). |

### 1.2 DNS / Ingress naming

| Category | Domain | Notes |
|---|---|---|
| Identity | `sso.example` (`/auth`) | **Sole historical exception**: decided 2026-10-27 to keep it; no second exception may be added |
| Core products | `nereidsphere.example`, `nereidlink.example`, `nereidhorizon.example`, `nereidforge.example` | Pattern `nereid<product>.example`; new products follow it (planned `nereidfleet.example`) |
| Third-party components | `labelstudio.nereidforge.example`, `cvat.nereidforge.example` | Pattern `<thirdparty>.nereid<product>.example` (hung off the owning product's subdomain); live also has `seaweedfs-s3.nereidforge.example` |
| Model routing | `*.<model-type>-<version>.inference.example` | Knative InferenceService exposed via a Traefik IngressRoute; plan DNS and certificates around the wildcard `*.inference.example` |
| Infrastructure (exempt) | `<harbor-host>` (Harbor), `<chartmuseum-host>` (ChartMuseum) | Not products; the nereid* rule does not apply |
| Edge | no ingress | NE/NI only make outbound connections (MQTT/ESS); preview/DS API is LAN-reachable only |

Common rules: ① ingress class is fixed to `traefik`; ② TLS is always issued by
`cert-manager.io/cluster-issuer: internal-ca` (ChartMuseum may run plain HTTP
as a trusted-intranet-only temporary form; formalization adds TLS+authentication); ③ in an example
lab, hosts files point at the entry node (192.0.2.10), and this moves transparently once internal
DNS exists; ④ each product
gets its own TLS Secret (`<product>-tls`).

### 1.3 Deployment form: everything installed manually

Every layer is **installed manually in steps with human confirmation** per the runbooks; no
GitOps/operator auto-management is introduced (edge model distribution is the exception — that is
Horizon's business capability, not a cluster-bootstrap mechanism). Standard path and documents:

| Layer | Content | Authoritative guide |
|---|---|---|
| L0 | Host OS, network, NFS, Docker (management server) | [`cluster-bootstrap.md`](../cluster-bootstrap.md) §3 |
| L1 | Rancher management plane (manual Docker bootstrap), downstream k3s cluster (Custom registration) | same guide §4–§6 |
| L2 | chartmuseum (cluster-self-hosted chart repository) | [`install-suite.md`](../install-suite.md) §9 (optional, air-gapped only) |
| L3 | cert-manager/internal-ca, csi-driver-nfs, GPU device plugins, Harbor credentials/namespaces/helm repo | [`install-suite.md`](../install-suite.md) prerequisites section + [`deploy/prereqs/`](../../../deploy/prereqs/README.md) |
| L4 | NereidIdentity → NereidSphere → NereidLink → NereidHorizon | [`install-suite.md`](../install-suite.md) product section |
| L5 | NereidForge heavy stack (infra + Kubeflow + business layer, run manually via the product repo scripts) | NereidForge product repository |
| L6 | Field gateways: EdgeX 4.0.2 + NereidInference + NereidEdge (manual compose) | Product repositories |
| L7 | End-to-end verification and delivery sign-off (incl. default-password remediation) | [fresh-cluster-checklist.md](fresh-cluster-checklist.md) |

### 1.4 Existing deviations and remediation list (cross-repo tasks)

Inventory date 2026-10-27. The table below shows the gap between current product-repo dev defaults
and this standard. NereidOverview only records and hands over prompts/patches; it does not edit
sibling repositories directly. Update the table after remediation lands.

| Component | Current dev default | Target (§1.1) | Owning repo |
|---|---|---|---|
| Keycloak NI compose | master `admin/admin`; PG `keycloak/keycloak`; client secrets `changeme*` | `admin/<dev-password>`; PG dev password `<dev-password>`; `changeme*` may stay (dev placeholders; mandatory install-time override already guaranteed) | NereidIdentity |
| NereidSphere dev.yaml | local users `admin/admin`, `user/user` | `admin/<dev-password>` (unifying the user system to `admin@nereidai.local` is better; left to product discretion) | NereidSphere |
| NereidLink dev seed | `admin@nereidai.local / <dev-password>`; PG `nereidlink/nereidlink` | password to `<dev-password>`; PG dev password `<dev-password>`; first-boot bootstrap mailbox already compliant | NereidLink |
| NereidHorizon dev | Setup wizard has no default (≥8 chars); PG `nereid/nereidpass` | unify docs/examples to `admin/<dev-password>`; PG dev password `<dev-password>` | NereidHorizon |
| NereidForge | `admin/<dev-password>` ✓; but mailbox `admin@nereidforge.local`; PG/S3 `nereidforge/nereidforge`; Grafana `admin/admin` | mailbox to `admin@nereidai.local`; unify dev DB/S3/Grafana passwords to `<dev-password>` | NereidForge |
| Label Studio / CVAT (Forge bootstrap) | `admin/<dev-password>` ✓; mailbox `admin@nereidforge.local` | mailbox to `admin@nereidai.local` | NereidForge (`10_infra/bootstrap-tokens.sh`) |
| Kubeflow Dex | `admin@nereidforge.local / <dev-password>` | mailbox to `admin@nereidai.local` (Secret `auth/dex-passwords` + config-map) | NereidForge |
| Grafana (Forge dev compose) | `admin/admin` | `admin/<dev-password>` | NereidForge |
| NereidFleet / NereidMobile | no code | implement to this standard from project inception | NereidFleet / NereidMobile |

## 2. Quick-reference table

| Product | k3s namespace | External ingress (lab domain → 192.0.2.10) | In-cluster Service FQDN (port) | DEV listener | DEV default login |
|---|---|---|---|---|---|
| NereidIdentity (Keycloak 26) | `nereididentity` | `https://sso.example/auth` | `nereididentity-keycloak-http.nereididentity.svc:80`; CNPG `keycloak-db-rw:5432` | `http://localhost:8090` (**no /auth**) | master `admin/admin`; realm users `admin/admin`, `user/user` |
| NereidSphere | `nereidsphere` | `https://nereidsphere.example` (**disabled by chart default**, must be enabled explicitly) | `nereidsphere.nereidsphere.svc:8081` | backend `:8081`; Vite `:5174` | local mode `admin/admin`, `user/user` |
| NereidLink | `nereidlink` (lab all-in-one uses `nereidai`) | `https://nereidlink.example`; MQTT NodePort **31883/31884** | `nereidlink.nereidlink.svc:8080`(HTTP) `:1883`(MQTT); `-postgresql:5432`; `-nats:4222` | backend `:8080`; Vite `:5173`; MQTT `1883/8883`; gRPC `19090`; ops `19190` | first-boot bootstrap empty password; seed `admin@nereidai.local / <dev-password>` (`nereidlink seed` only) |
| NereidHorizon | `nereidhorizon` | `https://nereidhorizon.example` | `<release>-frontend:80`; `<release>-backend:3001`; `<release>-postgres:5432` | BFF `:3001`; Vite `:8080`; PG host port `5433` | **no default**: first-boot Web Setup (`POST /api/setup`) creates the admin; dev PG `nereid/nereidpass` |
| NereidForge | `nereidforge` (plus `kubeflow`/`auth`/`istio-system`/`default`) | `https://nereidforge.example`; `labelstudio.nereidforge.example`; `cvat.nereidforge.example`; model routing `*.<model>-<ver>.inference.example` | `nereidforge-api:8080`, `nereidforge-frontend:80`, `labelstudio:8080`, `cvat-backend-service:8080`, `seaweedfs-s3:8333/9000`, `valkey-master:6379`, `nereidforge-postgresql-rw:5432` | API `:8080`; Vite `:5173`; compose PG `5432`; S3 `8333` (host 18080→8080 volume etc.) | `admin / <dev-password>` (mailbox `admin@nereidforge.local`); LS/CVAT/Dex same password; dev PG `nereidforge/nereidforge`; Grafana `admin/admin` |
| NereidInference | **not in the cluster**: delivered to field gateways via Open Horizon | none (edge side) | inside the edge Docker network `edgex_edgex-network`: `edgex-device-inference:59992` | DS API `:59992`; MJPEG preview container `18080` (host `28080`) | none (EdgeX non-secure mode); OpenAI-backend bearer taken from EdgeX secret `api_key` |
| NereidEdge | **not in the cluster**: edge-gateway compose/ESS | none (active outbound MQTT only) | inside the edge network: `nereid-edge` itself `59750`; EdgeX core 59880/59881/59882/59890 | health check `:59750/api/v4/ping` | no own account; northbound uses the NereidLink gateway credential pair (`.env`, see §3.7) |
| NereidFleet | TBD (design docs only, no code/chart) | planned `nereidfleet.example` | TBD | TBD | TBD |
| NereidMobile | client only, no server-side deployment | N/A | N/A | Flutter / WeChat DevTools | no own account; logs in via NereidIdentity |

> The realm name is fixed to **`nereidai`**; it is a different concept from the namespace — do not
> conflate them.
> Lab domains are resolved via hosts files on each node/office machine for now; internal DNS comes
> later. Wildcards needed: `*.nereidforge.example`, `*.inference.example`.

---

## 3. Per-product detail

### 3.1 NereidIdentity (Keycloak 26 + CNPG PostgreSQL)

#### DEV mode (`deploy/compose/docker-compose.yml`)
- Credentials:
  - Master console: `admin / admin` (`KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`, both default
    `admin`, see compose and `.env.example`).
  - Realm `nereidai` seed users: `admin/admin` (roles admin,user; mailbox `admin@nereidai.local`)
    and `user/user`; from `realm/nereidai-realm.json`.
  - PostgreSQL: db/user/password = `keycloak/keycloak/keycloak` (inside the container; port not exposed).
  - Client secrets (built into the dev realm JSON, development only):
    `nereidsphere=changeme`, `nereidlink=changeme-link`, `nereidhorizon=changeme-horizon`,
    `nereidforge=changeme-forge`, service account `nereidsphere-admin=changeme-admin`.
- DNS/ports:
  - Host `http://localhost:8090` (`KC_HOST_PORT=8090`) → container 8080; **dev has no `/auth` context**.
  - In-compose DNS: `keycloak:8080`, `keycloak-db:5432`; network `ni-net`.
  - Issuer: `http://localhost:8090/realms/nereidai`.
  - Dev callbacks registered in the realm: Sphere `localhost:8081|5173 /auth/callback`; Link
    `localhost:8080/v1/auth/oidc/callback`, `5173`; Horizon `3001|5174`; Forge `8082|5175`.
- Connections: depended on as the OIDC issuer by every product; the one-time bootstrap Job calls
  the Admin REST in client-credentials mode with `nereidsphere-admin`.

#### K3S mode (umbrella chart `deploy/helm/nereididentity`; release/ns must both be `nereididentity`)
- Credentials (all injected at install time or randomly generated; **values do not go in this file**):
  - Master admin: values `identity.admin.username/password` → Secret `nereididentity-admin`, keys
    `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD` (password is `required`; rendering fails without it).
  - Suite admin: `identity.suiteAdmin.*` (default user `admin`); if the password is left empty a
    random 32-char value is generated on first install into Secret `nereididentity-realm`, key
    `suite-admin-password`; not rotated on upgrade.
  - `nereidsphere-admin` SA: Secret `nereididentity-realm`, key `admin-client-secret`.
  - Four product OIDC client secrets: values `identity.clients.<product>.secret` (`required`).
  - PG: CNPG bootstrap Secret `pg-keycloak-credentials` (`username/password`, owner=keycloak).
  - Realm seed-user switch `identity.seedUsers` defaults to **false**; it must never be enabled in a central deployment.
- DNS/ports:
  - Ingress `sso.example`, `/auth/` Prefix, TLS Secret `keycloak-tls`, issuer `internal-ca`.
  - Context path `/auth`; external issuer: `https://sso.example/auth/realms/nereidai`.
  - Service `nereididentity-keycloak-http`: 80 / 9000(management) / 8443; StatefulSet
    `nereididentity-keycloak`.
  - CNPG: `keycloak-db-rw` / `-r` / `-ro`, port 5432; PVC via `nfs-csi` (8Gi).
  - Declarative realm import: Secret `nereididentity-realm`, key `nereidai-realm.json`;
    post-install/post-upgrade Hook Job `nereididentity-bootstrap`.
  - 2026-10-29 live defect: Keycloak 26.1.5 can import the realm without the built-in
    `roles`/`profile`/`email`/`web-origins` client scopes; the workaround is in
    install-suite §6.1 and the chart fix belongs to NereidIdentity.
  - Production callbacks (rendered in the realm): `https://nereidsphere.example/auth/callback`,
    `https://nereidlink.example/v1/auth/oidc/callback`(+`/auth/callback`),
    `https://nereidhorizon.example/auth/callback`,
    `https://nereidforge.example/auth/callback`.
- Connections: NI does not push secrets into product namespaces; each product keeps its own client
  secret. In-cluster trust is solved by copying the `internal-ca` CA (Secret key `ca.crt`).

### 3.2 NereidSphere (Go + embedded React SPA)

#### DEV mode (`make dev` → `go run ./cmd/sphere serve -c configs/dev.yaml`)
- Credentials:
  - dev default `auth.mode=local`: local bcrypt users `admin/admin`, `user/user` (`configs/dev.yaml`).
  - OIDC block (takes effect only when mode is switched): client `nereidsphere` / secret
    `changeme`; admin SA `nereidsphere-admin` / `changeme-admin`.
  - Product SSO secret defaults: `changeme-link / changeme-horizon / changeme-forge` (non-production code defaults).
  - The dev session sealing key is hardcoded in `configs/dev.yaml` (dev only); cookie name `ns_session`.
- DNS/ports:
  - Backend `:8081`; Vite **5174** (5173 is left to Link), proxying `/api /auth /p /healthz` → 8081.
  - Pitfall: the dev realm registers the NS callback as `localhost:5173` while NS actually runs on
    5174; and dev.yaml's `base_url` is written as a LAN IP — accessing via IP/LAN is rejected by
    Keycloak login; for development use `http://localhost:8081`.
- Connections (the product catalog urls in dev.yaml still point at the lab domains — known current state):
  - Product catalog: `forge / horizon / link`, mode defaults to `ns`, callback path `/auth/ns-callback`.
  - Ticket: `GET /auth/enter/{product}` issues a 30-second one-time ticket → product backend
    `POST {ns}/api/v1/auth/ticket/verify` with headers `X-NS-Client-Id` / `X-NS-Client-Secret`.
  - OIDC issuer: `http://localhost:8090/realms/nereidai`.
  - Gateway: `/p/{product}/*` reverse-proxies and injects `X-User-*`; stamps
    `X-NS-Integration-Secret` on each product's tenants_path.
  - forward-auth: `GET /api/v1/auth/verify`.

#### K3S mode (chart `deploy/helm`, release/ns `nereidsphere`)
- Credentials:
  - Default `auth.mode=oidc`; a local break-glass path requires explicitly supplied bcrypt `localUsers`.
  - Rendered config in Secret `nereidsphere-config` (key `config.yaml`, or use `config.existingSecret`).
  - OIDC: `config.oidc.issuer/clientId/clientSecret/adminClientId/adminClientSecret` (placeholders
    `changeme*`, `required`).
  - Session key: `config.session.secretKey` (exactly 32 bytes, `required`).
  - Product ticket secret: `config.products[].ssoSecret` (placeholder `change-me-*`).
  - Valkey: when built in, Secret `nereidsphere-valkey` key `password`, injected only as the env
    var `NS_VALKEY_PASSWORD`.
- DNS/ports:
  - Service `nereidsphere` ClusterIP **8081**; chart default is 2 replicas with Valkey. The
    2026-10-29 single-replica lab uses `replicaCount=1`, `valkey.enabled=false`, and
    `tickets.replayStore=memory`.
  - Ingress **disabled by chart default**; when enabled in the lab, set host
    `nereidsphere.example`, annotation `cert-manager.io/cluster-issuer: internal-ca`, and TLS
    Secret `nereidsphere-tls`.
  - When built in, Valkey Services are `nereidsphere-valkey-primary:6379`, `-replica:6379`, and
    `-sentinel:26379` (headless).
  - CA: `config.oidc.caBundleSecret` (key `ca.crt`) mounted at `/etc/ssl/certs/nereid-oidc-ca.pem`.
- Connections:
  - Issuer `https://sso.example/auth/realms/nereidai`; Admin REST root
    `https://sso.example/auth/admin/realms/nereidai`.
  - Product catalog (k3s values): forge→`https://nereidforge.example` (tenants
    `/api/v1/tenants`), horizon→`https://nereidhorizon.example` (`/api/organizations`),
    link→`https://nereidlink.example` (`/v1/integration/ns/tenants`).
  - NereidEdge is deliberately absent from the product catalog.

### 3.3 NereidLink (Go all-in-one)

#### DEV mode
- Credentials:
  - TimescaleDB: `nereidlink/nereidlink/nereidlink` (compose host port 5432; DSN in `configs/dev.yaml`).
  - First boot: migration 0049 creates `admin@nereidai.local` (old value `admin@nereidlink.local`,
    renamed in 0084) with **empty password + must_change_password**; the password is set via the
    unauthenticated `POST /v1/auth/bootstrap`.
  - Deterministic development seed (only with explicit `nereidlink seed`):
    `admin@nereidai.local / <dev-password>`.
  - The JWT dev secret, registry module token (`dev-module-token`) and seed device token
    (`seed-device-token`) are all dev placeholders, located in `configs/dev.yaml`.
  - OIDC/NS SSO is disabled by default in dev (config keys exist, see below).
- DNS/ports:
  - HTTP/WS `:8080` (WS `/ws`); MQTT/MQTTS `1883/8883`; registry gRPC `127.0.0.1:19090`; ops
    `127.0.0.1:19190`.
  - NATS `nats://127.0.0.1:4222` (monitoring 8222); PG `127.0.0.1:5432`.
  - Vite 5173 (there is also a local-isolation config 15173→18080).
  - All-in-one compose published ports: `127.0.0.1:18080→8080`, `11883→1883`, `18833→8883`.
- Connections:
  - dev has no enabled config pointing at other Nereid products; OIDC keys:
    `oidc.enabled/issuer/client_id/client_secret/redirect_url/frontend_base_url`; NS ticket keys:
    `sso.ns_base_url/client_id/sso_secret/callback_path`, verification via
    `POST {NS}/api/v1/auth/ticket/verify`.
  - NereidEdge is an **inbound** relationship (Edge connects to Link's MQTT, topic prefix
    `v1/gateway/*`); Link has no Edge configuration.
  - S3: dev points at Forge's SeaweedFS (endpoint/keys in `configs/dev.yaml`; lab values are not copied out).

#### K3S mode (chart `deploy/kubernetes/helm/nereidlink`, release/ns default `nereidlink`)
- Credentials:
  - Secret `<release>-config-secret` (key file `90-secret.yaml`): `postgres.dsn`,
    `identity.jwt_secret`, `blob.access_key/secret_key`, `oidc.client_secret`, `sso.sso_secret`.
  - The chart still carries development-flavored defaults (JWT `change-me-…`, built-in PG
    `nereidlink/nereidlink`, `dev-module-token`, etc.); all must be overridden before delivery.
  - Harbor pull Secret `harbor-registry-secret`: the chart has a placeholder default — **override
    with install values; real values do not go in this file**.
  - blob S3 keys are `required`; external PG goes through `postgresql.externalDSN`.
  - Standard CLI post-deploy (2026-10-29): `deploy/kubernetes/scripts/deploy.sh
    install|upgrade|post-deploy` bootstraps `admin@nereidai.local` with a random
    48-hex password only while first-run setup is required. The mode-0600
    hand-off is `.deployment/deploy-values/nereidlink/admin-credentials.env`;
    reruns do not reset an existing password. Raw Helm users can still use the
    one-time product bootstrap UI/API.
  - The same post-deploy checks `nereidlink license status`, then signs and
    installs a default deployment license only if none exists. The signed
    license and status stay in `.deployment/deploy-values/nereidlink/`;
    mode-0600 deploy logs stay in `.deployment/deploy-logs/nereidlink/`. The
    vendor private key stays offline.
- DNS/ports:
  - Ingress `nereidlink.example` (TLS `nereidlink-tls`, issuer `internal-ca`), path `/`
    (including `/ws`) → Service 8080.
  - Service `<release>`: 8080 / 1883; separate `<release>-mqtt` NodePort **31883→1883,
    31884→8883** (edge-gateway access).
  - Bundled mode uses `<release>-postgresql:5432` (single StatefulSet, local-path); CNPG mode
    exposes its normal `-rw`/`-r`/`-ro` Services. `<release>-nats:4222`, monitoring 8222,
    headless `-nats-headless`.
  - SAN: `nereidlink.nereidlink.svc.cluster.local`, `nereidlink.example`, `192.0.2.11/57`.
- Connections:
  - OIDC (direct, optional): `oidc.*`; default callback
    `https://nereidlink.example/v1/auth/oidc/callback`.
  - NS ticket (the suite default picks one of OIDC/ticket; mutually exclusive with oidc):
    `sso.nsBaseURL=https://nereidsphere.example`, `clientID=link`,
    `callbackPath=/auth/ns-callback`, CA Secret `nereid-internal-ca-tls/ca.crt`.
  - NS console tenant pullback: `GET /v1/integration/ns/tenants` (headers
    `X-NS-Integration-Secret`, `X-User-Roles`).
  - Blob store (2026-10-29 live): Forge SeaweedFS
    `seaweedfs-s3.nereidforge.svc.cluster.local:8333`, bucket `nereidlink`, using
    the Forge S3 identity. Fresh installs complete Forge first (install-suite
    §7.1), then use the same site credentials for Link (§7.2); Link creates its
    bucket idempotently. The earlier temporary `emptyDir` backend was migrated
    and deleted on 2026-10-29 and must not be recreated.
  - No outbound config toward Edge/Fleet/Mobile/Horizon.

### 3.4 NereidHorizon (Express BFF + React; manages an external Open Horizon Exchange)

#### DEV mode
- Credentials:
  - **The product ships no built-in admin**: the first-boot Setup wizard's `POST /api/setup`
    creates the `platform` user (≥8 chars); emergency entry at `/login?local=1`.
  - Setup also requires the Exchange super-account (upstream dev default `root/root`, dev environment only).
  - dev PG: db/user `nereid` / password `nereidpass` (npm brings up the DB on host port **5433**;
    the DSN lives in `.deployment/deploy-values/nereidhorizon/backend.env`).
  - Session master key `SESSION_ENC_KEY` (64 hex); if empty it lands in
    `.deployment/deploy-values/nereidhorizon/state/session.key` (0600).
  - OIDC: `OIDC_CLIENT_ID/OIDC_CLIENT_SECRET` (unset = off); NS: `NS_PRODUCT_ID=horizon`,
    `NS_CLIENT_SECRET`.
  - The verified Exchange setup input is
    `.deployment/deploy-values/nereidhorizon/exchange.env`; values do not go in
    this file, and `/api/setup` must not be rerun against an initialized system.
- DNS/ports:
  - BFF **3001** (`/api/health`); Vite **8080** proxying `/api`; compose form frontend
    8443(HTTPS)/8090(HTTP).
  - The lab Exchange address is filled in during Setup and stored encrypted in the DB (table
    `exchange_config`); code does not read an `EXCHANGE_URL` environment variable.
  - ESS/CSS default to the same host as Exchange on **9443** (setting `ess_base_url`).
- Connections:
  - Exchange REST `{url}/v1/...` (Basic auth); agbot/anax, CSS, Vault addresses are generated by
    the agbot deployment script.
  - NereidForge: runtime Settings configuration (no env):
    `forge_base_url / forge_username / forge_password / forge_namespace / forge_tenant`, login via
    `/api/v1/auth/login`, model-package pull via `/api/v1/models/.../packages`.
  - NS ticket: `NS_BASE_URL` + `POST {NS}/api/v1/auth/ticket/verify`; org switching via
    `POST /api/switch-org`; tenant pullback via `GET /v1/integration/ns/tenants`.
  - OIDC: `OIDC_ISSUER` (dev allows `OIDC_INSECURE_SKIP_VERIFY=true`), callback
    `/api/oidc/callback`, internal CA via `NODE_EXTRA_CA_CERTS`.

#### K3S mode (chart `deploy/helm/nereidhorizon`, namespace-neutral)
- Credentials:
  - Single Secret `<fullname>`: `session-enc-key` (random on first install, kept),
    `postgres-password` (random 24 chars if empty), `database-url`, plus `oidc-client-secret` and
    `ns-client-secret` when enabled.
  - The BFF admin still must be created post-install via port-forward to `POST /api/setup` (the
    chart does not pre-create one).
  - Harbor pull Secret `harbor-registry-secret`; registryCredentials must be supplied at install time.
- DNS/ports:
  - Ingress `nereidhorizon.example` (TLS `nereidhorizon-tls`), path `/` → frontend Service 80.
  - `<fullname>-frontend:80` (nginx), `<fullname>-backend:3001`, `<fullname>-postgres:5432`
    (PVC `local-path`).
  - nginx ConfigMap: `/api/` → backend; explicitly allow `/auth/ns-callback`,
    `/v1/integration/ns/`.
- Connections:
  - OIDC issuer example `https://sso.example/auth/realms/nereidai`, callback
    `https://nereidhorizon.example/api/oidc/callback`; group claims
    `nereidhorizon-platform` / `nereidhorizon-partner-<org>`.
  - NS: `ns.baseUrl=https://nereidsphere.example`, productId `horizon` (NS side mode `ns`,
    tenants_path `/v1/integration/ns/tenants`).
  - Exchange / Forge / ESS are **not modeled by the chart**; they stay runtime Setup/Settings
    configuration.

### 3.5 NereidForge (FastAPI + Next.js + Kubeflow platform; the heaviest)

#### DEV mode
- Credentials:
  - Platform super-admin (local login): `admin / <dev-password>`, mailbox `admin@nereidforge.local`,
    tenant `default`.
  - dev PG: `nereidforge/nereidforge/nereidforge` (host 5432); dev SeaweedFS has no auth, app
    default keys `nereidforge/nereidforge`.
  - Label Studio / CVAT (connecting to the clustered instances in dev): `admin / <dev-password>`;
    integration tokens in `.deployment/deploy-values/nereidforge/service-tokens.env`
    and local settings in `.deployment/deploy-values/nereidforge/dev.env`
    (**values do not go in this file**).
  - Grafana `admin/admin`; MailHog unauthenticated (SMTP 1025 / UI 8025).
  - dev defaults to `auth.enabled=false` (local API calls unauthenticated).
- DNS/ports:
  - API `:8080`, Vite 5173; dev PG 5432; SeaweedFS master 9333 / S3 8333 / filer 8888 / volume
    18080→8080; monitoring 3001/9090/3100/3200.
  - In-cluster services are reached via `infra/scripts/dev-port-forward.sh`: S3 8833, KFP 18888,
    Model Registry 8889, Trainer 8890, etc.
  - LS/CVAT development also uses domains `labelstudio.nereidforge.example` /
    `cvat.nereidforge.example`.
- Connections:
  - dev SSO issuer / NS base are both empty (pure local login).
  - KFP/Model Registry/Trainer/SeaweedFS are all localhost port-forward addresses
    (`config.dev.yaml`).
  - No direct connection to Link/Edge/Inference; the outward contract is the `nereid-model.json`
    model package + KServe descriptor.

#### K3S mode (staged chain `10_infra.sh` → `30_install-kubeflow.sh` → `40_nereidforge.sh` → `60_verify.sh`)
- Credentials (bootstrapped by scripts after deployment; **lab values are in each
  machine's `.deployment/deploy-values/nereidforge/site.env`, not in this file**):
  - Platform login (2026-10-29): user `admin` plus a random 48-hex password on
    first seed, stored in
    `.deployment/deploy-values/nereidforge/admin-credentials.env` (mode 0600).
    Leaving `NF_ADMIN_PASSWORD` unset preserves an existing password; supplying
    it explicitly rotates the account through the application service. The old
    `admin/<dev-password>` delivery default is retired.
  - Backend Secret `<release>-secrets` (release `nereidforge-backend`) keys:
    `NEREIDFORGE_DATABASE_PASSWORD`, `NEREIDFORGE_AUTH_JWT_SECRET`,
    `NEREIDFORGE_SSO_NS_CLIENT_SECRET`, `NEREIDFORGE_SSO_OIDC_CLIENT_SECRET`,
    `NEREIDFORGE_LABELSTUDIO_TOKEN`, `NEREIDFORGE_CVAT_TOKEN`,
    `NEREIDFORGE_STORAGE_S3_{ACCESS,SECRET}_KEY`,
    `NEREIDFORGE_KFP_OBJECT_STORE_{ACCESS,SECRET}_KEY`.
  - PG: CNPG `nereidforge-postgresql`, source Secret
    `pg-nereidforge-postgresql-credentials`, copied into the tenant namespace as
    `pg-nereidforge-credentials`; DBs `nereidforge/labelstudio/cvat` share the owner.
  - SeaweedFS S3 uses the site `SEAWEEDFS_S3_ACCESS_KEY` /
    `SEAWEEDFS_S3_SECRET_KEY`; legacy `nereidforge/nereidforge` is a dev-only
    default and is not a delivery credential. Valkey has no password.
  - Kubeflow Dex uses the site `DEX_STATIC_EMAIL` / `DEX_STATIC_PASSWORD`
    (Secret `auth/dex-passwords`); there is no delivery password default. Dex
    OIDC client `kubeflow-oidc-authservice` uses a site secret (the upstream
    default in `secret_params.env` must be replaced for delivery).
  - KFP artifacts: Secret `mlpipeline-minio-artifact` (keys accesskey/secretkey, bucket
    `mlpipeline`, endpoint `seaweedfs.kubeflow:9000`).
  - Suite SSO: Keycloak client `nereidforge` (secret injected at install); NS ticket product id `forge`.
    Forge `SSO_NS_CLIENT_SECRET` must exactly match Sphere's registered
    `products[id=forge].ssoSecret`; a mismatch produces `ns_unauthorized`.
  - Every staged entry point writes a timestamped mode-0600 log under
    `.deployment/deploy-logs/nereidforge/` with a `latest-<stage>.log` symlink.
    Credentials and service tokens stay in
    `.deployment/deploy-values/nereidforge/`. The admin credential and
    service-token files are mode 0600; a sudo administrator can read them
    locally and must store an encrypted backup outside Git.
- DNS/ports (namespace `nereidforge`; platform namespaces: `kubeflow`, `auth`, `istio-system`; the
  Model Registry DB is in `default`):
  - `nereidforge.example`: `/` frontend 80, `/api` → `nereidforge-api:8080`, additionally
    allow `/auth/ns-callback`, `/v1/integration/ns`; TLS `nereidforge-frontend-tls`.
  - `labelstudio.nereidforge.example` (`labelstudio:8080`),
    `cvat.nereidforge.example` (`cvat-backend-service:8080`).
  - Model inference routing (Traefik IngressRoute, not a K8s Ingress):
    `<model_type>-<short_ver>.inference.example`, backend Knative SKS 80; needs wildcard DNS
    `*.inference.example`.
  - Other Services: `ml-backend:9090`, `nereidforge-trainer:8890`,
    `nereidforge-postgresql-rw:5432`, `seaweedfs-s3:8333/9000`, `seaweedfs-filer:8888`,
    `seaweedfs-master:9333`, `valkey-master:6379`; KFP `ml-pipeline.kubeflow:8888`, Model Registry
    `model-registry-service.default:8080` (UI via kubeflow-gateway `/model-registry`).
  - NF's own chart **defines no NodePort** (the kind overlay's 30xxx values are not used for the
    standard deployment).
- Connections:
  - NS ticket: `https://nereidsphere.example`, `X-NS-Client-Id: forge`, verification via
    `POST /api/v1/auth/ticket/verify`; browser entry `/auth/enter/forge`; tenant pullback via
    `GET /v1/integration/ns/tenants` (`X-NS-Integration-Secret` equals the ticket secret).
  - OIDC (optional): issuer `https://sso.example/auth/realms/nereidai`, callback
    `https://nereidforge.example/auth/callback`.
  - The Horizon direction is **reverse pull**: NH calls NF's model-file API and distributes via
    ESS; NF has no NH address configured.
  - Multi-tenant namespace model: `nereidforge-<tenant>` per tenant.

### 3.6 NereidInference (EdgeX device service `device-inference`, Go)

#### DEV mode (layered on top of official edgex-compose)
- Credentials:
  - `EDGEX_SECURITY_SECRET_STORE=false`; the product itself has no account.
  - Bearer for OpenAI-style backends (vLLM/MindIE/OVMS-LLM): an EdgeX secret entry (config item
    `Inference.OpenAIAPISecret`) with key **`api_key`**; empty = no authentication.
  - Camera RTSP/ONVIF credentials: not configured in this repo; NereidEdge delivers them jointly
    via EdgeX secrets.
- DNS/ports (containers on the external network `edgex_edgex-network`):
  - DS API **59992** (tentative port, pending EdgeX TSC assignment; published on the host at the same port).
  - MJPEG preview: container **18080**, host **28080**, paths `/preview/{device}.mjpeg`,
    `/preview/{device}/frame.jpeg` (unauthenticated).
  - Model servers: `edgex-ovms:9000` (KServe gRPC v2, host 19000), `:9001` (REST/config reload);
    OpenAI default `edgex-vllm:8000`.
  - EdgeX core: keeper 59890, metadata 59881, command 59882; ONVIF DS 59984.
  - Volumes: model root `/var/lib/nereid-inference/models`, runtime config `.../models/runtime`,
    inbox `.../inbox`, ESS landing mounted read-only at
    `/var/horizon/ess-store/sync/local`.
- Connections:
  - **NereidHorizon (no URL)**: watches the ESS landing directory; a model package (a tar.gz with
    no extension, root `nereid-model.json`) is loaded as soon as it lands; there is also a manual
    operator drop directory `inbox`.
  - **NereidForge (no URL)**: only conforms to the model-package contract (`nereid-model/1`).
  - **NereidEdge**: no hard dependency; jobs can be registered directly via the EdgeX REST API; NE
    manages via keeper KVS (`edgex/v4/device-inference`) and the DS API.
  - The message-bus endpoint is provided by edgex-compose/keeper; this repo only sets clientId
    `device-inference`.

#### K3S mode
- **Does not exist.** The production deployment form is an Open Horizon service definition (owned
  by the NereidHorizon repository/deliverables); there is no Helm/Ingress/Service/Secret manifest.

### 3.7 NereidEdge (EdgeX App Service `nereid-edge`, Go)

#### DEV mode (compose, external `edgex_edgex-network`)
- Credentials:
  - EdgeX non-secure mode; the product itself has no account.
  - Northbound NereidLink gateway credential pair: `NEREID_CRED_ID` (`gw-xxxx_token`) + secret,
    injected via environment variables `NEREIDEDGE_BROKERURL/CREDENTIALID/CREDENTIALSECRET`. The
    template `.env.example` is empty; lab values live in each gateway's
    `.deployment/deploy-values/nereidedge/compose.env` (0600) and **do not go in
    this file**.
  - EdgeX secrets are encrypted at rest in `/app/data` (empty KeyFile = ephemeral key; the platform
    re-delivers after reconnect).
- DNS/ports:
  - Own HTTP **59750**: `GET /api/v4/ping`.
  - EdgeX peers: core-command `edgex-core-command:59882`, keeper 59890, onvif DS
    `edgex-device-onvif-camera:59984`, MQTT bus `edgex-mqtt-broker:1883`.
  - NereidInference: `edgex-device-inference:59992`.
- Connections:
  - **NereidLink (the only northbound product connection)**: MQTT, topic family
    `v1/gateway/{telemetry,connect,goodbye,command,probe,attributes,secrets,operations,profiles,linkhealth,connectors}`;
    plaintext 1883 / TLS 8883.
  - **NereidInference (edge-local, ADR-0039)**: polls the manager device `nereid-inference`'s
    `ModelsJSON` in keeper; stream credentials are dual-delivered to the DS `/api/v3/secret`,
    replayed every 30 seconds.
  - **No connection of any kind** to Forge/Horizon/Sphere/SSO (neutral channel; never touches model
    packages/ESS).

#### K3S mode
- Not in the cluster. Select the cluster-pointing variant directly with
  `ENV_FILE=../.deployment/deploy-values/nereidedge/compose.k3s.env`: broker
  `tcp://nereidlink.example:31883` (TLS 31884), with the credential pair in
  that file; **values do not go in this file**.
  No cluster resources need to be created for NE.

### 3.8 NereidFleet / NereidMobile / NereidRobot
- NereidFleet: the repository has design docs only (Zenoh/Open-RMF technical research); no code,
  chart, default account, domain, or connection configuration; every entry is **TBD**. Planned
  facts: robot side Zenoh 1.5.x + `zenoh-plugin-ros2dds`, ROS 2 Jazzy / CycloneDDS; planned
  northbound VDA5050 over MQTT; planned edge bridge `bridge-edgex-zenoh`; already registered in the
  organization product table (*Planned — working name*).
- NereidMobile: a pure client repository (Flutter + WeChat Mini Program) with no server resources;
  needs a WeChat AppID (configured at release time); will log in via NereidIdentity and read
  NereidLink (exact baseUrl config keys TBD).
- NereidRobot: planned, no repository; the organization diagram includes it (`+ robot DS`, a
  built-in EdgeX device service); single root data line with NereidEdge, real-time LAN loop with
  Fleet over commands/state.

---

## 4. Inter-product connection matrix

| # | Source → target | Protocol/endpoint | DEV address/config | K3S address/config |
|---|---|---|---|---|
| 1 | Each product → NereidIdentity | OIDC discovery | `http://localhost:8090/realms/nereidai` | `https://sso.example/auth/realms/nereidai` |
| 2 | Product browser → NereidSphere → product | NS ticket (30s, single use): `/auth/enter/{p}` → product `/auth/ns-callback` → product backend `POST /api/v1/auth/ticket/verify` (`X-NS-Client-Id/Secret`) | dev.yaml product catalog (secret placeholder `changeme-*`) | `config.products[]` (ssoSecret `required`) |
| 3 | NS → products (console tenant pullback) | HTTP: Link `/v1/integration/ns/tenants`, Horizon `/api/organizations`, Forge `/api/v1/tenants`, header `X-NS-Integration-Secret` | same protocol | same protocol, via the gateway `/p/{product}/...` |
| 4 | NereidEdge → NereidLink | MQTT `v1/gateway/*`, 1883/8883, gw-token credential pair | `tcp://<dev-host>:1883` | `tcp://nereidlink.example:31883` (TLS 31884) |
| 5 | NereidEdge → NereidInference | EdgeX REST/KVS: DS `:59992/api/v3/secret`, keeper `edgex/v4/device-inference` | `edgex-device-inference:59992` | same (edge-local; no cluster path) |
| 6 | NereidInference → model server | KServe gRPC v2 (OVMS :9000) / OpenAI HTTP (vLLM :8000) | compose service name | at the edge carried by the model-package descriptor; in cluster Knative ISVC → `*.<model>-<ver>.inference.example` |
| 7 | NereidHorizon → Open Horizon Exchange/agbot/ESS | Exchange REST `/v1/*` (Basic); ESS 9443 | lab address filled in during Setup | runtime Setup/Settings; not modeled by the chart |
| 8 | NereidHorizon → NereidForge | HTTP: `/api/v1/auth/login`, `/api/v1/models/.../packages` (pull model packages) | Settings `forge_*` keys | same (runtime configuration) |
| 9 | NereidHorizon/ESS → NereidInference | no API: ESS objects land at `/var/horizon/ess-store/sync/local`, watched by the DS | compose read-only mount | OH anax landing, same path |
| 10 | NereidLink ← NereidMobile | HTTPS/WS (telemetry/charts/alerts) | TBD | TBD (planned login via NereidIdentity) |
| 11 | NereidFleet → NereidRobot | LAN real-time: commands/state (Zenoh/ROS 2, planned) | TBD | TBD |
| 12 | NereidSphere/NereidLink/… → internal-ca | TLS trust | TLS off in dev | copy `cert-manager/nereid-internal-ca-tls` (key `ca.crt`) into the product namespace |

Mutual-exclusion switch: NereidLink's `oidc.enabled` and `sso.enabled` are mutually exclusive; the
suite default mode is the NS ticket (`ns`). Current state: Link uses direct OIDC, Forge uses the NS
ticket, Horizon is OIDC-only; align with the suite SSO model at deployment time.

## 5. k3s secret retrieval commands (for delivery/operations)

```bash
# Keycloak master admin (set at install time; if lost, only Keycloak's own recovery flow applies)
kubectl -n nereididentity get secret nereididentity-admin -o jsonpath='{.data.KEYCLOAK_ADMIN_PASSWORD}' | base64 -d; echo
# Suite admin user's first-install random password
kubectl -n nereididentity get secret nereididentity-realm -o jsonpath='{.data.suite-admin-password}' | base64 -d; echo
# Per-product client secrets (key names: admin-client-secret / nereidai-realm.json contains every client)
kubectl -n nereididentity get secret nereididentity-realm -o jsonpath='{.data.admin-client-secret}' | base64 -d; echo
# CNPG database password
kubectl -n nereididentity get secret pg-keycloak-credentials -o jsonpath='{.data.password}' | base64 -d; echo
# Sphere config (incl. OIDC/ticket secrets) and Valkey
kubectl -n nereidsphere get secret nereidsphere-config -o jsonpath='{.data.config\.yaml}'
kubectl -n nereidsphere get secret nereidsphere-valkey -o jsonpath='{.data.password}' | base64 -d; echo
# Link / Horizon / Forge: see each release's own Secret (key names listed in the corresponding §3 subsection)
```

Production hardening checklist (close out after deployment):
1. Keycloak master password, suite admin password, and PG passwords are all explicitly set at
   install time; no random default may flow out.
2. `identity.seedUsers=false`; remove/change every `changeme*`, `admin/admin`, `<dev-password>`,
   `<dev-password>`, `nereidpass` and other dev default.
3. Override the development-flavored defaults in Link/Forge charts (JWT, module token, built-in
   PG, S3 keys).
4. Replace the Kubeflow Dex password and the `kubeflow-oidc-authservice` client secret.
5. Rotate NereidEdge gateway credential pairs one secret per gateway; lab `.env*` files never enter
   any repository.
