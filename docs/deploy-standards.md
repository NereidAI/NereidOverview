# Deployment, Packaging, and Delivery Standards

Suite-wide deployment standard. Governs every product repository's
deployable artifacts (Helm charts, compose files, deploy scripts, CI
workflows) and this NereidOverview repository. One install path must
work both online and in air-gapped customer sites.

Sections 15.1–15.9 are the confirmed product contract. Sections
15.10–15.13 define the release-engineering layer (Mode G / Mode A
delivery): the contracts are normative for new release work; existing
repositories adopt them per the rollout in §15.13.

## 15.1 Canonical deploy layout

All deployment artifacts live under `deploy/`:

- `deploy/helm/<chart-name>/` — Helm chart(s), one chart per deployable
- `deploy/scripts/` — deployment helper scripts (license header required)
- `deploy/compose/` — docker-compose assets, if any

Legacy layouts (`infra/`, `deploy/kubernetes/helm/`) migrate: move,
don't copy; update every internal reference, doc link and workflow in
the same change. Until a product migrates, its actual chart path is
documented in that product's own repository documentation.

## 15.2 Public registries are the only canonical image references

- Suite-owned images: `ghcr.io/nereidai/nereid<product>[-<component>]:<tag>`,
  all lowercase (e.g. `ghcr.io/nereidai/nereidlink:0.0.1`,
  `ghcr.io/nereidai/nereidhorizon-backend:0.0.1`,
  `ghcr.io/nereidai/nereidforge-backend:0.0.1`). Image tags are bare
  SemVer derived from the signed git tag (`v0.0.1` → `0.0.1`, §15.9); no `VERSION` file exists. Legacy image names are renamed in CI,
  charts and docs together in one change.
- Third-party images keep their true upstream coordinates
  (`quay.io/...`, `registry.k8s.io/...`, `ghcr.io/<other-org>/...`,
  `nvcr.io/...`, `gcr.io/...`, `docker.io/library/...` or the
  unqualified official-image name) even when suite CI mirrors them — an
  unmodified upstream image is never re-homed under `nereidai/`.
- Never hardcode an internal registry hostname, Harbor domain, IP, or
  internal project path in committed code, charts, default values,
  scripts, workflows, compose files, or production docs. No chart value
  may default to an internal registry, and no registry-switch value
  (`global.imageRegistry`, etc.) may be added to retarget images at an
  internal Harbor — mirroring is a node-level concern (§15.3), not a
  template parameter.
- Lab/runbook convention: no tracked file spells out a real internal
  registry hostname (§15.3). Runbooks and operator site-value examples
  use the `<harbor-host>` placeholder; the real value lives only in the
  git-ignored `harbor.env` consumed by `deploy/scripts/harbor-sync.sh`, or
  in the operator's untracked `-f` files. Examples must not contain
  secrets and stay outside chart defaults, scripts, and product
  repositories.

## 15.3 Private/air-gapped delivery is deployment-layer only

Internal Harbor acts as a **mirror**, never a dependency baked into a
product. The same chart installs online and offline; the conversion
happens outside product repositories:

- Third-party images: copied public → customer registry with
  skopeo/crane.
- Locally built suite images: built and tagged locally with the canonical
  `ghcr.io/nereidai/...` coordinate and the three-tag scheme (§15.9). Makefiles contain no push action; copying a local build into the
  customer registry goes through NereidOverview `harbor-sync.sh push`
  with a `docker-daemon:` or `oci-archive:` source. The chart reference
  never changes.
- Each cluster node redirects public pulls to the customer registry via
  containerd `/etc/rancher/k3s/registries.yaml` mirror + rewrite.
- Machine-readable image dependency lists:

  - Each product repository may keep an `images.manifest` at its root
    (`# src-ref|dst-ref`, one pair per line) listing its **third-party**
    image dependencies. Suite-owned images are not listed — they are
    built locally by the build-only `make image` targets or published to
    GHCR by the tag-triggered release workflow (§15.9). The manifest
    drives `harbor-sync.sh mirror` and offline-bundle assembly; chart
    references always keep the public source coordinates.
  - NereidOverview owns the manifest for cluster-shared prerequisites
    (`deploy/prereqs/images.md` is the human-readable form, kept in sync
    with the machine-readable `deploy/prereqs/images.txt`). Customer
    target hosts never appear in product repositories; the destination
    prefix is supplied at execution time through the git-ignored
    `harbor.env` and `harbor-sync.sh` (§15.3).
