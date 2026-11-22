#!/usr/bin/env python3
"""Check Flareway convergence and send signed, side-effect-free GitHub pings."""

import argparse
import base64
import hashlib
import hmac
import json
import re
import subprocess
import urllib.error
import urllib.request
import uuid

CILIUM_CONTROLLER_NAME = "io.cilium/gateway-controller"
GATEWAY_CLASS_NAME_RE = re.compile(
    r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*$"
)


def is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def kubectl(context, *args):
    cmd = ["kubectl", "--context", context, *args, "-o", "json"]
    try:
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "kubectl timed out after " + str(error.timeout) + "s: " + " ".join(args)
        ) from None
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "").strip() or ("exit status " + str(error.returncode))
        raise RuntimeError("kubectl " + " ".join(args) + " failed: " + detail) from None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("kubectl " + " ".join(args) + " returned invalid JSON") from None


def converged(resource, condition):
    if not isinstance(resource, dict):
        return False
    metadata = resource.get("metadata")
    if not isinstance(metadata, dict):
        return False
    generation = metadata.get("generation")
    if not is_positive_int(generation):
        return False
    status = resource.get("status")
    if not isinstance(status, dict):
        return False
    conditions = status.get("conditions")
    if not isinstance(conditions, list):
        return False
    for item in conditions:
        if not isinstance(item, dict):
            continue
        observed = item.get("observedGeneration")
        if (
            item.get("type") == condition
            and item.get("status") == "True"
            and is_positive_int(observed)
            and observed == generation
        ):
            return True
    return False


