# NereidOverview

**Start here for public NereidAI installation.** This repository contains the
suite runbooks, delivery standards, and cluster-shared prerequisites. Product
runtime code and product-owned Helm chart sources remain in their respective
repositories.

The supported installation form is an internet-connected Kubernetes/k3s
cluster using versioned GHCR OCI charts and public images. Operators run every
step manually and verify each phase before continuing.

## Installation path

1. Prepare or accept a Rancher-managed empty k3s cluster with the
   [cluster bootstrap guide](docs/deploy/cluster-bootstrap.md).
2. Install the [cluster-shared prerequisites](deploy/prereqs/README.md).
3. Follow the [suite installation guide](docs/deploy/install-suite.md) in this
   strict order:

   **NereidIdentity → NereidSphere → NereidHorizon → NereidForge → NereidLink**

4. Deliver field services through Open Horizon, configure NereidEdge to connect
   to Link, and deliver models through ESS as a separate operation.
5. Complete the [fresh-cluster checklist](docs/deploy/reference/fresh-cluster-checklist.md).

NereidLink requires Forge SeaweedFS and its exact credentials from the first
installation. Do not install Link before Forge is healthy.

## Verified Lab/POC artifacts

The following immutable versions passed anonymous chart pull/render and
image-manifest verification on 2026-11-22:

| Product | Chart and image version | Source commit |
|---|---|---|
| NereidIdentity | `0.0.0-dev-7c2797d` | `7c2797ddec13d6fcef72a535069738d247173e61` |
| NereidSphere | `0.0.0-dev-90379cb` | `90379cbec953c51b5807cf60f53c17fb736da1ff` |
| NereidHorizon | `0.0.0-dev-05aaf97` | `05aaf97bb5d3119f00ccc2ea90d3e8bb86dda49d` |
| NereidLink | `0.0.0-dev-6da29bd` | `6da29bdca204510bd4b8560c503ead28bc231c0b` |

Charts use `oci://ghcr.io/nereidai/charts/<chart-name>` with an explicit
`--version`. Each chart selects matching suite images through its `appVersion`.
The floating `0.0.0-dev` channel is not a reproducible installation input.
Formal deployments must select a published, anonymously verified bare-SemVer
version instead.

> **Current full-suite boundary:** Forge does not yet have a complete public
> installation channel. Its rolling channel contains backend/frontend images
> only. No complete nine-chart/23-image Forge release or public Release
> installer has been verified. On an empty cluster, stop after Horizon; do not
> proceed to Link until a complete Forge release satisfies the installation
> guide's gate. Link's verified chart does not remove that dependency.

## Operator workspace

Only NereidOverview is needed for the shared prerequisites and suite runbook.
Product charts are pulled directly from GHCR; product source checkouts are not
part of the installation procedure.

Keep site inputs outside every Git checkout:

```text
$HOME/.nereidai-deployment/
├── deploy-values/   # values, credentials, keys, and generated hand-offs
├── deploy-logs/     # deployment and acceptance records
└── chart-archives/  # pulled packages used to initialize example values
```

Use restrictive directory and file permissions. Generate a unique secret for
every required credential and never commit real domains, addresses, values, or
hand-off files.

## What is in this repository

| Path | Contents |
|---|---|
| [`docs/deploy/`](docs/deploy/) | Public cluster and suite installation runbooks |
| [`docs/deploy-standards.md`](docs/deploy-standards.md) | Public artifact, publication, installation, and acceptance contracts |
| [`deploy/prereqs/`](deploy/prereqs/) | cert-manager CA resources, NFS CSI, and GPU/NPU device plugins |

## Edge delivery

NereidEdge and NereidInference run at edge sites rather than as central k3s
product charts. After Link is healthy, the operator manually:

1. registers each edge host with Open Horizon;
2. delivers the service Pattern and confirms the agreement and service health;
3. configures NereidEdge with its own Link MQTT credentials and device map;
4. verifies Link heartbeats and telemetry; and
5. delivers and verifies each model through ESS independently.

A service agreement does not prove model delivery.

## Contributing

Contributions to public runbooks, shared prerequisite manifests, and these
standards start here; product runtime and chart changes belong in the product's
own repository. Every commit must carry a Developer Certificate of Origin
sign-off, and every contribution is licensed under Apache-2.0. See
[CONTRIBUTING.md](CONTRIBUTING.md).

## Repositories

The complete product list and architecture overview are on the
[NereidAI organization page](https://github.com/NereidAI):
[NereidIdentity](https://github.com/NereidAI/NereidIdentity) ·
[NereidSphere](https://github.com/NereidAI/NereidSphere) ·
[NereidHorizon](https://github.com/NereidAI/NereidHorizon) ·
[NereidForge](https://github.com/NereidAI/NereidForge) ·
[NereidLink](https://github.com/NereidAI/NereidLink) ·
[NereidEdge](https://github.com/NereidAI/NereidEdge) ·
[NereidInference](https://github.com/NereidAI/NereidInference)
