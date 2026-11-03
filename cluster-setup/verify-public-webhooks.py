#!/usr/bin/env python3
"""Check Flareway convergence and send signed, side-effect-free GitHub pings."""

import argparse
import base64
import hashlib
import hmac
import json
import subprocess
import urllib.error
import urllib.request
import uuid


def kubectl(context, *args):
    result = subprocess.run(
        ["kubectl", "--context", context, *args, "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    return json.loads(result.stdout)


def converged(resource, condition):
    generation = resource["metadata"]["generation"]
    return any(
        item["type"] == condition
        and item["status"] == "True"
        and item.get("observedGeneration") == generation
        for item in resource.get("status", {}).get("conditions", [])
    )


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
        return error.code, error.read()


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

    for name in ("bhyoo-gateway", "nas-gateway"):
        gateway = kubectl(context, "-n", "ingress-ctrl", "get", "gateway", name)
        if gateway["spec"]["gatewayClassName"] != "cilium" or not converged(gateway, "Programmed"):
            raise RuntimeError("Cilium Gateway is not healthy: " + name)
    print("PASS Flareway resources, placement, and Cilium Gateways")


if __name__ == "__main__":
    main()
