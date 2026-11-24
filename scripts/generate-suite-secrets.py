#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
"""Generate and inject operator-supplied NereidAI suite secrets.

The persistent secret store is never printed. Rendering preserves the operator's
site-values file and writes a separate mode-0600 generated values file.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile
from typing import Any, Callable

import yaml

SCHEMA_VERSION = 1
PRODUCTS = ("nereididentity", "nereidsphere", "nereidhorizon", "nereidlink")
SECRET_GENERATORS: dict[str, Callable[[], str]] = {
    "identity.postgresql_password": lambda: secrets.token_urlsafe(48),
    "identity.admin_password": lambda: secrets.token_urlsafe(48),
    "identity.suite_admin_password": lambda: secrets.token_urlsafe(48),
    "identity.admin_client_secret": lambda: secrets.token_urlsafe(48),
    "identity.client.nereidsphere": lambda: secrets.token_urlsafe(48),
    "identity.client.nereidhorizon": lambda: secrets.token_urlsafe(48),
    "identity.client.nereidforge": lambda: secrets.token_urlsafe(48),
    "identity.client.nereidlink": lambda: secrets.token_urlsafe(48),
    # Exactly 32 ASCII bytes, as required by Sphere's AES-256 session value.
    "sphere.session_key": lambda: secrets.token_hex(16),
    "sphere.valkey_password": lambda: secrets.token_urlsafe(48),
    "sphere.ticket.forge": lambda: secrets.token_urlsafe(48),
    "sphere.ticket.horizon": lambda: secrets.token_urlsafe(48),
    "sphere.ticket.link": lambda: secrets.token_urlsafe(48),
    "horizon.postgresql_password": lambda: secrets.token_urlsafe(48),
    "link.jwt_secret": lambda: secrets.token_urlsafe(48),
    "link.postgresql_password": lambda: secrets.token_urlsafe(48),
}


class SecretToolError(RuntimeError):
    """An actionable input or persistence error without secret material."""


def private_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SecretToolError(f"expected a regular private file: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise SecretToolError(f"file must not be accessible by group/other; chmod 600 {path}")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def store_path(deployment_root: Path) -> Path:
    return deployment_root / "secret-store" / "suite-secrets.json"


def load_store(path: Path) -> dict[str, Any]:
    private_file(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SecretToolError(f"cannot read secret store {path}: {error}") from error
    if document.get("schemaVersion") != SCHEMA_VERSION:
        raise SecretToolError(f"unsupported secret-store schema in {path}")
    values = document.get("secrets")
    if not isinstance(values, dict):
        raise SecretToolError(f"secret store has no secrets object: {path}")
    for key, value in values.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise SecretToolError(f"secret store contains an invalid entry: {path}")
    return document


def initialize_store(deployment_root: Path) -> tuple[Path, int]:
    path = store_path(deployment_root)
    if path.is_symlink():
        raise SecretToolError(f"secret store must not be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    mode = stat.S_IMODE(path.parent.stat().st_mode)
    if mode & 0o077:
        raise SecretToolError(f"directory must be mode 0700: {path.parent}")
    os.chmod(path.parent, 0o700)

    if path.exists():
        document = load_store(path)
        missing = sorted(set(SECRET_GENERATORS) - set(document["secrets"]))
        if missing:
            raise SecretToolError(
                "secret store is incomplete; missing keys: " + ", ".join(missing)
                + "; restore the canonical store from its encrypted backup or perform a reviewed migration"
            )
    else:
        document = {"schemaVersion": SCHEMA_VERSION, "secrets": {}}
    generated = 0
    for key, generator in SECRET_GENERATORS.items():
        if key not in document["secrets"]:
            document["secrets"][key] = generator()
            generated += 1
    content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if generated or not path.exists():
        atomic_write(path, content)
    return path, generated


def load_yaml_mapping(path: Path, *, private: bool = False) -> dict[str, Any]:
    if private:
        private_file(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        detail = error.strerror or "read failed"
        raise SecretToolError(f"cannot read YAML mapping {path}: {detail}") from error
    except yaml.YAMLError as error:
        # PyYAML's string representation includes source excerpts, which may be
        # secret values in a private hand-off. Return only a safe location.
        mark = getattr(error, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise SecretToolError(f"invalid YAML in {path}{location}; source excerpt suppressed") from error
    if not isinstance(document, dict):
        raise SecretToolError(f"expected a YAML mapping: {path}")
    return document


def set_path(document: dict[str, Any], path: tuple[str, ...], value: str) -> None:
    node = document
    for key in path[:-1]:
        child = node.get(key)
        if child is None:
            child = {}
            node[key] = child
        if not isinstance(child, dict):
            raise SecretToolError(f"values path {'.'.join(path)} conflicts with a scalar")
        node = child
    node[path[-1]] = value


def get_path(document: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    node: Any = document
    for key in path:
        if not isinstance(node, dict):
            return default
        node = node.get(key, default)
    return node


def render_identity(values: dict[str, Any], generated: dict[str, str]) -> None:
    mappings = {
        ("postgresql", "bootstrap", "password"): "identity.postgresql_password",
        ("identity", "admin", "password"): "identity.admin_password",
        ("identity", "suiteAdmin", "password"): "identity.suite_admin_password",
        ("identity", "adminClient", "secret"): "identity.admin_client_secret",
    }
    for product in ("nereidsphere", "nereidhorizon", "nereidforge", "nereidlink"):
        mappings[("identity", "clients", product, "secret")] = f"identity.client.{product}"
    for path, key in mappings.items():
        set_path(values, path, generated[key])


def render_sphere(values: dict[str, Any], generated: dict[str, str]) -> None:
    if get_path(values, ("config", "existingSecret"), ""):
        raise SecretToolError("config.existingSecret requires externally rendered Sphere configuration")
    set_path(values, ("config", "oidc", "clientSecret"), generated["identity.client.nereidsphere"])
    set_path(values, ("config", "oidc", "adminClientSecret"), generated["identity.admin_client_secret"])
    set_path(values, ("config", "session", "secretKey"), generated["sphere.session_key"])

    products = get_path(values, ("config", "products"))
    if not isinstance(products, list):
        raise SecretToolError("Sphere site values must contain config.products entries for forge, horizon, and link")
    by_id = {entry.get("id"): entry for entry in products if isinstance(entry, dict)}
    for product in ("forge", "horizon", "link"):
        if product not in by_id:
            raise SecretToolError(f"Sphere config.products is missing id={product}")
        by_id[product]["ssoSecret"] = generated[f"sphere.ticket.{product}"]

    if get_path(values, ("valkey", "enabled"), True) and not get_path(
        values, ("valkey", "auth", "existingSecret"), ""
    ):
        set_path(values, ("valkey", "auth", "password"), generated["sphere.valkey_password"])


def render_horizon(values: dict[str, Any], generated: dict[str, str]) -> None:
    if get_path(values, ("postgres", "enabled"), True):
        set_path(values, ("postgres", "auth", "password"), generated["horizon.postgresql_password"])
    if get_path(values, ("ns", "enabled"), False):
        set_path(values, ("ns", "clientSecret"), generated["sphere.ticket.horizon"])
    if get_path(values, ("oidc", "enabled"), False):
        set_path(values, ("oidc", "clientSecret"), generated["identity.client.nereidhorizon"])


def render_link(
    values: dict[str, Any], generated: dict[str, str], forge_credentials: dict[str, Any]
) -> None:
    if get_path(values, ("oidc", "enabled"), False) and get_path(values, ("sso", "enabled"), False):
        raise SecretToolError("Link oidc.enabled and sso.enabled are mutually exclusive")
    if set(forge_credentials) != {"accessKey", "secretKey"}:
        raise SecretToolError("Forge credential hand-off must contain exactly accessKey and secretKey")
    set_path(values, ("auth", "jwtSecret"), generated["link.jwt_secret"])
    if get_path(values, ("postgresql", "mode"), "bundled") != "external":
        set_path(values, ("postgresql", "password"), generated["link.postgresql_password"])
    if get_path(values, ("sso", "enabled"), False):
        set_path(values, ("sso", "ssoSecret"), generated["sphere.ticket.link"])
    if get_path(values, ("oidc", "enabled"), False):
        set_path(values, ("oidc", "clientSecret"), generated["identity.client.nereidlink"])

    for key in ("accessKey", "secretKey"):
        value = forge_credentials[key]
        if not isinstance(value, str) or not value:
            raise SecretToolError(f"Forge credential hand-off requires non-empty {key}")
        if value.strip().startswith("<") and value.strip().endswith(">"):
            raise SecretToolError(f"Forge credential hand-off contains a placeholder in {key}")
        set_path(values, ("blob", key), value)


def render_values(args: argparse.Namespace) -> Path:
    deployment_root = args.deployment_root.expanduser().resolve()
    document = load_store(store_path(deployment_root))
    generated = document["secrets"]
    missing = sorted(set(SECRET_GENERATORS) - set(generated))
    if missing:
        raise SecretToolError(
            "secret store is incomplete; restore the canonical store or perform a reviewed migration; "
            "init will not generate replacements"
        )

    input_path = args.input.expanduser().resolve()
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else input_path.parent / "values.generated.yaml"
    )
    if input_path == output_path:
        raise SecretToolError("input and output must differ; site values are never modified")
    if output_path.exists() and not args.force:
        raise SecretToolError(f"output exists; use --force to regenerate it: {output_path}")

    values = copy.deepcopy(load_yaml_mapping(input_path))
    if args.product == "nereididentity":
        render_identity(values, generated)
    elif args.product == "nereidsphere":
        render_sphere(values, generated)
    elif args.product == "nereidhorizon":
        render_horizon(values, generated)
    else:
        if not args.forge_credentials:
            raise SecretToolError("Link rendering requires --forge-credentials from the verified Forge hand-off")
        credentials = load_yaml_mapping(args.forge_credentials.expanduser().resolve(), private=True)
        render_link(values, generated, credentials)

    atomic_write(output_path, yaml.safe_dump(values, sort_keys=False, allow_unicode=True))
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_root(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--deployment-root", type=Path, required=True)

    init_parser = subparsers.add_parser(
        "init",
        help="create a complete new store; reject incomplete existing stores without replacement",
    )
    add_root(init_parser)

    render_parser = subparsers.add_parser("render", help="inject secrets into a product values copy")
    add_root(render_parser)
    render_parser.add_argument("--product", choices=PRODUCTS, required=True)
    render_parser.add_argument("--input", type=Path, required=True, help="non-secret site-values YAML")
    render_parser.add_argument("--output", type=Path, help="default: <input-directory>/values.generated.yaml")
    render_parser.add_argument("--forge-credentials", type=Path, help="mode-0600 Forge accessKey/secretKey YAML")
    render_parser.add_argument("--force", action="store_true", help="replace a previous generated output")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "init":
            path, generated = initialize_store(args.deployment_root.expanduser().resolve())
            print(f"Secret store ready: {path} (new values: {generated}; existing values preserved)")
        else:
            path = render_values(args)
            print(f"Generated private values: {path}")
    except SecretToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
