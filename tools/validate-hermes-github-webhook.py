#!/usr/bin/env python3
"""Validate the GitHub → Hermes webhook GitOps contract."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / "apps/objects/hermes/isacmes.yaml"
INGRESS = ROOT / "apps/objects/hermes/github-webhook.yaml"
SECRETS = ROOT / "apps/objects/hermes/external-secret.yaml"


def require(text: str, expected: str, path: Path) -> None:
    if expected not in text:
        raise SystemExit(f"{path}: missing required content: {expected!r}")


def main() -> None:
    instance = INSTANCE.read_text()
    ingress = INGRESS.read_text()
    secrets = SECRETS.read_text()

    for expected in (
        "webhook:",
        "enabled: true",
        "secret: ${GITHUB_WEBHOOK_SECRET}",
        "github-events:",
        "networking:",
        "name: webhook",
        "targetPort: 8644",
        "httpRoute:",
        "isacmes-webhook.bhyoo.com",
        "servicePortName: webhook",
        "allowedIngressNamespaces:",
        "- ingress-ctrl",
    ):
        require(instance, expected, INSTANCE)
    if "INSECURE_NO_AUTH" in instance:
        raise SystemExit(f"{INSTANCE}: insecure webhook auth is forbidden")

    for event in (
        "issues",
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "pull_request_review_thread",
        "discussion",
        "discussion_comment",
    ):
        require(instance, f'"{event}"', INSTANCE)

    for expected in (
        "github_event.py:",
        "sqlite3.connect",
        "/opt/data/request-inbox/github-webhook.sqlite3",
        "INSERT INTO deliveries",
        "[SILENT]",
    ):
        require(ingress, expected, INGRESS)

    require(secrets, "secretKey: githubWebhookSecret", SECRETS)
    require(secrets, "/homelab/cluster/backbone/token/github/isacmes-webhook", SECRETS)
    print("GitHub → Hermes webhook GitOps contract: OK")


if __name__ == "__main__":
    main()