- Product scripts may preflight-check registry reachability and point
  to the NereidOverview mirror guide; they must never self-install a
  mirror, rewrite image names in charts, or embed customer hostnames.

## 15.4 Helm chart rules

- Tracked charts keep the rolling-dev placeholder `appVersion: "0.0.0-dev"`;
  the release's bare SemVer is injected at packaging time with
  `helm package --version/--app-version` (§15.9). No release
  version is ever committed into `Chart.yaml`.
- `helm lint` and `helm template` with default values must always pass;
  defaults target the online path (public images).
- Environment-specific values — domains, passwords, secrets, endpoints,
  StorageClass, nodeSelector — come from the operator's own values file
  (`-f site-values.yaml`). Committed examples (`values-example.yaml`,
  `values-k3s-example.yaml`) contain placeholders only; never a real
  secret.
- Subcharts stay upstream with upstream image references; never fork a
  vendored chart to point it at an internal registry.
- Cluster-shared prerequisites (cert-manager, CSI drivers, device
  plugins, operators) are never subcharted by products — preflight-check
  only and fail with a pointer to `NereidOverview/deploy/prereqs/`.

## 15.5 Chart distribution: local paths first

- The supported install path clones all product repositories side by
  side with NereidOverview and installs from local chart paths
  (`helm upgrade --install x ../NereidX/deploy/helm/x -f site-values.yaml`).
- NereidOverview never vendors product chart `.tgz` files or copies of
  product values; the product repository is the single source of truth.
- ChartMuseum is an optional air-gapped redistribution point only; its
  packages are generated from product sources by script. Hand-edited
  chart forks are forbidden.

## 15.6 English-only documentation

All committed documentation — READMEs, runbooks, manuals, design docs,
all Markdown under `docs/` and `deploy/` — is English-only. The project
does not maintain bilingual documents. (Code comments are English-only.)

## 15.7 NereidOverview boundary

NereidOverview contains documentation and deployment-only tooling:
runbooks, cluster-shared prerequisite manifests/wrappers, image mirror
manifests, and image/chart mirror scripts. It holds no product runtime
code, no product chart copies, and no product values copies; it
references product charts at their source paths in the product
repositories.

## 15.8 Standard Makefile interface

Every product repository has one `Makefile` at its repository root that
is the single entry point for routine operations. Long command sequences
live in make targets (or scripts under `deploy/scripts/` invoked by
them), never as prose for operators to retype.

Standard overridable variables (defaults are always the online/public
path; no internal hostname may appear in the Makefile):

```makefile
REGISTRY   ?= ghcr.io/nereidai   # canonical coordinate; Makefiles never push
# No VERSION file: exact v* tag -> bare SemVer, otherwise the 0.0.0-dev channel
VERSION    ?= $(shell ref=$$(git describe --tags --exact-match 2>/dev/null) && echo "$${ref#v}" || echo 0.0.0-dev)
TAG        ?= $(VERSION)
IMAGE_NAME ?= nereid<product>
IMAGE      ?= $(REGISTRY)/$(IMAGE_NAME):$(TAG)
RELEASE    ?= nereid<product>
NAMESPACE  ?= nereid<product>
CHART_DIR  ?= deploy/helm/<chart>
VALUES     ?=                    # operator-supplied site values; never committed
PLATFORMS  ?= linux/amd64,linux/arm64   # publication index; local make is native
```

Local network acceleration lives in the git-ignored `local.mk`
(`-include local.mk`, tracked `local.mk.example` with empty values,
§15.8); no proxy/mirror endpoint is ever committed.

Multi-component products define `IMAGES ?= nereid<product>-backend ...`
and provide per-component targets.

Standard target names (implement those that apply; do not invent
synonyms):

