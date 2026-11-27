# Optional Resumable Suite Installation

NereidOverview is an optional quick reference and convenience toolset. It is not
a required deployment controller. Operators can install every product directly
from its owning artifacts and documentation, with their own automation, without
following this guide. The [complete manual suite path](install-suite.md) remains
available and defines the same ordering, security, and acceptance contracts.

The quick installer automates the **central suite** from one non-secret
`deployment.env`. It does not automate cluster creation, DNS/NFS provisioning,
Open Horizon edge onboarding, or ESS model delivery. It uses the rolling
`0.0.0-dev` selectors and still accepts retained legacy
`0.0.0-dev-<short-sha>` selectors for reproducing historical snapshots.

## 1. Prepare the cluster and one configuration file

Start with a ready, empty cluster that satisfies the
[cluster bootstrap guide](cluster-bootstrap.md). Install the host tools listed
in [the suite guide §2](install-suite.md#2-operator-environment), including ORAS,
Helm, kubectl, Python/PyYAML/boto3, `htpasswd`, `envsubst`, and `flock`. Prepare the
NFS export, node NFS clients, selected hardware drivers, DNS records, and TLS
routes before running the installer.

Create the private configuration outside every Git checkout:

```bash
export DEPLOYMENT_ROOT="$HOME/.nereidai-deployment"
install -d -m 700 "$DEPLOYMENT_ROOT"
cp docs/deploy/quick-install.env.example "$DEPLOYMENT_ROOT/deployment.env"
chmod 600 "$DEPLOYMENT_ROOT/deployment.env"
```

Edit that one file. At minimum, replace `BASE_DOMAIN`, `NFS_SERVER`,
`NFS_EXPORT`, and `LINK_MQTTS_HOST`, and confirm `KUBECONFIG`, `KUBECONTEXT`,
`NF_IMAGE_PROFILE`, and `HARDWARE_PLUGINS`. Do not put credentials in this file.
On Linux, `KUBECONFIG` may contain multiple colon-separated files; every
non-empty component must be readable, and kubectl merges them when creating the
private minified copy. The configuration is trusted shell input, so keep it
owned by the current user and inaccessible to group/other users.

The installer generates product values and retains passwords, tokens, and keys
in the persistent files and temporary paths listed in §3. Its own status
messages do not deliberately display retained secret values. Treat every
generated values file, credential handoff, temporary render file, and private
log as sensitive. Back up the deployment root using the site's encrypted-backup
policy. In particular, do not delete the pre `site.env`, suite secret store, NF
secret directory, or Link data/handoffs during recovery.

## 2. Run, inspect, and resume

From the NereidOverview checkout, run:

```bash
scripts/install-suite.sh --config "$DEPLOYMENT_ROOT/deployment.env"
```

Use the same command after a failure, disconnect, or completed external action.
To inspect the local journal without contacting or changing the cluster:

```bash
scripts/install-suite.sh --config "$DEPLOYMENT_ROOT/deployment.env" status
```

### Console progress and private detail

The run command reports stage progress directly on the console. For example,
`11/13 stages complete (85%)` means that 11 of the 13 ordered stages have
completed; it is not an estimate of elapsed time or remaining duration. Each
stage also prints its purpose, private log path, action/verification steps, and
elapsed time. Completed stages are rechecked before they are skipped, and resume
therefore advances quickly through already healthy stages.

During an interactive long-running stage, the console reports elapsed time and
the latest non-secret operational event every 15 seconds. Set
`SUITE_PROGRESS_INTERVAL` to a different positive number of seconds, or to `0`
to disable these periodic messages. Stage start, completion, failure, and
final progress messages remain enabled. Non-interactive runs do not emit the
periodic heartbeat by default.

Success, waiting, and failure summaries include recent filtered activity so the
operator can distinguish the current action without opening the full log. The
filter relays only known operational messages and drops credential-shaped
content. It does not replace or truncate the complete private stage log, which
may contain sensitive values and retains its restrictive permissions.

Only one run may operate on a deployment root at a time. The runner binds its
journal to both the configured kubecontext and the live `kube-system` namespace
UID. Before installation it writes a private mode-`0600` minified kubeconfig
fixed to that context; all Helm, kubectl, pre, and NF child processes use that
copy rather than a mutable shared current-context. The runner rechecks the live
cluster UID around external installer stages and refuses to continue after
either identity changes. It also refuses to adopt existing NereidAI product
releases in any Helm state or any existing product namespace when no
quick-install journal exists; query errors are not treated as absence. Use the
manual recovery procedure for those installations.

### Stage journal

| Stage | Automated work and completion gate |
|---|---|
| `prerequisites` | cert-manager/internal CA, NFS CSI and storage smoke test, selected hardware plugins, CloudNativePG CRDs, persistent suite secret store |
| `identity` | Frozen chart, generated values, Identity installation, CNPG/Keycloak readiness, OIDC discovery |
| `sphere` | Frozen chart, generated values, rollout and readiness endpoint |
| `sphere-acceptance` | Waits for the manual unauthenticated Sphere-to-Identity login flow and ticket verification before Horizon |
| `horizon` | Frozen chart, generated values, backend/frontend rollouts and health endpoints |
| `horizon-acceptance` | Waits for the manual Horizon first-run Setup |
| `pre-artifact` | Independent pre-gate attestation, anonymous installer retrieval/checksum, private pre inputs, fail-closed preflight |
| `pre-infra` | Only the pre infrastructure stage and infrastructure verifier |
| `pre-kubeflow` | Only the Kubeflow stage and Kubeflow verifier; does not rerun infrastructure |
| `pre-verify` | Infrastructure, Kubeflow, Model Registry, and non-secret NF handoff verification |
| `forge` | Independent selected-profile NF-gate attestation, retained NF Secrets, two frozen application charts (consolidated `nereidforge` + `ml-backend`), handoff preflight and rollouts |
| `forge-acceptance` | Exact-commit NF verifier with interrupted-clone repair, manual live acceptance, canonical SeaweedFS-to-Link handoff |
| `link` | Frozen chart, generated values using the exact Forge identity, rollouts, health/MQTT Service checks, successful migration in non-terminating Pods owned by the current Deployment-matching ReplicaSet, and authenticated Forge SeaweedFS bucket verification |

A completed stage is skipped only when its input fingerprint still matches and
its live health check passes. If the marker exists but health fails, the runner
reconciles that stage with the same retained inputs. An interrupted stage is
retried according to its own recovery contract; downstream stages never run
after a failed gate.

Changing the inputs of a completed stage is rejected. Resume is not an upgrade,
rotation, or adoption mechanism. Use a separate reviewed upgrade/recovery plan
for those operations.

### Verifier commit selection

`forge-acceptance` always runs an exact-commit, verification-only checkout of
NereidForge. With a legacy immutable chart (resolved `0.0.0-dev-<sha7>`) the
frozen chart version names that commit directly. A floating `0.0.0-dev` chart
intentionally carries no source identity, so for that chart shape
`NF_VERIFIER_REF` is **required** and must be the reviewed, full 40-character
NereidForge commit ID; the stage fails closed without it. The same variable also
overrides the default commit of an immutable chart when a reviewed fix changes
only the verifier, without republishing or changing the runtime artifacts:

```bash
# Replace this example with the reviewed, full NF commit ID.
export NF_VERIFIER_REF="0123456789abcdef0123456789abcdef01234567"
```

Add the setting to `deployment.env` before the initial acceptance run or while
`forge-acceptance` is incomplete, then rerun the normal command. The value must
be exactly 40 lowercase hexadecimal characters identifying a Git commit;
branches, tags, short SHA values, and malformed references are rejected before
cluster installation begins. Use a commit reachable from the NF repository's
default branch after its PR has been merged.

The override has a separate checkout under `$DEPLOYMENT_ROOT/verifiers/`. It
changes neither `NEREIDFORGE_VERSION` nor any frozen chart or image digest, and
it does not rotate credentials or weaken the verifier's HTTP checks. Leaving it
unset preserves the original checkout path and stage fingerprints. Once an
override is recorded in a completed acceptance stage, changing or removing it
is rejected as a completed-input change. It never substitutes for the manual
`NF_LIVE_ACCEPTANCE_CONFIRMED=yes` attestation.

### Kubeflow apply retry window

The `pre-kubeflow` stage renders each ordered target once and retries transient
API, CRD, and admission-webhook failures using the same rendered bytes. Two
optional, non-secret environment variables control this bounded retry window:

| Variable | Value and behavior |
|---|---|
| `KUBEFLOW_APPLY_ATTEMPTS` | A positive integer setting the maximum apply attempts per target, including the switch to server-side apply after an annotation-size failure. |
| `KUBEFLOW_APPLY_RETRY_DELAY` | A non-negative integer setting the delay between attempts in seconds. |

When either variable is unset, the selected pre installer's built-in default
applies. To make the retry policy explicit across pre artifact versions, add
both values to `deployment.env`:

```bash
export KUBEFLOW_APPLY_ATTEMPTS="40"
export KUBEFLOW_APPLY_RETRY_DELAY="15"
```

This example allows approximately ten minutes of retries per target, which can
accommodate slow initial image pulls while admission webhooks start. For a
single run without editing `deployment.env`, prefix the normal command instead:

```bash
KUBEFLOW_APPLY_ATTEMPTS=40 KUBEFLOW_APPLY_RETRY_DELAY=15 \
scripts/install-suite.sh --config "$DEPLOYMENT_ROOT/deployment.env"
```

These settings change only the apply wait window. They do not modify the
selected immutable artifact, suppress permanent errors, or bypass
`pre-verify`. If the attempt budget is exhausted, the stage still fails closed;
diagnose the cause and resume rather than deleting state or editing the
extracted pre installer.

### External actions and independent Forge gates

The installer pauses with exit code `20` and a named action rather than treating
a Helm command or an attestation as proof of external acceptance:

1. Visit Sphere without an authenticated session, complete the Identity login
   flow and verify a Sphere ticket, then set
   `SPHERE_SSO_ACCEPTANCE_CONFIRMED=yes`. Horizon remains blocked until then.
2. Complete Horizon first-run Setup with the site's actual Open Horizon
   Exchange URL and privileged account, then set
   `HORIZON_SETUP_CONFIRMED=yes`.
3. Verify the selected pre installer and five supporting charts through their
   anonymous publication gate, then set `PRE_GATE_CONFIRMED=yes`. NF publication
   is not required for this pre-only boundary.
4. Before NF applications, independently verify all images in the selected
   profile (`full`: 23; `cpu-xpu`: 18, retaining every Intel XPU image) and
   exactly three NF charts. Then set `NF_GATE_CONFIRMED=yes`.
5. After the exact-commit NF verifier, complete browser SSO/login/logout, a real
   KFP run, Label Studio/CVAT integration, notebook WebSockets, and all four
   SeaweedFS buckets with authenticated list access. Then set
   `NF_LIVE_ACCEPTANCE_CONFIRMED=yes`.

These `yes` values are operator attestations, not evidence generated by the
runner. Leaving any value at `no` blocks the corresponding stage and everything
after it. In particular, Link cannot start before live NF and SeaweedFS
acceptance.

Edit only the waiting stage's attestation, rerun the same command, and leave
completed stages unchanged. Do not set every attestation preemptively merely to
make the command unattended.

## 3. Suite versioning and release tags

Product chart selectors default from one version matrix,
`deploy/suite-versions.yaml`; no product version is hardcoded in the
installer. The installer resolves its channel from this NereidOverview
checkout with the same rule as the product repositories:

- a checkout that is **not** exactly on a `v*` tag (main, feature branches,
  detached work, or a tarball without `.git`) uses the `channels.dev` matrix,
  where every product tracks the rolling `0.0.0-dev` chart;
- a checkout **exactly on a SemVer tag** such as `v0.0.1` uses the
  `releases.0.0.1` matrix, which pins every product to the versions validated
  together for that suite release.

`scripts/install-suite.sh status` prints the active channel or release. The
first pull of each selector is still frozen by the per-product artifact lock
and digest evidence, so a floating `0.0.0-dev` default cannot move under an
already-prepared deployment root, and the stage fingerprints treat version
changes as explicit configuration changes. The freeze holds for both internal
chart versions the pull path accepts: legacy `0.0.0-dev-<sha7>` charts and the
floating NereidForge charts whose own `version` is the bare `0.0.0-dev` tag.

An explicit selector in `deployment.env` (for example
`NEREIDLINK_VERSION=0.0.1`) overrides the matrix default for that product and
remains the supported escape hatch for a reviewed exception. The chart pull
path accepts both development selectors (`0.0.0-dev`, `0.0.0-dev-<sha7>`) and
bare SemVer release selectors; anything else fails closed. Rolling a floating
NereidForge chart forward on purpose means removing that product's lock,
digest intent, completion evidence, and bare-named archive before rerunning,
so the next anonymous resolution freezes a new digest.

### Cutting a suite release

1. Confirm each product's release tag has published its OCI chart with the
   intended bare SemVer version.
2. Add the validated combination to `releases:` in
   `deploy/suite-versions.yaml`, keyed by the bare suite version, and merge it
   to `main`.
3. Tag that commit `vX.Y.Z` and push the tag. The tag-triggered
   `.github/workflows/release.yml` gate resolves the matrix through
   `scripts/lib/suite_versions.py` and fails the release when the entry is
   missing, incomplete, or contains an invalid selector.

Known limitation: the NF verifier and the pre-NereidForge installer still
accept development selectors only. Until those consumers support release
versions, a tagged suite matrix cannot run the NF stages end to end on release
selectors; the tag gate validates matrix shape regardless, and development
deployments from `main` are unaffected.

## 4. Local credential file inventory

The following inventory covers the current quick-install wrapper and its
referenced pre installer and NF verifier. These are files on the operator host,
not Kubernetes Secrets; no credential values are shown here. Live Kubernetes
Secrets remain canonical where the table says so. When selecting a different
immutable pre artifact, verify any artifact-specific differences against that
artifact's own source.

The path aliases below make the exact locations explicit:

| Alias | Expansion |
|---|---|
| `QUICK_VALUES_DIR` | `$DEPLOYMENT_ROOT/quick-install/values` |
| `DEPLOY_VALUES_ROOT` | `${DEPLOY_VALUES_ROOT:-$DEPLOYMENT_ROOT/deploy-values}` |
| `PRE_HANDOFF_DIR` (also `NF_HANDOFF_DIR`) | `$DEPLOY_VALUES_ROOT/nereidforge` |
| `PRE_ENV_FILE` (also `NF_ENV_FILE`) | `$PRE_HANDOFF_DIR/site.env` |
| `NF_SECRET_DIR` | `$DEPLOYMENT_ROOT/secrets/nereidforge` |
| `DEPLOY_LOG_ROOT` | `${DEPLOY_LOG_ROOT:-$DEPLOYMENT_ROOT/deploy-logs}` |
| `PRE_ROOT` | `$DEPLOYMENT_ROOT/pre-nereidforge/$PRE_VERSION/pre-nereidforge-installer-$PRE_RESOLVED_VERSION` |

For example, in the default root-run setup, `$DEPLOYMENT_ROOT` expands to
`/root/.nereidai-deployment`.

### Persistent credential-bearing files

Quick-created secret stores, generated product values, and NF secret files are
mode `0600`; their private parent directories are mode `0700`. A generated or
reproducible copy is still sensitive.

| Exact path | Credential contents and recovery role |
|---|---|
| `$DEPLOYMENT_ROOT/secret-store/suite-secrets.json` | **Canonical local suite store**: Identity PostgreSQL, Keycloak administrator, suite-administrator and admin-client credentials; all four product OIDC client secrets; Sphere session, Valkey and Forge/Horizon/Link ticket secrets; Horizon PostgreSQL; Link JWT and PostgreSQL credentials. It is generated once and never refilled after initialization. |
| `$QUICK_VALUES_DIR/nereididentity.generated.yaml` | Identity PostgreSQL, Keycloak administrator and suite-administrator passwords, admin-client secret, and Sphere/Horizon/Forge/Link OIDC client secrets. Generated from the suite store for Helm. |
| `$QUICK_VALUES_DIR/nereidsphere.generated.yaml` | Sphere OIDC and admin-client secrets, session key, Forge/Horizon/Link `ssoSecret` tickets, and Valkey password when enabled. Generated from the suite store. |
| `$QUICK_VALUES_DIR/nereidhorizon.generated.yaml` | Horizon PostgreSQL password and Sphere Horizon NS ticket; direct-OIDC client secret when that mode is enabled. Generated from the suite store. |
| `$QUICK_VALUES_DIR/nereidlink.generated.yaml` | Link JWT, bundled PostgreSQL password, Link NS ticket or direct-OIDC client secret, and Forge S3 `accessKey`/`secretKey`. Generated from the suite store and canonical Forge handoff. |
| `$PRE_ENV_FILE` (`$PRE_HANDOFF_DIR/site.env`) | `PG_ADMIN_PASSWORD`, `SEAWEEDFS_S3_ACCESS_KEY`, `SEAWEEDFS_S3_SECRET_KEY`, plaintext `DEX_STATIC_PASSWORD`, and bcrypt `DEX_STATIC_PASSWORD_HASH`, together with non-secret pre inputs. Retained pre recovery input; live pre resources become canonical after bootstrap. |
| `$PRE_HANDOFF_DIR/service-tokens.env` | `NEREIDFORGE_LABELSTUDIO_TOKEN` and `NEREIDFORGE_CVAT_TOKEN` integration tokens. Retained handoff required by pre finalization and copied into the NF runtime Secret. |
| `$PRE_HANDOFF_DIR/service-admin-credentials.env` | `LS_ADMIN_PASSWORD` and `CVAT_ADMIN_PASSWORD`, with the corresponding administrator usernames/email. Retained UI-administrator recovery handoff. |
| `$PRE_ROOT/charts/labelstudio/values.yaml` | Label Studio chart `token` used as its static API token, distinct from the later DRF integration token. This is a generated chart input inside the verified pre extraction, not a canonical backup source; do not edit it manually. |
| `$NF_SECRET_DIR/jwt` | `NEREIDFORGE_AUTH_JWT_SECRET`. Retained local mirror of the canonical NF runtime Secret. |
| `$NF_SECRET_DIR/sso-client` | `NEREIDFORGE_SSO_NS_CLIENT_SECRET`, exactly matching the suite store's Forge ticket and the NF runtime Secret. |
| `$NF_SECRET_DIR/admin-password` | NF administrator password. Retained local mirror of canonical `nereidforge/nereidforge-admin-credentials`. |
| `$NF_SECRET_DIR/runtime-secret-patch.json` | NF JWT and Forge SSO secret in `stringData`. Regenerated patch input, not an independent source of truth. |
| `$PRE_HANDOFF_DIR/admin-credentials.env` | Optional legacy `NF_ADMIN_PASSWORD` input read by the NF verifier when present. The quick application-only path does not create it; its NF administrator file is `$NF_SECRET_DIR/admin-password`. |
| `$PRE_HANDOFF_DIR/seaweedfs-credentials.yaml` | Exactly `accessKey` and `secretKey` for Link's Forge S3 access. Generated after NF acceptance from canonical `nereidforge/seaweedfs-s3-credentials` and verified against it on resume. |
| `$DEPLOY_VALUES_ROOT/nereidlink/admin-credentials.env` | `LINK_ADMIN_EMAIL` (`admin@nereidai.local`) and a strong random `LINK_ADMIN_PASSWORD` (48 hex characters). Created only when the installer itself completes Link's one-time first-run bootstrap through a loopback-only Pod port-forward on a kernel-assigned local port (set `LINK_LOCAL_HTTP_PORT` to a positive number to pin one). Absent when the administrator was already initialized out of band (for example through the web UI); in that case the existing password is never reset and no replacement credential is written. |
| `$DEPLOY_LOG_ROOT/nereidlink/api-port-forward.log` | Written only when the loopback forward fails, mode `0600`. It contains kubectl's bind/connection diagnostics (for example an occupied local port), never credentials. |
| `$DEPLOYMENT_ROOT/quick-install/kubeconfig` | Minified, flattened cluster kubeconfig pinned to `KUBECONTEXT`; may contain a client private key, token, client certificate, or exec-credential configuration. |
| `${KUBECONFIG:-$HOME/.kube/config}` | Operator-supplied source kubeconfig(s), including every non-empty colon-separated component. The example uses `$HOME/.kube/nereidai.kubeconfig`; quick-install reads but does not create this source. |

The similarly named manual-path product files under
`$DEPLOY_VALUES_ROOT/<product>/values.generated.yaml` are not the
quick-install outputs; quick-install uses `$QUICK_VALUES_DIR` as listed above.

### Temporary credential-bearing files

These files normally exist only during an atomic rename, preflight, or Kubeflow
render. `RENDER_WORKDIR` is created with `mktemp -d`, normally under `/tmp`, and
the entire render tree is normally removed on exit. A hard interruption can
leave remnants; treat them as sensitive rather than as recovery sources.

| Exact path or pattern | Credential contents and lifetime |
|---|---|
| `$DEPLOYMENT_ROOT/secret-store/.suite-secrets.json.<random>` | Complete suite store during atomic write. |
| `$QUICK_VALUES_DIR/.<product>.generated.yaml.<random>` | Complete private generated values for `nereididentity`, `nereidsphere`, `nereidhorizon`, or `nereidlink` during atomic write. |
| `$PRE_HANDOFF_DIR/.site.env.<pid>.tmp` | Updated pre `site.env`, including all five pre credentials, during atomic write. |
| `$NF_SECRET_DIR/.<filename>.<pid>.tmp` | Temporary `jwt`, `sso-client`, `admin-password`, or `runtime-secret-patch.json` content during atomic write. |
| `$PRE_HANDOFF_DIR/.seaweedfs-credentials.yaml.<pid>.tmp` | Link Forge S3 handoff during atomic write. |
| `$DEPLOYMENT_ROOT/quick-install/kubeconfig.XXXXXX` | Raw minified kubeconfig before rename to `quick-install/kubeconfig`. |
| `$DEPLOYMENT_ROOT/quick-install/dex.XXXXXX` | Temporary htpasswd record containing `dex:$DEX_STATIC_PASSWORD_HASH`; deleted after verification. |
| `$RENDER_WORKDIR/dex-passwords.yaml`, then `$RENDER_WORKDIR/kubeflow-manifests/common/dex/base/dex-passwords.yaml` | Rendered Dex Secret containing the real bcrypt hash before and after its rename within the temporary render tree. |
| `$RENDER_WORKDIR/mlpipeline-minio-artifact-secret.yaml`, then `$RENDER_WORKDIR/kubeflow-manifests/applications/pipeline/upstream/third-party/seaweedfs/base/seaweedfs/mlpipeline-minio-artifact-secret.yaml` | Rendered KFP Secret containing the real SeaweedFS access and secret keys before and after its rename. |
| `$RENDER_WORKDIR/nf-rendered.XXXXXX` | Complete rendered target YAML; Dex and KFP targets contain their rendered Secrets, and other vendored targets can contain static Secret literals. Deleted after each target. |

### Sensitive logs and files that are not password stores

- `$DEPLOY_LOG_ROOT/quick-install/pre-infra.log` and timestamped
  infrastructure logs under `$DEPLOY_LOG_ROOT/pre-nereidforge/`
  can contain Label Studio's static API token. All private logs must therefore
  be protected as sensitive even though they are not intentional password
  stores. `$RENDER_WORKDIR/nf-apply-error.XXXXXX` can also temporarily contain
  an API rejection that echoes rendered Secret data.
- `$DEPLOYMENT_ROOT/deployment.env` is private, trusted, non-secret shell input;
  credential variables are rejected. `$QUICK_VALUES_DIR/<product>.site.yaml`,
  `$PRE_HANDOFF_DIR/values.generated.yaml`, and
  `$PRE_HANDOFF_DIR/operator-values.yaml` are deliberately non-secret.
- `$DEPLOYMENT_ROOT/nereid-internal-ca.crt` and
  `$DEPLOYMENT_ROOT/nereidlink-device-ca.pem` contain public CA certificates,
  not their private keys. Quick-install state and artifact-lock files are also
  intentionally non-secret.

Use the site's encrypted-backup policy for the entire deployment root and the
operator-supplied kubeconfig. Prioritize the canonical suite store, retained
pre inputs and service handoffs, NF secret directory, and Link handoff during
recovery. Generated values, patches, and extracted chart copies remain
sensitive even when they can be reproduced. Never commit or upload any
credential-bearing file listed in this section.

## 5. Artifact and Secret behavior on rerun

The first anonymous chart/pre resolution atomically records its OCI digest
intent before downloading bytes. Retrieval then uses that digest, verifies the
chart blob or published archive checksum, and records the resolved internal
version (a short-SHA version, or the bare `0.0.0-dev` version for a floating
NereidForge chart) and local archive path under
`quick-install/artifact-locks/`. An interrupted run recovers validated bytes or
resumes retrieval by the retained digest without resolving the floating
selector again. Resume reuses those verified bytes even if `0.0.0-dev` later
moves. A missing, mismatched, or corrupt intent, archive, or completion record
fails closed; it does not silently download a newer snapshot.

Rerun behavior is not based solely on local markers:

- product rollouts and public health endpoints are checked before a stage is
  skipped;
- existing CNPG, SeaweedFS, NF runtime, and administrator Secrets remain
  canonical and are never replaced merely because a local file is missing;
- an incomplete existing suite secret store stops byte-for-byte unchanged for
  encrypted-backup recovery or a reviewed migration; `init` never fills missing
  identities with replacements. If the store is lost after prerequisites have
  started, reconciliation stops instead of creating a new store;
- a missing or mismatched retained pre/NF identity stops for recovery rather
  than generating a replacement. Generation is limited to the owning stage's
  first bootstrap. A durable per-stage record written immediately before
  generation survives later `state/current` changes and requires retained
  recovery values, as does a completed owning or later-stage marker. A waiting
  artifact-confirmation gate alone does not create that record. API, RBAC,
  network, and credential helper failures are never treated as proof that a
  canonical resource is absent—only kubectl's explicit server `NotFound` reason
  means absence;
- the storage smoke test refuses unlabeled/foreign resources and only cleans up
  resources carrying its explicit quick-install ownership label;
- the NF Sphere ticket identity is copied from the existing suite store without
  displaying it, and any live mismatch stops;
- Link's private credential handoff is read from the canonical Forge SeaweedFS
  Secret only after NF acceptance; it is never added to `deployment.env`, the
  non-secret NF handoff, state, or command arguments.

Private logs are written under `deploy-logs/quick-install/`. The console prints
stage names and log paths, not log contents or secret values. Do not enable
shell tracing and do not upload deployment roots, generated values, private
logs, credential handoffs, private kubeconfigs, or Secret stores to an issue or
public artifact.

## 6. Finish acceptance separately

A successful final stage means the central Link installation passed its
programmatic gates, including completion of the one-time platform administrator
bootstrap (verified through `GET /v1/auth/bootstrap-status` reporting
`required=false`). It does not replace the
[fresh-cluster checklist](reference/fresh-cluster-checklist.md). Complete the
remaining browser, Link bucket/restart, license, MQTT/edge, Open Horizon
agreement, and independent ESS delivery checks through their owning interfaces,
and store the retained `admin-credentials.env` password in the site vault. Those
operations remain valid whether installation was performed manually, with this
convenience runner, or with entirely different operator tooling.
