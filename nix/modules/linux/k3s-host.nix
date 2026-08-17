{
  config,
  lib,
  pkgs,
  name,
  hostConfig,
  topology,
  ...
}:
let
  enabled = hostConfig.k3sRole != null;
  server = hostConfig.k3sRole == "server";
  wg0Address = topology.wg0.nodes.${name}.address or null;
  strip = address: if address == null then null else builtins.head (lib.splitString "/" address);
  k3sPackage = import ../../k3s-package.nix {
    inherit pkgs;
    version = hostConfig.k3sVersion;
  };
  tokenPath = config.homelab.k3s.tokenPath;
  yamlList = values: lib.concatMapStringsSep "\n" (value: "  - ${value}") values;
  serverConfig =
    if server then
      ''
        server: ${hostConfig.k3sServer}
        node-ip: ${hostConfig.lanAddress}
        token-file: ${tokenPath}
        etcd-expose-metrics: true
        flannel-backend: none
        disable-network-policy: true
        disable-kube-proxy: true
        disable-helm-controller: true
        disable:
          - traefik
          - servicelb
        advertise-address: ${hostConfig.lanAddress}
        node-external-ip: ${strip wg0Address}
        secrets-encryption: true
        tls-san:
          - ${strip wg0Address}
          - ${hostConfig.wireguardEndpointHost}
          - k8s.backbone.homelab.bhyoo.com
        kubelet-arg:
          - image-gc-high-threshold=60
          - image-gc-low-threshold=40
          - feature-gates=ImageVolume=true
          - feature-gates=NodeSwap=true
      ''
    else
      ''
        server: ${hostConfig.k3sServer}
        node-ip: ${hostConfig.lanAddress}
        token-file: ${tokenPath}
        node-external-ip: ${strip wg0Address}
        kubelet-arg:
          - image-gc-high-threshold=60
          - image-gc-low-threshold=40
          - feature-gates=ImageVolume=true
          - feature-gates=NodeSwap=true
      '';
in
{
  options.homelab.k3s.tokenPath = lib.mkOption {
    type = lib.types.str;
    default = "/run/homelab-secrets/active/k3s/server-token";
    description = "SOPS-staged existing K3s token; never copied into the Nix store.";
  };

  config = lib.mkIf enabled {
    environment.etc."rancher/k3s/config.yaml" = {
      text =
        serverConfig
        + lib.optionalString (
          hostConfig.k3sLabels != [ ]
        ) "\nnode-label:\n${yamlList hostConfig.k3sLabels}\n";
      replaceExisting = true;
      mode = "0600";
    };
    systemd.services.homelab-k3s = {
      description = "Run pinned K3s ${if server then "server" else "agent"}";
      wantedBy = [ "system-manager.target" ];
      after = [
        "network-online.target"
        "homelab-distro-packages.service"
        "homelab-wireguard.service"
        "homelab-firewall.service"
        "homelab-sysctl.service"
        "homelab-zram.service"
        "homelab-thp.service"
        "homelab-k3s-legacy-cleanup.service"
        "homelab-ksm.service"
      ];
      wants = [ "network-online.target" ];
      path = [
        pkgs.coreutils
        pkgs.systemd
        pkgs.kmod
        pkgs.iptables
        pkgs.iproute2
        pkgs.util-linux
        pkgs.ethtool
      ];
      script = ''
        set -eu
        runtime_config=/run/rancher/k3s-managed/config.yaml
        install -m 0600 /etc/rancher/k3s/config.yaml "$runtime_config"
        test -s ${lib.escapeShellArg tokenPath}
        for unit in k3s.service k3s-agent.service; do
          test "$(systemctl is-active "$unit" 2>/dev/null || true)" != active || {
            echo "$unit is still active; stop and disable the legacy K3s unit before activation" >&2
            exit 1
          }
        done
        exec ${k3sPackage}/bin/k3s ${if server then "server" else "agent"} --config "$runtime_config"
      '';
      serviceConfig = {
        Type = if server then "notify" else "exec";
        ExecStartPre = [
          "-${pkgs.kmod}/bin/modprobe br_netfilter"
          "-${pkgs.kmod}/bin/modprobe overlay"
        ];
        Restart = "always";
        RestartSec = "5s";
        KillMode = "process";
        Delegate = true;
        LimitNOFILE = 1048576;
        LimitNPROC = "infinity";
        LimitCORE = "infinity";
        TasksMax = "infinity";
        TimeoutStartSec = 0;
        RuntimeDirectory = "rancher/k3s-managed";
        RuntimeDirectoryMode = "0700";
      };
      environment = lib.optionalAttrs server { GOMEMLIMIT = "2GiB"; };
    };
    systemd.services.homelab-k3s-legacy-cleanup = lib.mkIf config.homelab.allowDestructiveCommit {
      description = "Remove superseded installer-owned K3s launch files";
      wantedBy = [ "system-manager.target" ];
      before = [ "homelab-k3s.service" ];
      path = [
        pkgs.coreutils
        pkgs.systemd
      ];
      script = ''
        set -eu
        for unit in k3s.service k3s-agent.service; do
          fragment=$(systemctl show -p FragmentPath --value "$unit" 2>/dev/null || true)
          case "$fragment" in
            /etc/systemd/system/*) rm -f "$fragment" ;;
          esac
          rm -f "/etc/systemd/system/multi-user.target.wants/$unit"
        done
        rm -f \
          /usr/local/bin/k3s \
          /usr/local/bin/k3s-killall.sh \
          /usr/local/bin/k3s-uninstall.sh \
          /usr/local/bin/k3s-agent-uninstall.sh
        systemctl daemon-reload
      '';
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
    };
  };
}