| Target | Purpose |
|---|---|
| `help` | Default goal; lists targets parsed from `##` comments |
| `fmt` / `lint` / `test` / `build` | Language toolchain per the repo's own documentation; omit `test` only when no framework exists |
| `verify` | Pre-commit gate: format check, lint, test, `helm-lint`, `helm-template` |
| `image` / `image-<component>` | Build/load image(s) locally at the canonical public coordinates; carries the three tags of §15.9, no push |
| `helm-dep` | `helm dependency update $(CHART_DIR)` |
| `helm-lint` / `helm-template` | Validate chart; template with defaults and optional `VALUES` |
| `helm-package` | Package tgz into `dist/charts/` for offline redistribution only |
| `install` / `uninstall` | `helm upgrade --install` with an explicit operator-supplied `VALUES=` (no default site values) / `helm uninstall` |
| `sbom` | Generate `dist/sbom-<image>.spdx.json` with syft (release engineering, §15.10) |
| `scan` | Grype scan of images; fail at the agreed severity threshold (§15.10) |
| `sign` | Cosign-sign image digests and the bundle checksum with the suite key (§15.10) |
| `bundle` | Assemble the offline delivery bundle under `dist/offline/` (§15.10) |
| `dev-up` / `dev-down` / `dev-logs` / `dev-rebuild` | Local compose dev environment |
| `clean` | Remove local build output and `dist/`; never touch images or clusters |

Rules:

- Bare `make` prints `help`; every target carries a trailing `## `
  description.
- Every image build carries the three-tag scheme of §15.9 —
  `$(VERSION)`, `$(VERSION)-<utc-timestamp>` and
  `$(VERSION)-<git-short-sha>` — locally and in publication; `latest`
  is forbidden. Charts pin the VERSION coordinate only. The same commit
  must produce content-equivalent images in CI and in a developer's
  local build (timestamp-only differences allowed).
- CI and docs invoke make targets rather than duplicating docker/helm
  commands. The Makefile must never hardcode an internal registry,
  customer host, or credential, and contains no push target; internal
  delivery uses NereidOverview `harbor-sync.sh` only. Node-level mirror
  configuration stays in NereidOverview (§15.3).
- Tool-specific `fmt`/`lint`/`test`/`build` commands follow each
  repository's verified commands in its own documentation; target names
  stay uniform across products.
- Makefile content and comments are English-only.

## 15.9 GitHub Actions standard

Three pipeline roles cover CI, rolling dev and release (file names
`ci.yml`, `publish-dev.yml` plus `release.yml`, or the established
exceptions `publish.yml` / `publish-images.yml` for multi-target
repositories); no other pipeline duplicates build commands:

- `.github/workflows/ci.yml` — runs on pushes to the default branch and
  PRs targeting it; no secrets; `permissions: contents: read`;
  concurrency group `ci-${{ github.ref }}` with
  `cancel-in-progress: true`. Test/lint/verification jobs invoke only
  Makefile gates (e.g. `make helm-dep` then `make verify`); multi-language
  repos may split parallel jobs, each still calling make. Repositories
  that publish images additionally run a cache-warm job, which uses
  `docker/build-push-action@v6` directly (see the cache rule below)
  because the `gha` cache backend is unavailable to a shell `buildx`.
- `.github/workflows/publish-dev.yml` — triggered only by pushes to the
  default branch, never by pull requests (forks cannot publish). It is a
  thin caller of the organization
  `NereidAI/.github/.github/workflows/publish-dev-image.yml` (pinned at a
  semver ref) and publishes the rolling channel: floating `0.0.0-dev`
  plus immutable `0.0.0-dev-<short-sha>`, one index digest,
  `cancel-in-progress: false`. Multi-image repos have one caller job per
  image with the same cache scopes as their warm jobs. Hardware-bound
  vendor/trainer images stay release-only.
- `.github/workflows/release.yml` — triggered only by pushing a new
  `v*` tag; no `workflow_dispatch`, no branch/PR publication. Product
  repositories keep a thin caller of the organization reusable workflow
  `NereidAI/.github/.github/workflows/release-image.yml` (pinned at a
  semver ref), which owns QEMU/buildx setup, GHCR login with the
  built-in `GITHUB_TOKEN`, SemVer tag validation, bare-VERSION derivation
  and injection, and the three-tag `docker/build-push-action`
  publication. Callers never pass a `VERSION` build-arg themselves.
  Repositories with specialized vendor jobs (NereidForge) keep the same
  action chain inline. No third-party registry credentials; internal
  delivery never goes through GitHub Actions.

Version rules (§15.9):

- No product repository tracks a `VERSION` file. The git tag is the
  single version source, keeps the leading `v` (`v0.0.1`), and must
  match `^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$`; the reusable
  workflow fails fast on any other shape.
- The workflow strips the leading `v` to derive bare `VERSION`
  (`0.0.1`); the tag triggers the run but image coordinates never carry
  the prefix. Non-tag checkouts and branch builds use the fixed
  `0.0.0-dev` channel.
