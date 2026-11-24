#!/usr/bin/env python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
"""Render deterministic, non-secret NereidAI suite site values."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Callable

import yaml

PRODUCTS = ("nereididentity", "nereidsphere", "nereidhorizon", "nereidlink")
SHARED_ENVIRONMENT = ("BASE_DOMAIN", "STORAGE_CLASS", "LOCAL_STORAGE_CLASS", "INGRESS_CLASS")
ADMIN_DEFAULTS = {
    "SUITE_ADMIN_USERNAME": "admin",
    "SUITE_ADMIN_EMAIL": "admin@nereidai.local",
    "SUITE_ADMIN_FIRST_NAME": "Admin",
    "SUITE_ADMIN_LAST_NAME": "User",
}
DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


class SiteValuesError(RuntimeError):
    """An actionable error that contains no environment values."""


def invalid_environment(name: str, requirement: str) -> SiteValuesError:
    return SiteValuesError(f"Invalid environment variable {name}: {requirement}")


def validate_host(name: str, value: str) -> None:
    if not value or value != value.strip() or any(character.isspace() for character in value):
        raise invalid_environment(name, "expected a non-empty host without whitespace")


def validate_base_domain(value: str) -> None:
    validate_host("BASE_DOMAIN", value)
    if len(value) > 253 or not all(DNS_LABEL.fullmatch(label) for label in value.split(".")):
        raise invalid_environment("BASE_DOMAIN", "expected a valid DNS domain")


def load_environment(product: str) -> dict[str, Any]:
    required = list(SHARED_ENVIRONMENT)
    if product == "nereidlink":
        required.append("LINK_MQTTS_HOST")
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise SiteValuesError("Missing required environment variables: " + ", ".join(missing))

    values: dict[str, Any] = {name: os.environ[name] for name in required}
    validate_base_domain(values["BASE_DOMAIN"])
    for name in ("STORAGE_CLASS", "LOCAL_STORAGE_CLASS", "INGRESS_CLASS"):
        value = values[name]
        if value != value.strip() or any(character.isspace() for character in value):
            raise invalid_environment(name, "expected a non-empty name without whitespace")
    if product == "nereidlink":
        validate_host("LINK_MQTTS_HOST", values["LINK_MQTTS_HOST"])

    if product == "nereidsphere":
        raw_replicas = os.environ.get("SPHERE_REPLICAS", "1")
        if not re.fullmatch(r"[0-9]+", raw_replicas) or int(raw_replicas) < 1:
            raise invalid_environment("SPHERE_REPLICAS", "expected a positive integer")
        values["SPHERE_REPLICAS"] = int(raw_replicas)

    if product == "nereididentity":
        for name, default in ADMIN_DEFAULTS.items():
            value = os.environ.get(name, default)
            if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
                raise invalid_environment(name, "expected non-empty text without control characters")
            values[name] = value
    return values


def client(name: str, description: str, origin: str, callbacks: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "directAccessGrants": False,
        "redirectUris": [origin + callback for callback in callbacks],
        "webOrigins": [origin],
    }


def identity_values(environment: dict[str, Any]) -> dict[str, Any]:
    domain = environment["BASE_DOMAIN"]
    sso_host = "sso." + domain
    origins = {product: f"https://{product}.{domain}" for product in (
        "nereidsphere",
        "nereidhorizon",
        "nereidforge",
        "nereidlink",
    )}
    return {
        "keycloak": {
            "ingress": {
                "enabled": True,
                "ingressClassName": environment["INGRESS_CLASS"],
                "annotations": {"cert-manager.io/cluster-issuer": "internal-ca"},
                "rules": [{"host": sso_host, "paths": [{"path": "/auth/", "pathType": "Prefix"}]}],
                "tls": [{"hosts": [sso_host], "secretName": "keycloak-tls"}],
            }
        },
        "identity": {
            "seedUsers": False,
            "suiteAdmin": {
                "username": environment["SUITE_ADMIN_USERNAME"],
                "email": environment["SUITE_ADMIN_EMAIL"],
                "firstName": environment["SUITE_ADMIN_FIRST_NAME"],
                "lastName": environment["SUITE_ADMIN_LAST_NAME"],
            },
            "clients": {
                "nereidsphere": client(
                    "NereidSphere",
                    "NereidSphere suite portal; authorization-code flow with PKCE",
                    origins["nereidsphere"],
                    ["/auth/callback"],
                ),
                "nereidlink": client(
                    "NereidLink",
                    "NereidLink IoT platform; authorization-code flow with PKCE",
                    origins["nereidlink"],
                    ["/v1/auth/oidc/callback", "/auth/callback"],
                ),
                "nereidhorizon": client(
                    "NereidHorizon",
                    "NereidHorizon edge distribution; authorization-code flow with PKCE",
                    origins["nereidhorizon"],
                    ["/api/oidc/callback"],
                ),
                "nereidforge": client(
                    "NereidForge",
                    "NereidForge model factory; authorization-code flow with PKCE",
                    origins["nereidforge"],
                    ["/auth/callback"],
                ),
            },
        },
        "postgresql": {"cluster": {"storage": {"storageClass": environment["STORAGE_CLASS"]}}},
    }


def sphere_values(environment: dict[str, Any]) -> dict[str, Any]:
    domain = environment["BASE_DOMAIN"]
    host = "nereidsphere." + domain
    replicas = environment["SPHERE_REPLICAS"]
    multiple = replicas > 1
    products = []
    for product_id, name, description in (
        ("forge", "NereidForge", "Model factory"),
        ("horizon", "NereidHorizon", "Edge distribution"),
        ("link", "NereidLink", "IoT platform"),
    ):
        products.append({
            "id": product_id,
            "name": name,
            "description": description,
            "url": f"https://nereid{product_id}.{domain}",
            "mode": "ns",
            "oidcClientId": "nereid" + product_id,
            "tenantsPath": "/v1/integration/ns/tenants",
        })
    return {
        "replicaCount": replicas,
        "podDisruptionBudget": {"enabled": multiple, "minAvailable": 1},
        "valkey": {"enabled": multiple},
        "tickets": {"replayStore": "valkey" if multiple else "memory"},
        "ingress": {
            "enabled": True,
            "className": environment["INGRESS_CLASS"],
            "annotations": {"cert-manager.io/cluster-issuer": "internal-ca"},
            "hosts": [{"host": host, "paths": [{"path": "/", "pathType": "Prefix"}]}],
            "tls": [{"hosts": [host], "secretName": "nereidsphere-tls"}],
        },
        "config": {
            "server": {"baseUrl": "https://" + host},
            "oidc": {
                "issuer": f"https://sso.{domain}/auth/realms/nereidai",
                "clientId": "nereidsphere",
                "adminClientId": "nereidsphere-admin",
                "caBundleSecret": "nereid-internal-ca-tls",
            },
            "products": products,
        },
    }


def horizon_values(environment: dict[str, Any]) -> dict[str, Any]:
    domain = environment["BASE_DOMAIN"]
    return {
        "global": {"imagePullSecrets": []},
        "postgres": {"persistence": {"storageClass": environment["LOCAL_STORAGE_CLASS"]}},
        "ns": {
            "enabled": True,
            "baseUrl": f"https://nereidsphere.{domain}",
            "productId": "horizon",
            "callbackPath": "/auth/ns-callback",
            "caBundleSecret": "nereid-internal-ca-tls",
            "caBundleKey": "ca.crt",
        },
        "ingress": {
            "enabled": True,
            "className": environment["INGRESS_CLASS"],
            "host": "nereidhorizon." + domain,
            "tls": {"enabled": True, "secretName": "nereidhorizon-tls"},
        },
    }


def link_values(environment: dict[str, Any]) -> dict[str, Any]:
    domain = environment["BASE_DOMAIN"]
    host = "nereidlink." + domain
    return {
        "imagePullSecrets": [],
        "registryCredentials": {"create": False},
        "replicaCount": 1,
        "frontend": {"replicaCount": 1},
        "ingress": {
            "enabled": True,
            "className": environment["INGRESS_CLASS"],
            "host": host,
            "tls": {"enabled": True, "secretName": "nereidlink-tls"},
        },
        "postgresql": {
            "mode": "bundled",
            "storageClass": environment["LOCAL_STORAGE_CLASS"],
        },
        "nats": {
            "enabled": True,
            "replicas": 1,
            "jetstreamReplicas": 1,
            "storageClass": environment["LOCAL_STORAGE_CLASS"],
        },
        "persistence": {"storageClass": environment["STORAGE_CLASS"]},
        "blob": {
            "endpoint": "seaweedfs-s3.nereidforge.svc.cluster.local:8333",
            "publicEndpoint": f"seaweedfs-s3.nereidforge.{domain}:443",
            "bucket": "nereidlink",
            "secure": False,
            "publicSecure": True,
        },
        "sso": {
            "enabled": True,
            "nsBaseURL": f"https://nereidsphere.{domain}",
            "clientID": "link",
            "callbackPath": "/auth/ns-callback",
            "caBundleSecret": "nereid-internal-ca-tls",
            "caBundleKey": "ca.crt",
        },
        "pki": {
            "serverHosts": [
                "localhost",
                "127.0.0.1",
                "nereidlink",
                "nereidlink.nereidlink.svc.cluster.local",
                host,
                environment["LINK_MQTTS_HOST"],
            ]
        },
    }


RENDERERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "nereididentity": identity_values,
    "nereidsphere": sphere_values,
    "nereidhorizon": horizon_values,
    "nereidlink": link_values,
}


def atomic_write(path: Path, content: bytes) -> bool:
    """Write a regular private file, returning False when bytes were unchanged."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
    except OSError as error:
        detail = error.strerror or "directory preparation failed"
        raise SiteValuesError(f"Cannot prepare output directory {path.parent}: {detail}") from error

    try:
        current = path.lstat()
    except FileNotFoundError:
        current = None
    except OSError as error:
        detail = error.strerror or "stat failed"
        raise SiteValuesError(f"Cannot inspect output {path}: {detail}") from error
    if current is not None and not stat.S_ISREG(current.st_mode):
        raise SiteValuesError(f"Output must be a regular file: {path}")

    if current is not None:
        try:
            unchanged = path.read_bytes() == content
        except OSError as error:
            detail = error.strerror or "read failed"
            raise SiteValuesError(f"Cannot read existing output {path}: {detail}") from error
        if unchanged:
            if stat.S_IMODE(current.st_mode) != 0o600:
                try:
                    path.chmod(0o600)
                except OSError as error:
                    detail = error.strerror or "chmod failed"
                    raise SiteValuesError(f"Cannot secure output {path}: {detail}") from error
            return False

    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    except OSError as error:
        detail = error.strerror or "temporary-file creation failed"
        raise SiteValuesError(f"Cannot create output beside {path}: {detail}") from error
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as error:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        detail = error.strerror or "write failed"
        raise SiteValuesError(f"Cannot write output {path}: {detail}") from error
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", choices=PRODUCTS, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        environment = load_environment(args.product)
        values = RENDERERS[args.product](environment)
        content = yaml.safe_dump(values, sort_keys=False, allow_unicode=True).encode("utf-8")
        atomic_write(args.output.expanduser(), content)
    except SiteValuesError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
