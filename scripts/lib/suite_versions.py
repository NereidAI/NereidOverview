#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
"""Resolve the product chart selectors for a suite release channel.

The version matrix lives in ``deploy/suite-versions.yaml``. The installer asks
for either the rolling ``dev`` channel or a bare SemVer suite release (the
tag with its leading ``v`` stripped). Output is shell-sourceable assignment
lines; any malformed or missing input fails with a nonzero exit and no
partial output so the installer cannot run with an unverified version.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path
from typing import Any

import yaml

# Bare SemVer per treaty section 19.5, plus the rolling 0.0.0-dev channel.
# The legacy 0.0.0-dev-<short-sha> selector remains accepted for reproducing
# frozen snapshots even though NereidForge development charts now keep the
# bare rolling identity. The strict character class is the primary guard
# against shell/selector injection; shlex.quote is defense in depth for the
# emitted assignments.
SELECTOR_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?$"
)
PRODUCT_VARIABLES = {
    "nereididentity": "NEREIDIDENTITY_VERSION",
    "nereidsphere": "NEREIDSPHERE_VERSION",
    "nereidhorizon": "NEREIDHORIZON_VERSION",
    "pre": "PRE_VERSION",
    "nereidforge": "NEREIDFORGE_VERSION",
    "nereidlink": "NEREIDLINK_VERSION",
}


def fail(message: str) -> None:
    print(f"suite version matrix: {message}", file=sys.stderr)
    raise SystemExit(1)


def resolve(manifest_path: Path, channel: str) -> dict[str, str]:
    try:
        document = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except OSError:
        fail(f"cannot read manifest {manifest_path}")
    except yaml.YAMLError as error:
        fail(f"invalid manifest YAML: {error}")
    if not isinstance(document, dict):
        fail("manifest root must be a mapping")

    if channel == "dev":
        matrix = document.get("channels", {}).get("dev")
        if not isinstance(matrix, dict):
            fail("manifest lacks a channels.dev product matrix")
    else:
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
                            r"(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?", channel):
            fail(f"invalid release channel: {channel}")
        releases = document.get("releases")
        if not isinstance(releases, dict) or channel not in releases:
            fail(f"no release matrix for suite version {channel}")
        matrix = releases[channel]
        if not isinstance(matrix, dict):
            fail(f"release matrix for {channel} must be a mapping")

    resolved: dict[str, str] = {}
    for product, variable in PRODUCT_VARIABLES.items():
        if product not in matrix:
            fail(f"channel {channel} is missing product selector {product}")
        selector = matrix[product]
        if not isinstance(selector, str) or not SELECTOR_RE.fullmatch(selector):
            fail(f"invalid version selector for {product}: {selector!r}")
        resolved[variable] = selector
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--channel",
        required=True,
        help="'dev' or a bare SemVer suite release such as 0.0.1",
    )
    args = parser.parse_args()

    resolved = resolve(args.manifest, args.channel)
    print(f"SUITE_VERSION_CHANNEL={shlex.quote(args.channel)}")
    # Emit SUITE_DEFAULT_* rather than the installer variables so an explicit
    # deployment.env selector always takes precedence over the matrix default.
    for variable in PRODUCT_VARIABLES.values():
        print(
            f"SUITE_DEFAULT_{variable}={shlex.quote(resolved[variable])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