def post(host, path, secret, valid=True):
    # Ping is handled without creating an issue-agent job or changing a Git repo.
    body = b'{"zen":"homelab public webhook verification"}'
    signature = hmac.new(secret, body, hashlib.sha256).hexdigest() if valid else "0" * 64
    request = urllib.request.Request(
        "https://" + host + path,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "GitHub-Hookshot/homelab-ingress-qa",
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": "sha256=" + signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        try:
            return error.code, error.read()
        finally:
            error.close()


def valid_gateway_class_name(value):
    return (
        isinstance(value, str)
        and len(value) <= 253
        and GATEWAY_CLASS_NAME_RE.match(value) is not None
    )


def verify_cilium_gateways(context, gateway_names=("bhyoo-gateway", "nas-gateway")):
    gateway_classes = {}
    failures = []

    for name in gateway_names:
        try:
            gateway = kubectl(context, "-n", "ingress-ctrl", "get", "gateway", name)
        except RuntimeError as error:
            failures.append(name + ": " + str(error))
            continue

        if not isinstance(gateway, dict):
            failures.append(name + ": unexpected Gateway payload")
            continue

        spec = gateway.get("spec")
        class_name = spec.get("gatewayClassName") if isinstance(spec, dict) else None
        if not valid_gateway_class_name(class_name):
            failures.append(name + ": missing or invalid spec.gatewayClassName " + repr(class_name))
        else:
            if class_name not in gateway_classes:
                try:
                    gateway_classes[class_name] = (
                        kubectl(context, "get", "gatewayclass", class_name),
                        None,
                    )
                except RuntimeError as error:
                    gateway_classes[class_name] = (None, str(error))

            gateway_class, class_error = gateway_classes[class_name]
            if class_error is not None:
                failures.append(name + ": GatewayClass " + class_name + ": " + class_error)
            elif not isinstance(gateway_class, dict):
                failures.append(name + ": GatewayClass " + class_name + " payload is invalid")
            else:
                gc_spec = gateway_class.get("spec")
                controller = gc_spec.get("controllerName") if isinstance(gc_spec, dict) else None
                if controller != CILIUM_CONTROLLER_NAME:
                    failures.append(
                        name
                        + ": GatewayClass "
                        + class_name
                        + " controllerName is "
                        + repr(controller)
                        + ", expected "
                        + repr(CILIUM_CONTROLLER_NAME)
                    )
                if not converged(gateway_class, "Accepted"):
                    failures.append(name + ": GatewayClass " + class_name + " is not Accepted")

        for condition in ("Accepted", "Programmed"):
            if not converged(gateway, condition):
                failures.append(name + ": Gateway condition " + condition + " has not converged")

    if failures:
        raise RuntimeError("Cilium Gateway check failed: " + "; ".join(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default="homelab-backbone")
    args = parser.parse_args()
    context = args.context

    gateway = kubectl(context, "-n", "flareway-system", "get", "gateway", "public-webhooks")
    if not converged(gateway, "Programmed"):
        raise RuntimeError("Flareway Gateway has not converged")
    tunnel = kubectl(context, "-n", "flareway-system", "get", "cloudflaretunnel", "public-webhooks")
    for condition in ("Ready", "DNSReady"):
        if not converged(tunnel, condition):
            raise RuntimeError("Flareway tunnel has not converged: " + condition)

    pods = kubectl(context, "-n", "flareway-system", "get", "pods")["items"]
    active = [pod for pod in pods if not pod["metadata"].get("deletionTimestamp")]
    dataplane = [
        pod for pod in active
        if any(container["name"] == "cloudflared" for container in pod["spec"]["containers"])
    ]
    if not dataplane:
        raise RuntimeError("No Flareway data-plane pods found")
    for pod in active:
        name = pod["metadata"]["name"]
        statuses = pod.get("status", {}).get("containerStatuses", [])
        if len(statuses) != len(pod["spec"]["containers"]) or not all(s["ready"] for s in statuses):
            raise RuntimeError("Unready container: " + name)
        for container in pod["spec"]["containers"]:
            resources = container.get("resources", {})
            requests = resources.get("requests", {})
            limits = resources.get("limits", {})
            if not all(requests.get(key) for key in ("cpu", "memory")) or not limits.get("memory"):
                raise RuntimeError("Missing resource guarantees: " + name + "/" + container["name"])
            if "cpu" in limits:
                raise RuntimeError("Unexpected CPU limit: " + name + "/" + container["name"])
    if any(pod["spec"].get("nodeName") == "macmini" for pod in dataplane):
        raise RuntimeError("A tunnel connector is on the WARP-incompatible node")

    cases = (
        ("argocd", "argocd-webhook", "argocd-webhook.bhyoo.com", "/api/webhook", "argocd-secret", "webhook.github.secret"),
        ("issue-agent", "issue-agent-webhook", "issue-agent-webhook.bhyoo.com", "/webhooks/github", "issue-agent-webhook", "secret"),
    )
    for namespace, name, host, path, secret_name, secret_key in cases:
        route = kubectl(context, "-n", namespace, "get", "httproute", name)
        parents = [
            parent for parent in route.get("status", {}).get("parents", [])
            if parent.get("controllerName") == "flareway.bhyoo.com/gateway-controller"
            and parent["parentRef"]["name"] == gateway["metadata"]["name"]
            and parent["parentRef"].get("namespace") == "flareway-system"
        ]
        if not parents or not any(
            all(converged({"metadata": route["metadata"], "status": parent}, condition)
                for condition in ("Accepted", "ResolvedRefs"))
            for parent in parents
        ):
            raise RuntimeError("HTTPRoute has not converged: " + namespace + "/" + name)
        secret = base64.b64decode(kubectl(context, "-n", namespace, "get", "secret", secret_name)["data"][secret_key])
        status, response = post(host, path, secret)
        if status != 200:
            raise RuntimeError("Signed ping failed: " + host + " HTTP " + str(status))
        if namespace == "issue-agent":
            if json.loads(response) != {"status": "pong"}:
                raise RuntimeError("Signed ping did not reach the issue-agent bridge")
            status, response = post(host, path, secret, valid=False)
            if status != 401 or json.loads(response) != {"status": "bad_signature"}:
                raise RuntimeError("Invalid webhook signature was not rejected")
        for unmatched in (path + "/", path + "/extra"):
            status, _ = post(host, unmatched, secret)
            if status != 404:
                raise RuntimeError("Exact-path boundary failed: " + host + unmatched)
        print("PASS", host, "signed ping and exact-path boundary")

    verify_cilium_gateways(context)
    print("PASS Flareway resources, placement, and Cilium Gateways")


if __name__ == "__main__":
    main()
