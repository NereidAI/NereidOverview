#!/usr/bin/python3
# Copyright (C) 2026 YIQISOFT
# SPDX-License-Identifier: Apache-2.0
"""Local command fakes for quick-install end-to-end tests.

The multiplexer is linked to host tool names by the test. It persists only
non-production fixture state and never contacts a cluster or registry.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import tarfile
import tempfile

import yaml


STATE_PATH = Path(os.environ["FAKE_SUITE_CLUSTER"])
CALLS_PATH = Path(os.environ["FAKE_SUITE_CALLS"])


def load_state():
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state):
    temporary = STATE_PATH.with_name(f".{STATE_PATH.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(STATE_PATH)


def record(tool, args=()):
    with CALLS_PATH.open("a", encoding="utf-8") as destination:
        destination.write("\t".join([tool, *args]) + "\n")


def option(args, name, default=None):
    try:
        return args[args.index(name) + 1]
    except (ValueError, IndexError):
        prefix = f"{name}="
        return next((arg[len(prefix):] for arg in args if arg.startswith(prefix)), default)


def namespace_and_args(args):
    args = list(args)
    namespace = "default"
    while args:
        if args[0] == "-n":
            namespace = args[1]
            args = args[2:]
        elif args[0].startswith("--namespace="):
            namespace = args[0].split("=", 1)[1]
            args = args[1:]
        elif args[0] == "--context":
            args = args[2:]
        elif args[0].startswith("--context="):
            args = args[1:]
        else:
            break
    return namespace, args


def secret_key(namespace, name):
    return f"{namespace}/{name}"


def kubeconfig_documents():
    documents = []
    for filename in os.environ.get("KUBECONFIG", "").split(os.pathsep):
        if not filename:
            continue
        path = Path(filename)
        if not path.is_file():
            continue
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(document, dict):
            documents.append(document)
    return documents


def active_context(state):
    for document in kubeconfig_documents():
        if document.get("current-context"):
            return document["current-context"]
    return state.get("shared_context", state["context"])


def not_found(kind, name):
    print(f'Error from server (NotFound): {kind} "{name}" not found', file=sys.stderr)
    return 1


def output_format(args):
    if "-o" in args:
        value = option(args, "-o", "")
    else:
        value = next((arg.split("=", 1)[1] for arg in args if arg.startswith("-o=jsonpath=")), "")
    return value.removeprefix("jsonpath=")


def write_chart(product, version, destination):
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / f"{product}-{version}.tgz"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / product
        root.mkdir()
        (root / "Chart.yaml").write_text(
            f"apiVersion: v2\nname: {product}\nversion: {version}\n",
            encoding="utf-8",
        )
        (root / "values.yaml").write_text("{}\n", encoding="utf-8")
        with tarfile.open(archive, "w:gz") as bundle:
            bundle.add(root, arcname=product)
    return archive


def pre_config():
    return r"""#!/usr/bin/env bash
set -euo pipefail
: "${PG_CLUSTER_NAME:=nereidforge-pg}"
: "${PG_DB_NAME:=nereidforge}"
: "${PG_DB_USER:=nereidforge}"
: "${PG_ADMIN_PASSWORD:=}"
: "${SEAWEEDFS_S3_ACCESS_KEY:=}"
: "${SEAWEEDFS_S3_SECRET_KEY:=}"
: "${DEX_STATIC_EMAIL:=}"
: "${DEX_STATIC_PASSWORD:=}"
: "${DEX_STATIC_PASSWORD_HASH:=}"
: "${BASE_DOMAIN:=}"
: "${STORAGE_CLASS:=}"
: "${POD_CIDR:=}"
: "${SERVICE_CIDR:=}"
: "${SSO_MODE:=}"
: "${SSO_NS_BASE_URL:=}"
: "${FRONTEND_HOST:=}"
: "${NF_VALUES_FILE:=$PRE_HANDOFF_DIR/values.generated.yaml}"
if [[ -f "$PRE_ENV_FILE" ]]; then
    source "$PRE_ENV_FILE"
fi
export PG_CLUSTER_NAME PG_DB_NAME PG_DB_USER PG_ADMIN_PASSWORD
export SEAWEEDFS_S3_ACCESS_KEY SEAWEEDFS_S3_SECRET_KEY
export DEX_STATIC_EMAIL DEX_STATIC_PASSWORD DEX_STATIC_PASSWORD_HASH
export BASE_DOMAIN STORAGE_CLASS POD_CIDR SERVICE_CIDR
export SSO_MODE SSO_NS_BASE_URL FRONTEND_HOST NF_VALUES_FILE
"""


def pre_infra():
    return r"""#!/usr/bin/env bash
