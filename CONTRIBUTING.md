# Contributing to NereidOverview

Thank you for your interest in NereidAI. This repository is the suite's
source-code entry point: it holds the deployment runbooks, the deployment
standards, the cluster-shared prerequisite components, and the air-gapped
delivery tooling. It contains **no product runtime code** — feature changes to
a product itself belong in that product's own repository.

Typical contributions here are:

- corrections and clarifications to the deployment runbooks and reference docs;
- fixes to the cluster-shared manifests under `deploy/prereqs/`;
- improvements to the air-gapped tooling under `deploy/scripts/`;
- improvements to this guide, the README, or the deployment standards.

## Repository-specific rules

- **English only.** Every committed document and code comment is written in
  English (see [deploy-standards §15.6](docs/deploy-standards.md)).
- **Host-free by design.** Never commit internal hostnames, real DNS names,
  lab IP addresses, credentials, tokens, or private registry coordinates. Use
  the reserved documentation domains and networks instead — for example
  `*.example` (RFC 2606), addresses in `192.0.2.0/24` (RFC 5737), and
  `<placeholder>` values. Secrets have no place in the repository, even in
  examples or command history.
- **One install path per component.** Shared prerequisites are installed only
  from this repository; product installers preflight-check them and never
  self-install them.
- Match the structure and style of the surrounding document or script.

## Developer Certificate of Origin

Every non-merge commit must be signed off under the
[Developer Certificate of Origin](https://developercertificate.org/) (DCO):

```
Signed-off-by: Your Name <you@example.com>
```

Create signed commits with `git commit -s`. A CI workflow rejects pull
requests that contain commits whose `Signed-off-by` trailer does not match the
commit author.

Signing off means you certify the DCO statement: you wrote the contribution,
or otherwise have the right to submit it, and you contribute it under this
project's license. **The DCO is a certification and a license grant — it is
not a copyright assignment.**

If the work was created for an employer (a work made for hire), the DCO's
clauses (c) and (d) apply: the signer is responsible for ensuring the
employer's rights are covered, for example through an employer agreement or
authorization. The project does not negotiate employer-side paperwork.

## Copyright and license of contributions

- The inbound license for every contribution is the
  [Apache License 2.0](LICENSE). By submitting a signed-off contribution you
  grant the project and every downstream recipient a perpetual, irrevocable,
  worldwide, sublicensable license under copyright and any relevant patent
  claims, on Apache-2.0 terms.
- **Copyright stays with the author.** Contributors retain ownership of the
  copyright in their own work; there is no Contributor License Agreement and
  no copyright assignment.
- Copyright headers follow authorship rather than a single project owner:
  - Documentation Markdown in this repository conventionally carries no
    copyright header; the DCO record and the repository `LICENSE` govern
    attribution.
  - For a new hand-written source, YAML, or shell file of substantial
    authorship, use your own copyright line together with the standard
    SPDX identifier:
    ```text
    Copyright (C) <year> <author or organization>
    SPDX-License-Identifier: Apache-2.0
    ```
  - When modifying an existing file, keep its existing headers and notices
    intact; do not replace or reassign them. Small fixes do not create a new
    copyright claim.
  - A file substantially co-authored by multiple parties may carry multiple
    copyright lines.
- The `NOTICE` files in product repositories list bundled third-party
  components; ordinary pull-request contributions are not added there.

## AI-assisted contributions

AI tools may be used as aids, but the human signer takes full responsibility
for the result exactly as for hand-written code, including correctness,
license compatibility, and the DCO certification. Substantially AI-generated
content must be disclosed in the pull request description. Commits authored
solely by an automated agent with no human sign-off are not accepted.

Automated platform bots (for example Dependabot) are exempt from the DCO
trailer: their contributions are covered by the platform's terms of service,
and the DCO workflow skips bot authors.

## Pull request workflow

1. Fork the repository and create a feature branch off `main`
   (`fix/...`, `docs/...`, `chore/...`).
2. Keep the change focused: one logical change per pull request, with a
   conventional-commit message (`feat:`, `fix:`, `docs:`, `chore:`).
3. Verify before requesting review:
   - documentation: every relative link resolves and the host-free rules
     above hold;
   - chart changes under `deploy/prereqs/charts/`: `helm lint` and
     `helm template` pass for both the default values and any production
     overlay;
   - shell changes: the script passes `shellcheck` and `bash -n`.
4. Make sure every commit carries a matching `Signed-off-by` trailer.
5. Describe what changed and why, referencing any related issue.
6. Do not force-push to `main`; releases and tags are cut by maintainers only.

## Reporting problems

Open a GitHub issue with the steps to reproduce, the expected and actual
behavior, and the relevant environment (k3s/Kubernetes version, host OS,
deployment mode). Never paste secrets, full credentials, or private registry
hostnames into an issue.

## License

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
