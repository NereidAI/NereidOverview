# NereidOverview

**Use this repository as an optional quick reference for public NereidAI
installation.** It contains suite runbooks, delivery standards, cluster-shared
prerequisites, and a resumable convenience installer. Product runtime code and
product-owned Helm chart sources remain in their respective repositories.

NereidOverview is not a required deployment controller. Operators can install
all components directly from their owning artifacts and documentation, using
their own procedures or automation, without following this repository's manual.
The supported platform form is an internet-connected Kubernetes/k3s cluster
using versioned GHCR OCI charts and public images. Every installation path must
preserve the same ordering, artifact, Secret-retention, and acceptance gates.

## Installation path

1. Prepare or accept a Rancher-managed empty k3s cluster with the
   [cluster bootstrap guide](docs/deploy/cluster-bootstrap.md).
2. Install the [cluster-shared prerequisites](deploy/prereqs/README.md).
3. Install in this strict order:

   **NereidIdentity → NereidSphere → NereidHorizon → NereidForge → NereidLink**

   Either follow the complete [manual suite guide](docs/deploy/install-suite.md),
   or configure one non-secret `deployment.env` and use the optional
   [resumable quick installer](docs/deploy/quick-install.md). The latter runs
   and resumes with one command, verifies completed stages before skipping them,
   and still pauses at independent publication and live-acceptance gates.
   Equivalent independently managed installation procedures are also valid.

4. Deliver field services through Open Horizon, configure NereidEdge to connect
   to Link, and deliver models through ESS as a separate operation.
5. Complete the [fresh-cluster checklist](docs/deploy/reference/fresh-cluster-checklist.md).

NereidLink requires Forge SeaweedFS and its exact credentials from the first
installation. Do not install Link before Forge is healthy.

## Verified development artifacts

The floating `0.0.0-dev` charts and their corresponding first-party images
passed anonymous chart pull/render and image-manifest verification on
2026-11-22. The [dated evidence snapshot](docs/deploy/reference/development-artifacts-2026-11-22.md)
records the exact resolved chart versions/digests, image index digests, and
publication runs:

| Product | OCI chart | Development selector |
|---|---|---|
| NereidIdentity | `oci://ghcr.io/nereidai/charts/nereididentity` | `0.0.0-dev` |
| NereidSphere | `oci://ghcr.io/nereidai/charts/nereidsphere` | `0.0.0-dev` |
| NereidHorizon | `oci://ghcr.io/nereidai/charts/nereidhorizon` | `0.0.0-dev` |
| NereidLink | `oci://ghcr.io/nereidai/charts/nereidlink` | `0.0.0-dev` |

The floating chart tag aliases the latest successfully published immutable
`0.0.0-dev-<short-sha>` OCI manifest; it is not a separate chart package. The
archive retains that immutable chart version and `appVersion`, selecting
matching immutable product images. Normal development installations therefore
need only `0.0.0-dev`. Record the resolved chart digest/version and running
image digests as deployment evidence. Use the resolved short-SHA snapshot only
for deliberate reproduction. Formal deployments must select a published,
anonymously verified bare-SemVer version instead.

> **Full-suite boundary:** Forge uses independently gated development stages,
> not a formal-release prerequisite. The verified pre installer and five
> supporting charts are sufficient to start pre-only §7.2. The selected NF
> profile (23 `full` images, or 18 `cpu-xpu` images retaining Intel XPU) and four
> NF charts must separately pass anonymous verification before NF §§7.3–7.5;
> backend/frontend images alone are insufficient. Do not proceed
> to Link until live Forge and SeaweedFS acceptance also passes. Link's verified
> chart does not remove that dependency.

## Operator workspace

For this repository's optional guided path, only the NereidOverview checkout is
needed for the shared prerequisites and convenience tooling. Product charts are
pulled directly from GHCR; product source checkouts are not part of the central
installation procedure except for the exact-commit NF verifier. Independent
installations may use the owning products' artifacts and their own tooling
instead of this runbook, provided they satisfy the published contracts.

Keep site inputs outside every Git checkout:

```text
$HOME/.nereidai-deployment/
├── deployment.env   # persistent non-secret selectors, paths, and site inputs
├── deploy-values/   # site values, rendered values, and generated hand-offs
├── secret-store/    # persistent generated operator-supplied secrets
├── deploy-logs/     # resolved digests, deployment, and acceptance records
└── chart-archives/  # single resolved packages used for values and installation
```

For the manual path, create `deployment.env` from the installation guide once,
then run `source scripts/load-deployment-env.sh` in each operator shell to
restore its selectors, paths, resolved identities, and download helpers. For
the quick path, edit the same single non-secret file and let the runner generate
product values and maintain its resume journal. Use restrictive directory and
file permissions. The manual path initializes the private secret store with
`scripts/generate-suite-secrets.py` and renders each product's private values
from a non-secret `site-values.yaml`; the quick runner performs those steps
automatically. Never commit real domains, addresses, values, stores, or hand-off
files. The tool preserves existing secrets across repeated renders and requires
the exact Forge credential hand-off for Link.

## What is in this repository

| Path | Contents |
|---|---|
| [`docs/deploy/`](docs/deploy/) | Public cluster and suite installation runbooks |
| [`docs/deploy-standards.md`](docs/deploy-standards.md) | Public artifact, publication, installation, and acceptance contracts |
| [`deploy/prereqs/`](deploy/prereqs/) | cert-manager CA resources, NFS CSI, and GPU/NPU device plugins |
| [`scripts/generate-suite-secrets.py`](scripts/generate-suite-secrets.py) | Idempotent private secret generation and product-values injection |
| [`scripts/install-suite.sh`](scripts/install-suite.sh) | Optional one-configuration, resumable central-suite installer |
| [`docs/deploy/quick-install.md`](docs/deploy/quick-install.md) | Quick-install configuration, stage, recovery, and external-acceptance guide |

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
