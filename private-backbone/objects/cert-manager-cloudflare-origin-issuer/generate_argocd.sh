#!/usr/bin/env sh

set -ex

kubectl create secret generic cf-origin-ca-key -n argocd --dry-run=client --from-file cloudflare_origin_ca_key -o yaml | kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system -n argocd --format yaml > argocd_cf-origin-ca-key.yaml