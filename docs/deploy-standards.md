# Public Deployment, Packaging, and Delivery Standards

This standard governs the NereidAI internet installation path. Products are
installed on Kubernetes from versioned GHCR OCI charts and public images.
NereidOverview owns suite documentation and cluster-shared prerequisites; each
product repository remains the source of truth for its own charts and release
workflows.

## 15.1 Public artifact coordinates

- Suite images use `ghcr.io/nereidai/<image-name>:<tag>` in lowercase.
- Suite charts use `oci://ghcr.io/nereidai/charts/<chart-name>` with an explicit
  `--version`.
- Third-party images retain their upstream coordinates and pinned versions.
  They are not re-homed under the NereidAI organization.
- Tracked configuration contains no site registry, credentials, real domain,
  or real host address. Operators supply domains, endpoints, and secrets through
  untracked values files.
- Installation requires internet access from the operator host and cluster
  nodes to every referenced public artifact registry.

A chart or image coordinate may be added to public installation documentation
only after that exact version has passed anonymous pull verification. CI success
alone does not prove public availability.

## 15.2 Chart source and metadata

- Product chart source stays in its product repository. NereidOverview never
  vendors a product chart archive, chart copy, or product values copy.
- Tracked first-party product charts use `version: 0.0.0-dev` and
  `appVersion: "0.0.0-dev"`. Packaging injects the selected version; a release
  version is not committed back into `Chart.yaml`.
- First-party image tags default to `.Chart.AppVersion`, so an immutable chart
  selects the matching immutable images.
- Upstream wrapper charts retain their own `version` and `appVersion`. A suite
  release must not overwrite independent upstream metadata.
- Dependencies are locked. Publication registers declared public HTTPS
  repositories, runs `helm dependency build`, and never depends on a runner's
  pre-existing repository configuration.
- Every packaged chart passes `helm lint` and `helm template`. The rendered
  output is checked for suite-image/version mismatches in inline references,
  structured image fields, and embedded YAML configuration.
- Cluster-shared prerequisites are installed and verified centrally before any
  product. Product charts only preflight them.

## 15.3 OCI publication

The organization reusable workflow is
`NereidAI/.github/.github/workflows/publish-chart.yml@v1`. Product repositories
keep thin callers and use the same implementation for both channels.

### Development channel

A push to the default branch first publishes every required product image, then
publishes:

1. `0.0.0-dev-<short-sha>` — immutable and suitable for a reproducible Lab/POC;
2. `0.0.0-dev` — the floating channel head.

The chart's `appVersion` equals its chart version. The floating version is not a
reproducible deployment input and must not be used when an exact installation
record is required.

### Formal-release channel

A new protected `v*` tag publishes the required images before any chart. The tag
uses strict SemVer without build metadata, and artifact coordinates remove the
leading `v`. Product chart `version` and `appVersion` both become that bare
version. Upstream wrapper metadata remains unchanged.

Formal images carry the bare version plus timestamp- and commit-qualified
traceability tags. Generic product images are multi-architecture indexes;
documented hardware-bound Forge images are the single-architecture exceptions.

### Publication verification

Every OCI push uses Helm registry authentication, is pulled back
authenticated, and is compared byte-for-byte with the pushed archive. New GHCR
packages must be publicly visible before the release is accepted. Every version
referenced by the installation guide then passes a separate anonymous chart
pull/render and anonymous image-manifest check.

## 15.4 Forge release boundary

Forge's rolling channel publishes backend and frontend images only. It is not a
complete Forge installation channel. Do not publish or document a partial Forge
chart channel.

No complete formal Forge release has currently passed anonymous public
verification. Until one selected formal version's complete required images,
active charts, installer, checksums/manifests, and staged installation procedure
have all been retrieved and verified anonymously, do not name individual Forge
release assets or chart coordinates, provide their URLs, or claim that a
supported Forge installation channel exists.

After that gate is satisfied, document only the verified version and its actual
artifact metadata. Every required image job must succeed before chart
publication; upstream wrapper metadata remains independent. A published Release
and its existing assets are immutable and must never be replaced by a rerun.
The legacy Kubeflow Helm umbrella is not an installation artifact; Kubeflow
integration uses the selected release's verified Kustomize stages and vendored
manifests.

## 15.5 Central installation contract

The supported platform form is Kubernetes with Helm. Every phase is run
manually by the operator and verified before the next phase starts.

The strict product order is:

**NereidIdentity → NereidSphere → NereidHorizon → NereidForge → NereidLink**

- Identity establishes the suite realm and product clients.
- Sphere consumes Identity and supplies the suite ticket/session layer.
- Horizon consumes Identity/Sphere and is initialized before model delivery.
- Forge must complete its infrastructure, Kubeflow integration, applications,
  and verification before Link starts.
- Link requires Forge SeaweedFS from its first installation. It uses the exact
  Forge S3 endpoint, bucket credentials, and CA configuration; a temporary
  object-store substitute is not supported.

The installation guide must give explicit values inputs, ordered commands,
health checks, and stop conditions for each product. A successful Helm command
alone is not acceptance.

## 15.6 Edge delivery contract

Field gateways are delivered after Link is healthy. The operator performs these
steps separately and confirms each result:

1. Register the edge host with Open Horizon using the generated registration
   inputs.
2. Deliver the NereidEdge/NereidInference service Pattern and wait for the
   agreement and service containers to become healthy.
3. Create one Link gateway credential pair per edge host and configure
   NereidEdge with the Link MQTT endpoint, edge ID, credentials, and device map.
4. Verify the NereidEdge health endpoint and Link heartbeats/telemetry.
5. Deliver each model through ESS as a separate operation and verify its receipt
   and inference status.

Pattern/agreement delivery does not prove that a model was delivered. Model
verification remains an independent ESS and edge acceptance step.

## 15.7 Operator values and secrets

- Site values, credentials, keys, license material, and generated hand-off files
  live only in the operator's untracked deployment directory with restrictive
  permissions.
- Committed examples contain placeholders, never usable shared secrets.
- Every required password, OIDC client secret, session key, database credential,
  and object-store credential is generated or explicitly supplied for the
  installation.
- Secret values are never printed in documentation, CI logs, shell tracing, or
  acceptance output.
- Commands in the runbook are executed by the operator. Documentation changes
  and CI validation do not authorize mutation of a cluster or edge host.

## 15.8 Documentation and acceptance

- Documentation and code comments are English-only.
- Keep the order, prerequisites, values names, chart versions, and verification
  commands consistent across the README, installation guide, and checklist.
- Pin exact versions in examples. Replace examples only with versions that have
  passed the public verification in §15.3.
- Do not claim an OCI package, Release installer, manifest, or edge package is
  available until it exists and its public retrieval has been verified.
- Record the selected chart version, image version, and source commit in the
  Lab/POC or release hand-off.
- Finish with the fresh-cluster checklist, including SSO, product health,
  SeaweedFS-backed Link storage, MQTT, Open Horizon agreements, and separate ESS
  model delivery.