- Images are published with exactly the three tags of §15.9:
  `ghcr.io/nereidai/...:$(VERSION)`, `:$(VERSION)-<utc-timestamp>` and
  `:$(VERSION)-<git-short-sha>`. The `latest` tag is forbidden; chart
  values/defaults always pin the VERSION coordinate (the in-branch
  placeholder being `0.0.0-dev`).
- Repository tag protection on `v*` and secret-scanning push protection
  are mandatory compensating controls before a repository is made
  public.
- Every published suite image is a `linux/amd64,linux/arm64`
  multi-architecture index (§15.9); hardware-bound vendor
  trainer images with no upstream arm64 base are the only single-arch
  exception, each registered in the repository's own documentation
  (NereidForge ADR-012). Local `make` builds stay native/single-arch.
- Release and branch CI share the GitHub Actions buildx layer cache
  (`type=gha`): each repository's branch/PR pipeline runs a cache-warm
  job built with `docker/build-push-action@v6` (`push: false`,
  `cache-from/to: type=gha`) over the same architectures and inputs as
  the release — never a raw `docker build` shell step, and no cache
  machinery in the Makefile. A cold or expired cache transparently
  falls back to a full build. Cross-workflow artifact hand-off to the
  release run is forbidden (§15.9); large vendor image sets that
  outgrow the GHA cache quota switch to `type=registry` against a
  dedicated GHCR cache repo.

Workflows are hand-written YAML and carry the standard license header
with English comments; action versions are pinned. Repositories may
consume the organization reusable workflows (§15.10) instead of inline
job definitions but keep the same two file names. Charts are never
auto-pushed to a chart repo by CI (local-path distribution per §15.5);
`helm-package` feeds the offline bundle only. After the first release,
new GHCR packages must be set to Public visibility once in the
organization package settings.

## 15.10 Delivery modes: Mode G and Mode A

Commercial premise: the open-source path (GitHub) feeds the community;
air-gapped delivery (Mode A) is the paid private deployment. Both paths
share one build definition and diverge only in execution environment
and artifact destination.

| Term | Meaning |
|---|---|
| **Mode G** (GitHub) | A `v*` tag triggers GitHub Actions: source build → multi-arch images → GHCR → SBOM/scan/sign → GitHub Release assets. Serves community users and evaluators. |
| **Mode A** (air-gap) | Signed delivery bundle imported into the customer registry; the site only installs (Tier-1 products may optionally build from source on site). Serves private-deployment customers. |
| **Bundle** | `dist/offline/<name>-<version>/` directory: image tars + charts + optional source package + manifest + checksums + signature. The Mode G Release asset and the Mode A deliverable are **the same bundle**. |
| **Tier-1 / Tier-2** | On-site buildability classification: Tier-1 = pure Go/Node, source buildable on site; Tier-2 = ML/heavy-dependency images, prebuilt images only. See §15.11. |

Invariants holding in both modes:

1. **One build definition** — build logic exists only in Makefile
   targets and Dockerfiles; the workflow is a caller (login,
   orchestration, upload). A build step that exists only in CI YAML is
   a violation.
2. **Single version source** — `VERSION` drives image tags, chart
   versions, bundle name and release name (§15.8/§15.9).
3. **Single image-list source** — `images.manifest` (§15.3); human
   docs are generated from it or reconciled by CI, never maintained in
   parallel.
4. **Air-gap default** — the bundle is self-contained; installation
   makes zero external calls (see §15.10).
5. **Offline-verifiable signatures** — verification must complete with
   no internet access (no Rekor/tlog online lookup).
6. **Fork-safe CI** — PR/branch CI needs no secrets; secrets exist only
   in the tag-triggered release path.

### Bundle layout

```text
dist/offline/<name>-<version>/
├── bundle.manifest                       # JSON, see below
├── images/                               # docker-save tars, named by digest
├── charts/                               # helm package output
├── manifests/                            # kustomize sources for customer overlays
├── src/<name>-<version>-src.tar.gz       # Tier-1 only: source + vendor/ + offline caches
├── install.sh                            # offline install entry; installs, never builds
├── SHA256SUMS                            # checksums of every file above
├── SHA256SUMS.sig                        # cosign signature over SHA256SUMS
└── cosign.pub                            # suite verification public key
```