set -euo pipefail
source "$PRE_ROOT/scripts/lib/config.sh"
printf 'pre\t10_infra\n' >> "$FAKE_SUITE_CALLS"
[[ "${FAKE_FAIL_PRE_INFRA:-no}" != yes ]]
python3 - "$FAKE_SUITE_CLUSTER" <<'PY'
import json
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
if "nereidforge" not in state["namespaces"]:
    state["namespaces"].append("nereidforge")
secrets = state["secrets"]
secrets.setdefault(
    "nereidforge/pg-" + os.environ["PG_CLUSTER_NAME"] + "-credentials",
    {"username": os.environ["PG_DB_USER"], "password": os.environ["PG_ADMIN_PASSWORD"]},
)
secrets.setdefault(
    "nereidforge/seaweedfs-s3-credentials",
    {
        "accessKey": os.environ["SEAWEEDFS_S3_ACCESS_KEY"],
        "secretKey": os.environ["SEAWEEDFS_S3_SECRET_KEY"],
    },
)
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY
"""


def pre_kubeflow():
    return r"""#!/usr/bin/env bash
set -euo pipefail
source "$PRE_ROOT/scripts/lib/config.sh"
printf 'pre\t30_install-kubeflow\n' >> "$FAKE_SUITE_CALLS"
if [[ "${FAKE_FAIL_PRE_KUBEFLOW:-no}" == yes ]]; then
    echo 'simulated Kubeflow apply failure' >&2
    false
    printf 'UNEXPECTED-CONTINUED\n' >> "$FAKE_SUITE_CALLS"
fi
if [[ "${FAKE_SWITCH_SHARED_CONTEXT:-no}" == yes ]]; then
    python3 - "$FAKE_SUITE_CLUSTER" <<'PY'
import json
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
state["shared_context"] = "other-context"
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY
fi
printf 'backend: {}\n' > "$NF_VALUES_FILE"
chmod 600 "$NF_VALUES_FILE"
if [[ "${FAKE_SKIP_PRE_RUNTIME_SECRET:-no}" != yes ]]; then
    python3 - "$FAKE_SUITE_CLUSTER" "$DEPLOYMENT_ROOT/secret-store/suite-secrets.json" <<'PY'
import json
import os
from pathlib import Path
import sys

path = Path(sys.argv[1])
state = json.loads(path.read_text(encoding="utf-8"))
store = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
runtime = state["secrets"].setdefault("nereidforge/nereidforge-service-credentials", {})
runtime.setdefault("NEREIDFORGE_LABELSTUDIO_TOKEN", "fake-pre-labelstudio-token")
runtime.setdefault("NEREIDFORGE_CVAT_TOKEN", "fake-pre-cvat-token")
if os.environ.get("FAKE_PRE_RUNTIME_WITHOUT_NF_SSO") != "yes":
    runtime.setdefault(
        "NEREIDFORGE_SSO_NS_CLIENT_SECRET",
        os.environ.get("FAKE_PRE_RUNTIME_SSO_OVERRIDE", store["secrets"]["sphere.ticket.forge"]),
    )
temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
temporary.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
temporary.chmod(0o600)
temporary.replace(path)
PY
fi
"""


def pre_infra_verify():
    return r"""#!/usr/bin/env bash
set -euo pipefail
source "$PRE_ROOT/scripts/lib/config.sh"
python3 - "$FAKE_SUITE_CLUSTER" <<'PY'
import json
import os
from pathlib import Path
import sys

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
secrets = state["secrets"]
pg = secrets.get("nereidforge/pg-" + os.environ["PG_CLUSTER_NAME"] + "-credentials")
s3 = secrets.get("nereidforge/seaweedfs-s3-credentials")
if not pg or pg != {"username": os.environ["PG_DB_USER"], "password": os.environ["PG_ADMIN_PASSWORD"]}:
    raise SystemExit("fake canonical PostgreSQL identity is unavailable or mismatched")
if not s3 or s3 != {
    "accessKey": os.environ["SEAWEEDFS_S3_ACCESS_KEY"],
    "secretKey": os.environ["SEAWEEDFS_S3_SECRET_KEY"],
}:
    raise SystemExit("fake canonical SeaweedFS identity is unavailable or mismatched")
