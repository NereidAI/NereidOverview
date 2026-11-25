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

An ungated installation example or availability claim may reference a chart or
image coordinate only after that exact version has passed anonymous pull
verification. CI success alone does not prove public availability. A gated
runbook may describe a development coordinate before its first complete
publication only when it explicitly stops installation until the anonymous
artifact gate passes and never asserts that the artifact is already available.

## 15.2 Chart source and metadata

- Product chart source stays in its product repository. NereidOverview never
  vendors a product chart archive, chart copy, or product values copy.
- Tracked first-party product charts use `version: 0.0.0-dev` and
  `appVersion: "0.0.0-dev"`. Packaging injects the selected version; a release
  version is not committed back into `Chart.yaml`.
- First-party image tags default to `.Chart.AppVersion`. A chart resolved
  through the floating development selector retains its immutable `appVersion`
  and therefore selects the matching immutable images.
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

A push to the default branch first publishes every required product image. Each
image's `0.0.0-dev-<short-sha>` and `0.0.0-dev` tags share one index digest.
Only after all required images succeed does chart publication:

1. package and verify one immutable `0.0.0-dev-<short-sha>` chart whose
   `appVersion` selects the matching immutable images; then
2. attach the floating `0.0.0-dev` OCI tag to that exact chart manifest.

The floating chart tag must never identify a separately packaged `0.0.0-dev`
archive. Its OCI digest and pulled `.tgz` bytes must equal the immutable
snapshot's. A failed image or chart publication leaves the previous floating
chart snapshot in place.

Normal development installations use `0.0.0-dev`; no per-commit edit is needed.
Record the resolved chart OCI digest, its internal short-SHA version, and the
running image digests. Select `0.0.0-dev-<short-sha>` directly only for a
deliberate reproducible snapshot.

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
packages must be publicly visible before the release is accepted. Every selector
referenced by the installation guide then passes a separate anonymous chart
pull/render and anonymous image-manifest check. For the development channel,
verification also proves that floating and immutable chart tags resolve to the
same OCI digest and byte-identical archive.

## 15.4 Forge development boundary

The complete Forge development snapshot comprises the independent
pre-NereidForge ORAS installer and five supporting charts, followed by exactly
three NF charts and one selected NF image profile: all 23 images for `full`, or
18 core/CPU/Intel-XPU images for `cpu-xpu`. The latter excludes only the five
AMD/NVIDIA trainer images; Intel XPU images remain mandatory. A formal release
is not required. The third NF chart, `nereidforge-tenant-check`, is
verification-only; only the consolidated `nereidforge` chart (API, worker, and
the embedded SPA frontend) and the ML backend chart install applications.
There is no NF source-installer artifact.

Backend/frontend images or a subset of charts alone are not a complete Forge
installation channel. The gates are independently enforceable: the anonymously
verified pre installer and five supporting charts permit pre-only §7.2, while
every image in the selected `full` or `cpu-xpu` profile and all three NF charts
must pass their separate anonymous gate before NF §§7.3–7.5. Record the image
profile, each resolved immutable version, OCI digest, and source commit. Missing
NF evidence stops the operator after pre acceptance; it
does not block or invalidate a pre-only installation. Do not claim a complete
public Forge snapshot until both gates pass. Artifact availability does not
waive live NF and SeaweedFS acceptance, which remains mandatory before Link.

Every required image job must succeed before NF chart publication; upstream
wrapper metadata remains independent. Immutable artifacts must never be
overwritten by a rerun. The legacy Kubeflow Helm umbrella is not an installation
artifact; Kubeflow integration uses the pre installer's verified ordered
Kustomize stages and vendored manifests.

## 15.5 Central installation contract

The supported platform form is Kubernetes with Helm. Every phase is verified
before the next phase starts. Operators may use the complete manual runbook,
the optional resumable convenience installer, or independent procedures and
tooling. Automation does not weaken any artifact, ordering, Secret-retention,
or acceptance gate, and NereidOverview is not a required deployment controller.

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
health checks, and stop conditions for each product. The optional convenience
runner must preserve those inputs and gates, record OCI digest intents before
download and freeze resolved artifacts for a partial installation, refuse
concurrent or cross-cluster resume, pin child processes to a private kubecontext,
and recheck live health before skipping a completed stage. Resource query errors
must not be treated as absence, and unowned storage resources must not be adopted
or deleted. A successful Helm command or a local completion marker alone is not
acceptance.

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
- The suite secret generator uses a persistent mode-`0600` store, never prints
  secret material, preserves existing values across renders, and shares values
  only across explicit inter-product contracts. Site values remain separate
  from generated private values.
- The quick installer's single environment file contains no credentials. Its
  state journal contains only stage status, cluster identity, and non-secret
  input/artifact fingerprints. Existing canonical Kubernetes Secrets remain
  authoritative; resume never generates replacements for an existing identity.
  Private minified kubeconfigs and malformed-YAML diagnostics receive the same
  restrictive-permission and source-content-suppression treatment as credentials.
- Externally issued credentials, including Forge SeaweedFS and Open Horizon
  accounts, must come from their actual systems; the generator must not invent
  replacements. Link's device CA and Horizon's chart-generated session key
  remain product-owned.
- Secret values are never printed in documentation, CI logs, shell tracing,
  command-line `--set` arguments, or acceptance output.
- Commands in the runbook are executed by the operator. Documentation changes
  and CI validation do not authorize mutation of a cluster or edge host.

## 15.8 Documentation and acceptance

- Documentation and code comments are English-only.
- Keep the order, prerequisites, values names, chart versions, and verification
  commands consistent across the README, installation guide, and checklist.
- Use the verified floating `0.0.0-dev` selector in normal development examples.
  Immutable short-SHA pins are optional snapshot inputs and formal examples use
  bare SemVer; every referenced selector must pass §15.3 verification.
- Do not claim an OCI package, Release installer, manifest, or edge package is
  available until it exists and its public retrieval has been verified.
- Record the selected selector, resolved chart OCI digest/internal version,
  running image IDs/digests, and source commit in the development or release
  hand-off.
- Finish with the fresh-cluster checklist, including SSO, product health,
  SeaweedFS-backed Link storage, MQTT, Open Horizon agreements, and separate ESS
  model delivery.
