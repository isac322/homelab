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
  manageRules = config.homelab.firewall.manageRules;
  firewallReconcile = pkgs.writeShellScript "homelab-k3s-firewall-reconcile" (
    if manageRules then
      ''
        set -u
        exec 9>/run/homelab-k3s-firewall-reconcile.lock
        ${pkgs.util-linux}/bin/flock -n 9 || exit 0
        iptables=${pkgs.iptables}/bin/iptables
        awk=${pkgs.gawk}/bin/awk
        sort=${pkgs.coreutils}/bin/sort
        sleep=${pkgs.coreutils}/bin/sleep
        cilium_ready() {
          "$iptables" -S INPUT | "$awk" '/-j CILIUM_INPUT$/ || /-j KUBE-FIREWALL$/ { found = 1 } END { exit !found }' \
            && "$iptables" -S FORWARD | "$awk" '/-j CILIUM_FORWARD$/ { found = 1 } END { exit !found }'
        }
        firewall_ordered() {
          "$iptables" -S INPUT | "$awk" '
            /-j CILIUM_INPUT$/ || /-j KUBE-FIREWALL$/ { native = NR }
            /-j HOMELAB_INPUT$/ { homelab = NR; count++ }
            END { exit !(native && homelab > native && count == 1) }
          ' \
            && "$iptables" -S FORWARD | "$awk" '
              /-j CILIUM_FORWARD$/ { native = NR }
              /-j HOMELAB_FORWARD$/ { homelab = NR; count++ }
              END { exit !(native && homelab > native && count == 1) }
            '
        }
        place_jump() {
          local chain=$1 target=$2 position=$3 keep=$3
          "$iptables" --wait -I "$chain" "$position" -j "$target"
          for index in $("$iptables" -S "$chain" | "$awk" -v target="$target" 'NR > 1 && $(NF - 1) == "-j" && $NF == target { print NR - 1 }' | "$sort" -rn); do
            if test "$index" -eq "$keep"; then continue; fi
            "$iptables" --wait -D "$chain" "$index"
            if test "$index" -lt "$keep"; then keep=$((keep - 1)); fi
          done
        }
        attempt=0
        stable=0
        while test "$attempt" -lt 90 && test "$stable" -lt 3; do
          if firewall_ordered; then
            stable=$((stable + 1))
          elif cilium_ready; then
            stable=0
            input_position=$("$iptables" -S INPUT | "$awk" '/-j CILIUM_INPUT$/ || /-j KUBE-FIREWALL$/ { position = NR } END { print position }')
            forward_position=$("$iptables" -S FORWARD | "$awk" '/-j CILIUM_FORWARD$/ { position = NR } END { print position }')
            place_jump INPUT HOMELAB_INPUT "$input_position"
            place_jump FORWARD HOMELAB_FORWARD "$forward_position"
          else
            stable=0
          fi
          attempt=$((attempt + 1))
          "$sleep" 2
        done
        if test "$stable" -lt 3; then
          echo "Cilium and HOMELAB firewall ordering did not stabilize after K3s start" >&2
          exit 1
        fi
      ''
    else
      ''
        exit 0
      ''
  );
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
        ExecStartPost = "-${firewallReconcile}";
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
