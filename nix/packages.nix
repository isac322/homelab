{
  pkgs,
  self,
  topology,
}:
let
  runtimeInputs = with pkgs; [
    age
    bash
    coreutils
    curl
    git
    gawk
    gnugrep
    gnused
    jq
    kubectl
    kubernetes-helm
    nix
    openssh
    openssl
    sops
    wireguard-tools
    yq-go
  ];
  mkApp =
    name: description: script: prefix:
    pkgs.writeShellApplication {
      inherit name runtimeInputs;
      text = ''
        export HOMELAB_REPO_ROOT="''${HOMELAB_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
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
  homelab-host = hostApp "homelab-host" "Manage declarative homelab hosts" "";
  adopt-host = hostApp "adopt-host" "Capture and adopt an existing Linux host" "adopt-host";
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
    mkApp "k3s-handoff" "Run the guarded legacy-to-Nix K3s service handoff" ./scripts/k3s-handoff
      "";
  onboard-k3s-node =
    hostApp "onboard-k3s-node" "Stage a cluster token and prepare a new declarative K3s node"
      "onboard-k3s-node";
  bootstrap-k3s =
    hostApp "bootstrap-k3s" "Bootstrap Cilium only for an explicitly new K3s cluster"
      "bootstrap-k3s";
  upgrade-k3s = hostApp "upgrade-k3s" "Perform ordered K3s minor upgrades" "upgrade-k3s";
  bootstrap-argocd =
    hostApp "bootstrap-argocd" "Bootstrap Argo CD only for an explicitly new cluster"
      "bootstrap-argocd";
  register-clusters =
    mkApp "register-clusters" "Register an existing Kubernetes cluster in Argo CD"
      ./scripts/register-cluster
      "";
  register-cluster =
    mkApp "register-cluster" "Compatibility command for register-clusters" ./scripts/register-cluster
      "";
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
