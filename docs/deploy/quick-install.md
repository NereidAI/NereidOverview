# Optional Resumable Suite Installation

NereidOverview is an optional quick reference and convenience toolset. It is not
a required deployment controller. Operators can install every product directly
from its owning artifacts and documentation, with their own automation, without
following this guide. The [complete manual suite path](install-suite.md) remains
available and defines the same ordering, security, and acceptance contracts.

The quick installer automates the **central suite** from one non-secret
`deployment.env`. It does not automate cluster creation, DNS/NFS provisioning,
Open Horizon edge onboarding, or ESS model delivery. It currently accepts only
the reviewed `0.0.0-dev` and immutable `0.0.0-dev-<short-sha>` selectors.

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

The installer generates product site values and retains passwords, tokens, and
keys in separate mode-`0600` files under `DEPLOYMENT_ROOT`. It never prints
those values. Back up the deployment root using the site's encrypted-backup
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
| `forge` | Independent selected-profile NF-gate attestation, retained NF Secrets, three frozen application charts, handoff preflight and rollouts |
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
   exactly four NF charts. Then set `NF_GATE_CONFIRMED=yes`.
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

## 3. Artifact and Secret behavior on rerun

The first anonymous chart/pre resolution atomically records its OCI digest
intent before downloading bytes. Retrieval then uses that digest, verifies the
chart blob or published archive checksum, and records the immutable version and
local archive path under `quick-install/artifact-locks/`. An interrupted run
recovers validated bytes or resumes retrieval by the retained digest without
resolving the floating selector again. Resume reuses those verified bytes even
if `0.0.0-dev` later moves. A missing, mismatched, or corrupt intent, archive,
or completion record fails closed; it does not silently download a newer
snapshot.

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

## 4. Finish acceptance separately

A successful final stage means the central Link installation passed its
programmatic gates. It does not replace the
[fresh-cluster checklist](reference/fresh-cluster-checklist.md). Complete the
remaining browser, Link bucket/restart, administrator bootstrap, license,
MQTT/edge, Open Horizon agreement, and independent ESS delivery checks through
their owning interfaces. Those operations remain valid whether installation was
performed manually, with this convenience runner, or with entirely different
operator tooling.
