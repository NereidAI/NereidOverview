# NereidOverview

**Start here.** This is the source-code entry point for the NereidAI suite.
Whether you are deploying the platform for the first time or doing secondary
development, you begin in this repository.

It contains no product runtime code — only orientation, the full-suite
deployment runbooks and reference material, deployment standards,
cluster-shared prerequisites, and air-gapped delivery tooling. Products ship
in their own repositories; the scenario guide below explains which ones make
sense alone and which only work as part of a combination.

> **What is NereidAI?** Product descriptions, architecture, and the full
> product list live on the [NereidAI organization page](https://github.com/NereidAI).
> This README covers working with the source only.

## Choose your deployment path

Three scenarios cover the practical ways teams enter the suite. Pick the
smallest one that fits your goal; every product also has its own README with
the product-level details.

### Scenario 1 — Single product: testing or development

No ordering and no suite-wide prerequisites: clone one repository and follow
its README. Standalone suitability differs by product role:

| Product | Role | Meaningful on its own? |
|---|---|---|
| NereidLink | Private IoT platform: device onboarding, telemetry, rules, alerts | **Yes** — testing the IoT platform is a single-repo job |
| NereidForge | Model factory: annotation, training, optimization, evaluation, model registry | **Yes** — testing the model factory is a single-repo job |
| NereidHorizon | Edge/OTA distribution plane built on Open Horizon | **Yes** — edge distribution can be evaluated on its own |
| NereidEdge | Field gateway policy/guard process (EdgeX application service) | **No** — designed to pair with NereidLink as its northbound platform |
| NereidInference | Edge inference runtime (EdgeX device service) | **No** — auxiliary to NereidEdge; it has no standalone purpose |
| NereidSphere | Suite portal and unified entry point | **No** — only makes sense with products behind it |
| NereidIdentity | Suite identity plane (SSO/OIDC, RBAC, tenant governance) | **No** — only makes sense with products federating to it |

### Scenario 2 — Docker / Compose: testing or simple commercial deployment

Single-host container stacks work for both testing and simple commercial use,
but configuration is more involved: you must understand the overall
architecture and edit configuration files yourself, and there is no
clustering, high availability or horizontal scaling. Two common combinations:

- **NereidLink + NereidEdge** — cloud-edge collaboration: the field gateway
  reports into a single-host IoT platform.
- **NereidHorizon + NereidEdge + NereidInference** — edge distribution and
  model distribution: the distribution plane pushes services and model
  packages to field gateways running inference.

Only a product's explicitly documented production Compose path is
production-eligible; trial overrides and development compose files are not.
The formal support matrix is the section below.

### Scenario 3 — Full suite on Kubernetes: complete testing and commercial use

Deploying every product under Kubernetes (k3s or a conformant cluster) via
Helm unlocks the complete suite functionality — high availability,
horizontal scaling and namespace-per-tenant multi-tenancy — and is the
strongly recommended production form. The requirement is not only hardware
and cluster infrastructure: the team needs real Kubernetes operational
capability **and** AI engineering capability to run the model factory and
edge loop. Follow the linear deployment chain in the
[deployment guides](docs/deploy/README.md) (cluster bootstrap → shared
prerequisites → products → verification); air-gapped sites use the same
steps with image delivery handled per
[deploy-standards §15.3](docs/deploy-standards.md).

### Quick links

| Goal | Go to |
|---|---|
| Cluster-shared prerequisites (cert-manager, NFS CSI, GPU/NPU plugins) | [`deploy/prereqs/`](deploy/prereqs/) |
| Air-gapped delivery rules and tooling | [Deploy & delivery standards](docs/deploy-standards.md) §15.3, §15.10 |
| Contribute a fix or improvement | [Contributing guide](CONTRIBUTING.md) |
| Full product list and architecture overview | [NereidAI organization page](https://github.com/NereidAI) |

## Deployment modes and support boundaries

Every NereidAI product can be started in more than one way, but the run modes
are not interchangeable. Their support levels are a suite-wide rule, restated
in every product README and normalized in [deploy-standards §15.14](docs/deploy-standards.md):

| Run mode | Typical entry point | Purpose | Production support |
|---|---|---|---|
| **Dev mode** | Host processes, `make dev`, `configs/dev.yaml`, Vite/dev servers | Day-to-day development and debugging only | **Not supported — never use for production** |
| **Docker / Compose mode** | `docker compose`, single-host container stacks | Testing, demos, image verification and local evaluation; selected stacks also serve single-host, edge and air-gapped appliance deployments | **Partially supported** — only a product's explicitly documented production Compose path; no clustering, high availability or horizontal scaling |
| **Kubernetes mode** | Helm charts on k3s/Kubernetes, per each product's own deployment docs | Full-featured production deployment | **Strongly recommended for production — full functionality** (HA, horizontal scaling, multi-tenancy) |

Platform products (NereidIdentity, NereidSphere, NereidLink, NereidHorizon,
NereidForge) follow this table; each product README names exactly which Compose
assets, if any, are production-eligible (for example NereidHorizon's air-gapped
production stack and NereidLink's Mode A/B edge stack) versus trial-only
overrides. Edge products (NereidEdge, NereidInference) have no Kubernetes
mode: their production form is the Open Horizon service definition delivered
and managed by NereidHorizon, while their Compose stacks remain development and
testing only. Dev mode must never be described or supported as a production
installation; a Compose deployment may be, only when it follows the product's
documented production path with its stated capability limits.

## Workspace layout

> **Full-suite deployment requires every NereidAI product repository cloned
> locally** — products install from local sibling chart paths, not from a
> remote chart repository. Clone the whole organization's repositories as
> siblings under one directory:
>
> ```bash
> git clone https://github.com/NereidAI/NereidOverview.git
> git clone https://github.com/NereidAI/NereidIdentity.git
> # …repeat for every product in the organization
> ```

```text
nereid-workspace/
├── .deployment/
│   ├── deploy-values/  # site inputs and hand-offs, outside every Git repository
│   └── deploy-logs/    # deployment and verification logs
├── NereidOverview/     # you are here
├── NereidIdentity/
├── NereidLink/
├── NereidSphere/
├── NereidHorizon/
├── NereidForge/
├── NereidEdge/         # field gateway policy/guard process
├── NereidInference/    # EdgeX device service: edge inference runtime
└── …                   # every other NereidAI repository
```

A single-product deployment needs only that one repository when the product
is standalone-capable (see the Scenario 1 table). Actual site values,
credentials, keys, licenses, and deployment logs live under `.deployment/`,
not inside a product checkout; canonical charts, templates, and placeholder
examples remain versioned with their products. The complete repository list is
on the [organization page](https://github.com/NereidAI).

## What is in this repository

| Path | Contents |
|---|---|
| `docs/` | Deployment runbooks, reference material, and the deployment/packaging/delivery standards |
| [`deploy/prereqs/`](deploy/prereqs/) | Cluster-shared components: cert-manager, NFS CSI, GPU/NPU device plugins |
| [`deploy/scripts/`](deploy/scripts/) | Air-gapped image mirroring tooling and its empty environment template |

## Contributing

Contributions are welcome — runbook corrections, prerequisite manifests, and
air-gapped tooling improvements all start here; product runtime changes go to
the product's own repository. Every commit must carry a Developer Certificate
of Origin sign-off, and every contribution is licensed under Apache-2.0. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the full rules, including copyright
handling and the host-free requirements.

## Repositories

Each product has its own repository and release cycle; standalone
suitability varies by role — see the Scenario 1 table above. The complete
product list and descriptions live on the
[organization page](https://github.com/NereidAI):
[NereidIdentity](https://github.com/NereidAI/NereidIdentity) ·
[NereidLink](https://github.com/NereidAI/NereidLink) ·
[NereidSphere](https://github.com/NereidAI/NereidSphere) ·
[NereidHorizon](https://github.com/NereidAI/NereidHorizon) ·
[NereidForge](https://github.com/NereidAI/NereidForge) ·
[NereidEdge](https://github.com/NereidAI/NereidEdge) ·
[NereidInference](https://github.com/NereidAI/NereidInference)
