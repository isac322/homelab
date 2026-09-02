{
  pkgs,
  self,
  topology,
}:
let
  # macOS can reject LAN connections from Nix OpenSSH while allowing /usr/bin/ssh.
  # Prefer the native client for operator sessions, while retaining packaged
  # OpenSSH for Linux and companion utilities.
  darwinNativeSsh = pkgs.writeShellScriptBin "ssh" ''
    exec /usr/bin/ssh "$@"
  '';
  runtimeInputs =
    pkgs.lib.optionals pkgs.stdenv.isDarwin [ darwinNativeSsh ]
    ++ (with pkgs; [
      age
      bash
      coreutils
      curl
      git
      gawk
      findutils
      gnugrep
      gnused
      gnutar
      jq
      kubectl
      kubernetes-helm
      kubernetes-helmPlugins.helm-diff
      nix
      openssh
      openssl
      python3
      sops
      opentofu
      wireguard-tools
      yq-go
    ]);
  mkApp =
    name: description: script: prefix:
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      text = ''
        export HOMELAB_REPO_ROOT="''${HOMELAB_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
        export HELM_PLUGINS=${pkgs.kubernetes-helmPlugins.helm-diff}
        exec ${script} ${prefix} "$@"
      '';
      meta = {
        inherit description;
        mainProgram = name;
      };
    };
  hostApp =
    name: description: command:
    mkApp name description ./scripts/homelab-host command;
  secretApp =
    name: description: command:
    mkApp name description ./scripts/wireguard-secrets command;
in
{
  bootstrap-host =
    hostApp "bootstrap-host" "Install host prerequisites and establish noninteractive sudo"
      "bootstrap-host";
  homelab-host = hostApp "homelab-host" "Manage declarative homelab hosts" "";
  adopt-host =
    mkApp "adopt-host" "Capture the pre-Nix state of an existing Linux host" ./scripts/adopt-host
      "";
  reconcile-host =
    hostApp "reconcile-host" "Idempotently converge an active Nix-owned Linux host"
      "reconcile";
  rollout-peers =
    mkApp "rollout-peers" "Reconcile one node's WireGuard peers without a full host switch"
      ./scripts/rollout-peers
      "";
  provision-host =
    mkApp "provision-host" "Provision a Git-declared new Linux host" ./scripts/provision-host
      "";
  decommission-host =
    mkApp "decommission-host" "Remove a declared decommissioning host from active peers"
      ./scripts/decommission-host
      "";
  deploy = hostApp "deploy" "Prepare a Linux system-manager generation" "prepare";
  reconcile-distro-packages =
    hostApp "reconcile-distro-packages"
      "Install required distro packages without upgrading the distribution"
      "reconcile-distro-packages";
  bootstrap-age-identity =
    secretApp "bootstrap-age-identity" "Create or print a host-local age recipient"
      "bootstrap-age-identity";
  import-wireguard-host =
    secretApp "import-wireguard-host" "Verify or encrypt an existing host WireGuard identity"
      "import-host";
  copy-k3s-token =
    secretApp "copy-k3s-token" "Copy an existing cluster join token into one host ciphertext bundle"
      "copy-k3s-token";
  stage-secrets =
    secretApp "stage-secrets" "Stage an encrypted host secret bundle as an atomic runtime generation"
      "stage-secrets";
  gen-psk = secretApp "gen-psk" "Check or generate an immutable WireGuard link PSK" "gen-psk";
  rekey-secrets =
    secretApp "rekey-secrets" "Re-encrypt secret bundles for a recipient transition"
      "rekey-secrets";
  rotate-psk = secretApp "rotate-psk" "Rotate one managed WireGuard link PSK" "rotate-psk";
  k3s-handoff =
    mkApp "k3s-handoff" "Manage persistent full-host rollback across a Nix activation"
      ./scripts/k3s-handoff
      "";
  onboard-k3s-node =
    hostApp "onboard-k3s-node" "Install the live K3s layout, stage its token, and prepare the node"
      "onboard-k3s-node";
  bootstrap-k3s =
    hostApp "bootstrap-k3s" "Bootstrap Cilium only for an explicitly new K3s cluster"
      "bootstrap-k3s";
  bootstrap-argocd =
    hostApp "bootstrap-argocd" "Bootstrap Argo CD only for an explicitly new cluster"
      "bootstrap-argocd";
  issue-kubeconfig =
    mkApp "issue-kubeconfig" "Issue a Kubernetes client kubeconfig" ./scripts/issue-kubeconfig
      "";
  verify-host = hostApp "verify-host" "Verify a Linux host after activation or reboot" "verify-host";
  verify-cluster =
    mkApp "verify-cluster" "Verify one Kubernetes API readiness endpoint" ./scripts/verify-cluster
      "";
  sync-bootstrap-secret =
    mkApp "sync-bootstrap-secret" "Import a Terraform bootstrap credential directly into SOPS"
      ./scripts/sync-bootstrap-secret
      "";
  render-macbook-wireguard =
    mkApp "render-macbook-wireguard"
      "Render and validate the private MacBook full-mesh WireGuard config"
      ./scripts/render-macbook-wireguard
      "";
}
