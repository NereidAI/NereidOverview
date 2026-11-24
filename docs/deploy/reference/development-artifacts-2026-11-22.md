# Anonymous Development Artifact Evidence — 2026-11-22

This is a historical verification snapshot, not the routine installation
selector. Normal development installation continues to use `0.0.0-dev`; do not
update this page after every commit. A later deployment records its own resolved
chart digest/internal version and running image digests. Use the immutable tags
below only when deliberately reproducing this verified snapshot.

Verification ran anonymously on 2026-11-22 UTC with empty Helm and Skopeo
registry credentials. For every chart, the floating and immutable tags returned
the same raw OCI manifest and digest. Independent Helm pulls produced
byte-identical `.tgz` archives whose `version` and `appVersion` both equal the
listed immutable version.

## Resolved chart snapshot

Chart repositories are `ghcr.io/nereidai/charts/<product>`.

| Product | Immutable chart version and appVersion | OCI manifest digest | Publication run |
|---|---|---|---|
| Identity | `0.0.0-dev-c0354e9` | `sha256:0a2ec369b9ebaf29bf07a3810bfd185b1830a1ae881dc92be3f64149f681c594` | [45040905707](https://github.com/NereidAI/NereidIdentity/actions/runs/45040905707) |
| Sphere | `0.0.0-dev-7fd7a44` | `sha256:adbf1e08d26ce3a2ee7b88d931849607715328482626ca831d245252c3b38637` | [45040904985](https://github.com/NereidAI/NereidSphere/actions/runs/45040904985) |
| Horizon | `0.0.0-dev-bfc731d` | `sha256:9dda9bfa8861714ab2c938c1e75260370b2ea383363536fad2eff8f1efccd7d0` | [45040905094](https://github.com/NereidAI/NereidHorizon/actions/runs/45040905094) |
| Link | `0.0.0-dev-5b330be` | `sha256:8c4809747bb32b4e4d3ca48aecd5188df92d4efba634216d77def28c8e9971c6` | [45040959053](https://github.com/NereidAI/NereidLink/actions/runs/45040959053) |

## Resolved first-party image snapshot

Each chart rendered the immutable image tag below. Anonymous image-manifest
inspection confirmed that `0.0.0-dev` and that immutable tag identified the same
index digest. Images below are in the `ghcr.io/nereidai/` namespace.

| Image | Immutable tag | Image index digest |
|---|---|---|
| `nereididentity-bootstrap` | `0.0.0-dev-c0354e9` | `sha256:8aea176006718263bf92a6444e22eaed33c672bf0d2f9e2cee6642fc5b9767e2` |
| `nereidsphere` | `0.0.0-dev-7fd7a44` | `sha256:d9650ad89a6d04f72111008da30c41c3ced8c2b77daac218b5adadf12ee20b9b` |
| `nereidhorizon-backend` | `0.0.0-dev-bfc731d` | `sha256:6d3f55dd67c7cf1da9de0e59fc0f22834b8dd2d73b7cec9fac3aeb76b604ba4c` |
| `nereidhorizon-frontend` | `0.0.0-dev-bfc731d` | `sha256:24c80bcd4e89982ea97bf4eda591f35be7deb4171593503e12e3ba60a2413c1a` |
| `nereidlink-backend` | `0.0.0-dev-5b330be` | `sha256:d3de37d9524f67314255c8802e8b8379dad323d8e01d1acb904d0b5594d496e4` |
| `nereidlink-frontend` | `0.0.0-dev-5b330be` | `sha256:0393f6dc66bc859c1dcac3dd8b22753b317b59d240481168fe1b9342bb2504ff` |

The four pulled charts also passed Helm rendering with private values produced
by `scripts/generate-suite-secrets.py`. Additional renders passed for Sphere's
multi-replica Valkey mode and direct OIDC on Horizon and Link.

This is public artifact and rendering evidence, not cluster acceptance. Link's
artifact availability does not waive the Forge gate: installation still stops
after Horizon until the suite guide's complete Forge development artifact gate
and its healthy SeaweedFS hand-off are verified.