PY
"""


def write_pre_payload(root):
    scripts = {
        "scripts/lib/config.sh": pre_config(),
        "scripts/10_infra.sh": pre_infra(),
        "scripts/30_install-kubeflow.sh": pre_kubeflow(),
        "scripts/60_verify/infra-check.sh": pre_infra_verify(),
        "scripts/60_verify/kubeflow-check.sh": "#!/usr/bin/env bash\nset -euo pipefail\ntest -s \"$NF_VALUES_FILE\"\n",
        "scripts/60_verify/mr-check.sh": "#!/usr/bin/env bash\nset -euo pipefail\n",
        "scripts/40_check-nf-handoff.sh": "#!/usr/bin/env bash\nset -euo pipefail\ntest -s \"$NF_VALUES_FILE\"\n",
    }
    for relative, content in scripts.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o700)
    (root / "install-lock.json").write_text('{"schema": 1}\n', encoding="utf-8")


def oras_pull(args):
    state = load_state()
    version = state["pre_version"]
    output = Path(option(args, "--output"))
    output.mkdir(parents=True, exist_ok=True)
    archive_name = f"pre-nereidforge-installer-{version}.tar.gz"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / f"pre-nereidforge-installer-{version}"
        root.mkdir()
        write_pre_payload(root)
        with tarfile.open(output / archive_name, "w:gz") as bundle:
            bundle.add(root, arcname=root.name)
    digest = hashlib.sha256((output / archive_name).read_bytes()).hexdigest()
    (output / f"{archive_name}.sha256").write_text(f"{digest}  {archive_name}\n", encoding="utf-8")
    (output / f"pre-nereidforge-installer-{version}.lock.json").write_text(
        '{"schema": 1}\n', encoding="utf-8"
    )
    (output / f"pre-nereidforge-charts-{version}.txt").write_text(
        "five fake supporting charts\n", encoding="utf-8"
    )
    return 0


def chart_blob(product, version):
    cache = STATE_PATH.parent / "chart-cache"
    archive = cache / f"{product}-{version}.tgz"
    if not archive.exists():
        write_chart(product, version, cache)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    return archive, digest


def run_oras(args):
    state = load_state()
    command = args[0]
    if command == "resolve":
        repository = args[-1]
        version = state["pre_version"] if "pre-nereidforge-installer" in repository else state["chart_version"]
        digest = hashlib.sha256(f"{repository}:{version}".encode()).hexdigest()
        print(f"sha256:{digest}")
        return 0
    if command == "manifest" and args[1] == "fetch":
        reference = args[-1]
        if "pre-nereidforge-installer" in reference:
            version = state["pre_version"]
            short = version.rsplit("-", 1)[1]
            print(json.dumps({
                "annotations": {
                    "org.opencontainers.image.version": version,
                    "org.opencontainers.image.revision": short + "a" * 33,
                }
            }))
        else:
            product = reference.split("/", 1)[1].split("@", 1)[0].removeprefix("nereidai/charts/")
            version = state["chart_version"]
            _, layer_digest = chart_blob(product, version)
            print(json.dumps({
                "layers": [{
                    "mediaType": "application/vnd.cncf.helm.chart.content.v1.tar+gzip",
                    "digest": f"sha256:{layer_digest}",
                }]
            }))
        return 0
    if command == "blob" and args[1] == "fetch":
        output = Path(option(args, "--output"))
        reference = args[-1]
        product = reference.split("/", 1)[1].split("@", 1)[0].removeprefix("nereidai/charts/")
        expected = reference.rsplit("@", 1)[1].removeprefix("sha256:")
        for archive in (STATE_PATH.parent / "chart-cache").glob(f"{product}-*.tgz"):
            if hashlib.sha256(archive.read_bytes()).hexdigest() == expected:
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(archive, output)
                return 0
        print("fake chart blob digest was not found", file=sys.stderr)
        return 1
    if command == "pull":
        return oras_pull(args)
    print(f"unsupported fake oras command: {args}", file=sys.stderr)
    return 2


def run_helm(args):
    state = load_state()
    if args[:1] == ["repo"]:
        return 0
    if args[:1] == ["list"]:
        names = list(state["releases"])
        if "--all" in args:
            names.extend(state.get("pending_releases", []))
        print(json.dumps([{"name": name} for name in names]))
        return 0
    if args[:2] == ["show", "chart"]:
        with tarfile.open(args[2], "r:gz") as bundle:
            for member in bundle.getmembers():
                if member.name.endswith("/Chart.yaml"):
                    sys.stdout.write(bundle.extractfile(member).read().decode("utf-8"))
                    return 0
        return 1
    if args[:1] == ["pull"]:
        chart = args[1]
        selector = option(args, "--version")
        destination = Path(option(args, "--destination"))
        if chart.startswith("oci://"):
            product = chart.rsplit("/", 1)[1]
            version = state["chart_version"] if selector == "0.0.0-dev" else selector
        else:
            product = chart
            version = selector
        write_chart(product, version, destination)
        return 0
    if args[:2] == ["upgrade", "--install"]:
        release = args[2]
        if os.environ.get("FAKE_FAIL_RELEASE") == release:
            print(f"simulated Helm failure for {release}", file=sys.stderr)
            return 1
        if release not in state["releases"]:
            state["releases"].append(release)
        if release == "nereidlink":
            state["link_bucket"] = os.environ.get("FAKE_SKIP_LINK_BUCKET") != "yes"
        save_state(state)
        return 0
    print(f"unsupported fake helm command: {args}", file=sys.stderr)
    return 2


def secret_document(namespace, name, values):
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "data": {
            key: base64.b64encode(value.encode("utf-8")).decode("ascii")
            for key, value in values.items()
        },
    }


def apply_json(document):
    state = load_state()
    kind = document.get("kind")
    metadata = document.get("metadata", {})
    if kind == "Namespace":
        name = metadata["name"]
        if name not in state["namespaces"]:
            state["namespaces"].append(name)
    elif kind == "Secret":
        namespace = metadata.get("namespace", "default")
        name = metadata["name"]
        values = {
            key: base64.b64decode(value).decode("utf-8")
            for key, value in document.get("data", {}).items()
        }
        state["secrets"][secret_key(namespace, name)] = values
    else:
        return
    save_state(state)


def link_pod(name, replicaset, template, migration_exit=0):
    pod = {
        "metadata": {
            "name": name,
            "ownerReferences": [{
                "kind": "ReplicaSet",
                "name": replicaset["metadata"]["name"],
                "uid": replicaset["metadata"]["uid"],
                "controller": True,
            }],
        },
        "spec": copy.deepcopy(template["spec"]),
        "status": {
            "containerStatuses": [{
                "name": "main",
                "imageID": "ghcr.io/nereidai/fake@sha256:" + "1" * 64,
            }],
        },
    }
    pod["spec"]["containers"] = [{
        "name": "main",
        "image": "ghcr.io/nereidai/nereidlink-backend:0.0.0-dev",
    }]
    if "migrate" in {item.get("name") for item in pod["spec"].get("initContainers", [])}:
        pod["status"]["initContainerStatuses"] = [{
            "name": "migrate",
            "imageID": "ghcr.io/nereidai/fake@sha256:" + "2" * 64,
            "state": {"terminated": {"exitCode": migration_exit}},
        }]
    return pod


def link_workloads():
    current_has_migration = os.environ.get("FAKE_LINK_OLD_SUCCESS_CURRENT_WITHOUT_MIGRATION") != "yes"
    init_containers = [{
        "name": "migrate",
        "image": "ghcr.io/nereidai/nereidlink-backend:0.0.0-dev",
    }] if current_has_migration else []
    current_template = {"spec": {"initContainers": init_containers}}
    deployment = {
        "metadata": {"name": "nereidlink", "uid": "link-deployment-uid"},
        "spec": {"template": copy.deepcopy(current_template)},
    }
    current_rs = {
        "metadata": {
            "name": "nereidlink-current",
            "uid": "link-current-rs-uid",
            "annotations": {"deployment.kubernetes.io/revision": "2"},
            "ownerReferences": [{
                "kind": "Deployment",
                "name": "nereidlink",
                "uid": "link-deployment-uid",
                "controller": True,
            }],
        },
        "spec": {"template": copy.deepcopy(current_template)},
    }
    replicasets = [current_rs]
    current_exit = 0 if os.environ.get("FAKE_LINK_MIGRATION_COMPLETE", "yes") == "yes" else 1
    pods = [link_pod("nereidlink-current-pod", current_rs, current_template, current_exit)]

    old_failed = os.environ.get("FAKE_LINK_OLD_FAILED_MIGRATION") == "yes"
    old_success = os.environ.get("FAKE_LINK_OLD_SUCCESS_CURRENT_WITHOUT_MIGRATION") == "yes"
    if old_failed or old_success:
        old_template = {
            "spec": {
                "initContainers": [{
                    "name": "migrate",
                    "image": "ghcr.io/nereidai/nereidlink-backend:0.0.0-dev-old",
                }],
            },
        }
        old_rs = {
            "metadata": {
                "name": "nereidlink-old",
                "uid": "link-old-rs-uid",
                "annotations": {"deployment.kubernetes.io/revision": "1"},
                "ownerReferences": [{
                    "kind": "Deployment",
                    "name": "nereidlink",
                    "uid": "link-deployment-uid",
                    "controller": True,
                }],
            },
            "spec": {"template": old_template},
        }
        replicasets.append(old_rs)
        pods.append(link_pod("nereidlink-old-pod", old_rs, old_template, 1 if old_failed else 0))
    return deployment, replicasets, pods


def run_kubectl(raw_args):
    namespace, args = namespace_and_args(raw_args)
    state = load_state()
    if not args:
        return 2
    command = args[0]
    if command == "config" and args[1:] == ["current-context"]:
        print(active_context(state))
        return 0
    if command == "config" and args[1] == "view":
        documents = kubeconfig_documents()
        requested = option(raw_args, "--context")
        known_contexts = {
            entry.get("name")
            for document in documents
            for entry in document.get("contexts", []) or []
            if isinstance(entry, dict)
        }
        if requested and known_contexts and requested not in known_contexts:
            print(f'context "{requested}" does not exist', file=sys.stderr)
            return 1
        current = requested
        if not current:
            current = next(
                (document["current-context"] for document in documents if document.get("current-context")),
                state["context"],
            )
        print(yaml.safe_dump({
            "apiVersion": "v1",
            "current-context": current,
            "kind": "Config",
        }, sort_keys=False), end="")
        return 0
    if command == "get" and args[1] == "--raw=/healthz":
        print("ok")
        return 0
    if command == "get":
        kind = args[1]
        name = args[2] if len(args) > 2 and not args[2].startswith("-") else ""
        fmt = output_format(args)
        if os.environ.get("FAKE_KUBECTL_QUERY_ERROR") == f"{kind}:{name}":
            print(
                os.environ.get(
                    "FAKE_KUBECTL_QUERY_ERROR_MESSAGE",
                    "simulated Kubernetes API query failure",
                ),
                file=sys.stderr,
            )
            return 2
        if kind == "namespace":
            if name not in state["namespaces"]:
                return not_found(kind, name)
            if fmt.startswith("{.metadata.uid}"):
                print(state["cluster_uid"] if name == "kube-system" else f"uid-{name}", end="")
            return 0
        if kind == "secret":
            key = secret_key(namespace, name)
            if key not in state["secrets"]:
                return not_found(kind, name)
            values = state["secrets"][key]
            if fmt == "json":
                print(json.dumps(secret_document(namespace, name, values)))
            elif fmt == "name":
                print(f"secret/{name}")
            elif fmt.startswith("{.data."):
                field = fmt[len("{.data."):].split("}", 1)[0].replace("\\", "")
                if field not in values:
                    return 1
                print(base64.b64encode(values[field].encode("utf-8")).decode("ascii"), end="")
            return 0
        if kind == "configmap":
            key = secret_key(namespace, name)
            if key not in state["secrets"]:
                return not_found(kind, name)
            if fmt == "name":
                print(f"configmap/{name}")
            return 0
        if kind == "storageclass":
            if name == state["local_storage_class"]:
                return 0
            if name != state["storage_class"]:
                return not_found(kind, name)
            if fmt == "{.parameters.server}":
                print(state["nfs_server"], end="")
            elif fmt == "{.parameters.share}":
                print(state["nfs_export"], end="")
            return 0
        if kind == "crd":
            return 0
        if kind in {"pvc", "pod"} and name:
            owners = state.get("storage_smoke_owners", {})
            if kind not in owners:
                return not_found(kind, name)
            if fmt.startswith("{.metadata.labels."):
                print(owners[kind], end="")
            return 0
        if namespace == "nereidlink" and kind == "deployment" and name == "nereidlink" and fmt == "json":
            deployment, _, _ = link_workloads()
            print(json.dumps(deployment))
            return 0
        if namespace == "nereidlink" and kind == "replicasets" and fmt == "json":
            _, replicasets, _ = link_workloads()
            print(json.dumps({"items": replicasets}))
            return 0
        if kind == "pods" and fmt == "json":
            if namespace == "nereidlink":
                _, _, pods = link_workloads()
            else:
                pods = [{
                    "metadata": {"name": f"{namespace}-fake"},
                    "spec": {"containers": [{"name": "main", "image": f"ghcr.io/nereidai/{namespace}:0.0.0-dev"}]},
                    "status": {"containerStatuses": [{
                        "name": "main",
                        "imageID": "ghcr.io/nereidai/fake@sha256:" + "1" * 64,
                    }]},
                }]
            print(json.dumps({"items": pods}))
            return 0
        if kind == "nodes" and fmt == "json":
            print('{"items": []}')
            return 0
        if kind == "svc":
            return 0
    if command == "create":
        if args[1] == "namespace":
            print(json.dumps({"kind": "Namespace", "metadata": {"name": args[2]}}))
            return 0
        if args[1:3] == ["secret", "generic"]:
            name = args[3]
            values = {}
            for arg in args:
                if arg.startswith("--from-file="):
                    specification = arg.split("=", 1)[1]
                    key, filename = specification.split("=", 1)
                    values[key] = Path(filename).read_text(encoding="utf-8")
            print(json.dumps(secret_document(namespace, name, values)))
            return 0
    if command == "apply":
        filename = option(args, "-f")
        content = sys.stdin.read() if filename == "-" else ""
        if content.lstrip().startswith("{"):
            apply_json(json.loads(content))
        return 0
    if command == "patch" and args[1] == "secret":
        name = args[2]
        patch = json.loads(Path(option(args, "--patch-file")).read_text(encoding="utf-8"))
        key = secret_key(namespace, name)
        if key not in state["secrets"]:
            return not_found("secret", name)
        values = state["secrets"][key]
        values.update(patch.get("stringData", {}))
        save_state(state)
        return 0
    if command in {"rollout", "wait"}:
        return 0
    if command == "delete":
        if args[1] in {"pvc", "pod"}:
            state.get("storage_smoke_owners", {}).pop(args[1], None)
            save_state(state)
        return 0
    if command == "logs":
        print("fake Link startup completed")
        return 0
    if command == "exec":
        print("fake-device-ca")
        return 0
    print(f"unsupported fake kubectl command: {raw_args}", file=sys.stderr)
    return 2


def write_verifier_checkout(destination):
    script = destination / "scripts" / "60_verify" / "nf-check.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'nf\\t60_verify/nf-check\\n' >> \"$FAKE_SUITE_CALLS\"\n",
        encoding="utf-8",
    )
    script.chmod(0o700)


def run_git(args):
    if args[0] == "clone":
        destination = Path(args[-1])
        (destination / ".git").mkdir(parents=True)
        (destination / ".git" / "commit-available").write_text("abcdef1\n", encoding="utf-8")
        return 0
    if "-C" in args:
        destination = Path(args[args.index("-C") + 1])
        available = destination / ".git" / "commit-available"
        if "cat-file" in args:
            return 0 if available.is_file() else 1
        if "fetch" in args:
            available.parent.mkdir(parents=True, exist_ok=True)
            available.write_text("abcdef1\n", encoding="utf-8")
            return 0
        if "checkout" in args:
            if not available.is_file():
                return 1
            write_verifier_checkout(destination)
            return 0
        if "rev-parse" in args:
            if not available.is_file():
                return 1
            print("abcdef1" + "a" * 33)
            return 0
    return 2


def main():
    tool = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if tool == "python3":
        if args == ["-c", "import boto3"]:
            return 0
        os.execv("/usr/bin/python3", ["/usr/bin/python3", *args])
    record(tool, args)
    if tool == "helm":
        return run_helm(args)
    if tool == "oras":
        return run_oras(args)
    if tool == "kubectl":
        return run_kubectl(args)
    if tool == "git":
        return run_git(args)
    if tool == "curl":
        print("{}")
        return 0
    if tool == "getent":
        return 0
    if tool == "openssl":
        if args[:1] == ["rand"]:
            print(secrets.token_hex(int(option(args, "-hex"))))
            return 0
        if args[:1] == ["x509"]:
            print("subject=fake device CA")
            return 0
    print(f"unsupported fake tool invocation: {tool} {args}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