`bundle.manifest` is JSON with at least: `schema:1`, `name`, `version`,
`git_sha`, `build_time`, `tier`, `images:[{repo,tag,digest}]`,
`charts:[{name,version}]`.

### Signing

- One suite cosign ed25519 key pair. The private key is stored encrypted
  in each product repo's GitHub secrets (`COSIGN_PRIVATE_KEY`,
  `COSIGN_PASSWORD`); the public key is committed at
  `NereidAI/.github/cosign.pub` and embedded in every bundle.
- No keyless/Rekor: keyless verification depends on the online
  transparency log and cannot complete air-gapped.
- Images: `cosign sign --key env://COSIGN_PRIVATE_KEY <digest>` — sign
  the digest, never a tag.
- Bundle: sign `SHA256SUMS`, producing `SHA256SUMS.sig`.
- Customer verification is fully offline:
  `cosign verify --key cosign.pub <image>` and checksum-signature
  verification. When the customer Harbor uses intercepted/self-signed
  TLS, the delivery doc must state the exact boundary for
  `--allow-insecure-registry`.

## 15.11 On-site source build tiers (optional Mode A capability)

| Tier | Products | Bundle contents | On-site prerequisites |
|---|---|---|---|
| **Tier-1** | NereidLink, NereidEdge, NereidSphere, NereidHorizon, face-service, NereidIdentity | Source package, Go `vendor/` (generated at packaging), Node offline cache (`npm pack` set or node_modules tar), base image tars (golang/node) | Docker plus Go/Node toolchain; `make build && make image` (build-only, three tags, no push), then `harbor-sync.sh push docker-daemon:<ref> <target>` per §15.3/§15.9 |
| **Tier-2** | NereidForge, NereidHorizon (when ML/heavy frontend deps apply) | Prebuilt images plus source for audit only; buildability not promised | No on-site build; persistent customer demand is handled as staffed custom delivery |

New products default to Tier-1 design (vendorable dependencies,
obtainable base images). Introducing a dependency that cannot be closed
offline (CUDA/ROCm, large Python closures) drops the product to Tier-2,
recorded in the bundle manifest's `tier` field.

## 15.12 Organization reusable workflows and NereidOverview CI

Shared pipeline definitions live once in `NereidAI/.github` and are
consumed by product repos with major tags (`@v1`, never `@main`):

```text
NereidAI/.github/
├── cosign.pub
├── README.md                             # three-step onboarding
└── .github/workflows/
    ├── _ci.yml                           # workflow_call: inputs.language, workdir
    ├── _release-image.yml                # inputs: name, dockerfile, context, platforms
    ├── _sbom-scan-sign.yml               # inputs: image@digest
    └── _offline-bundle.yml               # inputs: name, version, images.manifest
```

Product repositories keep only the two thin caller files (`ci.yml`,
`release.yml`) per §15.9. NereidHorizon's existing multi-arch
`publish.yml` is the reference prototype for `_release-image.yml`;
NereidLink's ADR-0031 already follows the same CI/release split and its
differences are reconciled when onboarding.

NereidOverview builds no images. Its CI enforces deployment-artifact
consistency:

Safe on GitHub-hosted runners (PR gate):

- `helm lint` + `helm template` for wrapper charts, both default values
  and `values-prod.yaml` (`nfs-csi`, `cert-manager-kubeflow-hook`);
- kubeconform schema validation of every `device-plugins/` manifest;
- machine-readable image list ↔ `deploy/prereqs/images.md`
  reconciliation (render drift fails the job);
- relative-link checking across all docs;
- gitleaks secret scan.

Local only (the site registry is not reachable from GitHub runners),
all via `deploy/scripts/harbor-sync.sh` with the git-ignored
`harbor.env` (§15.3):

- `harbor-sync.sh check` — validate the host configuration and
  skopeo/crane tooling;
- `DRY_RUN=1 harbor-sync.sh mirror deploy/prereqs/images.txt` — preview
  every planned prerequisite copy without contacting a registry;
- `harbor-sync.sh mirror deploy/prereqs/images.txt` — perform the
  mirroring once the preview is reviewed.

A future lab self-hosted runner (`[self-hosted, lab]` labels) may move
the two local checks into CI.

End-to-end flow:

```text
                    ┌── Mode G ────────────────────────────────────────
git tag vX.Y.Z ─────┤  CI gate → buildx multi-arch → GHCR → SBOM/grype
                    │       → cosign → GitHub Release (bundle + checksums)
                    │       → community: docker pull ghcr.io/… or bundle
                    └── Mode A ───────────────────────────────────────
same bundle ────────┤  release engineer: harbor-sync.sh mirror/push
(or same commit)    │       (harbor.env supplies the customer host)
                    │       → import → cosign verify → install.sh
                    │       → Tier-1 optional: on-site make build/image
                    │       → runbook rehearsal gate
```

The release asset and the customer deliverable being the same bundle
eliminates "community and customer got different builds" incidents.

## 15.13 Rollout and open questions

Rollout order (owners self-pace; this document sets the standard):

1. **Phase 1** — `NereidAI/.github`: four reusable workflows,
   `cosign.pub`, onboarding doc; `_release-image.yml` prototyped from
   NereidHorizon's publish workflow.
2. **Phase 2** — NereidOverview: machine-readable prerequisite image
   list generated from `images.md`; PR-gate CI per §15.12.
3. **Phase 3** — product repositories onboarding one by one (thin
   `ci.yml`/`release.yml`, Makefile contract, `images.manifest`);
   §15 compliance work is the vehicle.
4. **Phase 4** — first end-to-end rehearsal: tag → Release → bundle →
   lab registry → clean-node air-gapped install ("signed offline bundle +
   air-gapped install rehearsal" gate; the original v0.0.1 release plan is
   retained in the internal repository's archive).

Open questions (not ruled on by this standard):

- Whether a lab self-hosted runner is provisioned (moves the two local
  checks into CI).
- Whether the lab registry is ever internet-reachable; today it is not,
  so the community path relies on GHCR only.
- arm64 build scope per product (a real edge-gateway requirement for
  NereidEdge vs. opportunistic elsewhere).
- How enterprise-only code is isolated (separate repo / build tags /
  config switches) — a legal and product decision outside this
  document.

## 15.14 Runtime mode support boundaries

Run modes are not interchangeable, and every product repository must state
the support boundary in its root `README.md`, using the same three-tier
wording as the NereidOverview root README ("Deployment modes and support
boundaries"):

| Run mode | Allowed purpose | Production support |
|---|---|---|
| Dev mode (host processes, `make dev`, `configs/dev.yaml`, language dev servers) | Development and debugging only | Never |
| Docker / Docker Compose mode (single-host container stacks) | Testing, demos, image verification and local evaluation; selected stacks also run single-host, edge or air-gapped appliance deployments | Partial — only a product's explicitly documented production Compose path, within its stated limits; no clustering, high availability or horizontal scaling |
| Kubernetes mode (Helm charts on k3s/Kubernetes) | Full-featured production deployment | Yes — strongly recommended; the full-functionality form (HA, horizontal scaling, multi-tenancy) |

Rules:

1. The notice applies to platform products: NereidIdentity, NereidSphere,
   NereidLink, NereidHorizon and NereidForge. Each product README marks its
   dev section "development only", and distinguishes trial/demo Compose assets
   from any production Compose path it documents, pointing full-featured
   production deployments at the Helm/Kubernetes path.
2. Edge products (NereidEdge, NereidInference) have no Kubernetes mode.
   Their production deployment form is the Open Horizon service definition,
   delivered and managed by NereidHorizon; their Compose-based stacks are
   development and testing only, and their READMEs must say so explicitly.
3. A Compose path may be called production-supported only when the product
   README names it explicitly, ships a hardening checklist (TLS, persisted
   volumes, injected secrets) and states its capability limits (single host;
   no clustering, HA or horizontal scaling). Trial overrides and
   `docker-compose.dev.yml`-style assets must be labeled non-production.
   Vague synonyms such as "lab production" or "small-scale production" are
   forbidden — say either "production Compose path" with its limits, or
   "testing/demo only". Architecture descriptions of a single-binary/
   all-in-one image remain allowed (the same image runs in Kubernetes with
   role split); the restriction is on the *run mode*, not on the image.
4. Dev-only defaults (`changeme*` credentials, seeded users, exposed
   database ports, disabled secret stores) must stay confined to dev and
   trial/demo Compose assets; production Compose paths and Helm charts alike
   require operator-injected secrets and keep the chart's `required`-secret
   behavior.
5. The canonical wording lives in the NereidOverview root README; product
   READMEs adapt the section names to their existing structure but keep the
   three support levels (never / partial with stated limits / strongly
   recommended full-featured) identical.
