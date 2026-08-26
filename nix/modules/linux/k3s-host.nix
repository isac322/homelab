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
  firewallService =
    if hostConfig.packageBackend == "pacman" then
      "iptables.service"
    else
      "netfilter-persistent.service";
  server = hostConfig.k3sRole == "server";
  wg0Address = topology.wg0.nodes.${name}.address or null;
  strip = address: if address == null then null else builtins.head (lib.splitString "/" address);
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
    default = "/run/credentials/homelab-k3s.service/k3s-token";
    description = "Machine-encrypted K3s token loaded by systemd for the daemon.";
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
      description = "Run K3s ${if server then "server" else "agent"}";
      wantedBy = [ "multi-user.target" ];
      requires = [ firewallService ];
      after = [
        "network-online.target"
        "systemd-networkd.service"
        firewallService
      ]
      ++ lib.optionals config.homelab.zram [ "dev-zram0.swap" ]
      ++ lib.optionals hostConfig.iscsiClient [
        "iscsid.service"
        "open-iscsi.service"
      ];
      wants = [
        "network-online.target"
      ]
      ++ lib.optionals config.homelab.zram [ "dev-zram0.swap" ]
      ++ lib.optionals hostConfig.iscsiClient [
        "iscsid.service"
        "open-iscsi.service"
      ];
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
        test -x /usr/local/bin/k3s
        runtime_config=/run/rancher/k3s-managed/config.yaml
        install -m 0600 /etc/rancher/k3s/config.yaml "$runtime_config"
        test -s ${lib.escapeShellArg tokenPath}
        for unit in k3s.service k3s-agent.service; do
          test "$(systemctl is-active "$unit" 2>/dev/null || true)" != active || {
            echo "$unit is still active; stop and disable the legacy K3s unit before activation" >&2
            exit 1
          }
        done
        exec /usr/local/bin/k3s ${if server then "server" else "agent"} --config "$runtime_config"
      '';
      serviceConfig = {
        Type = "exec";
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
        LoadCredentialEncrypted = [
          "k3s-token:/var/lib/homelab-secrets/active/k3s-token.cred"
        ];
      };
      environment = lib.optionalAttrs server { GOMEMLIMIT = "2GiB"; };
    };
  };
}
