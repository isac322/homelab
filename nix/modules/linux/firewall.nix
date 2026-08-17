{
  config,
  lib,
  pkgs,
  hostConfig,
  topology,
  ...
}:
let
  cfg = config.homelab.firewall;
  k3s = hostConfig.k3sRole != null;
  server = hostConfig.k3sRole == "server";
  gateway = hostConfig.firewall.wireguardGateway or false;
  localNetwork = cfg.localNetwork;
  wgPorts = map (_: topology.wg0.listenPort) hostConfig.wireguard;
  body = ''
    :HOMELAB_INPUT - [0:0]
    :HOMELAB_FORWARD - [0:0]
    :HOMELAB_TCP - [0:0]
    :HOMELAB_UDP - [0:0]
    -F HOMELAB_INPUT
    -F HOMELAB_FORWARD
    -F HOMELAB_TCP
    -F HOMELAB_UDP
    -A HOMELAB_INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
    -A HOMELAB_INPUT -i lo -j ACCEPT
    -A HOMELAB_INPUT -m conntrack --ctstate INVALID -j DROP
    -A HOMELAB_INPUT -p icmp --icmp-type echo-request -m conntrack --ctstate NEW -j ACCEPT
    -A HOMELAB_INPUT -p udp -m conntrack --ctstate NEW -j HOMELAB_UDP
    -A HOMELAB_INPUT -p tcp --syn -m conntrack --ctstate NEW -j HOMELAB_TCP
    -A HOMELAB_INPUT -p udp -j REJECT --reject-with icmp-port-unreachable
    -A HOMELAB_INPUT -p tcp -j REJECT --reject-with tcp-reset
    -A HOMELAB_INPUT -j REJECT --reject-with icmp-proto-unreachable
    -A HOMELAB_TCP -p tcp --dport 22 -j ACCEPT
    ${lib.concatMapStringsSep "\n" (
      port: "-A HOMELAB_UDP -i ${hostConfig.defaultInterface} -p udp --dport ${toString port} -j ACCEPT"
    ) wgPorts}
    -A HOMELAB_UDP -s ${localNetwork} -p udp --dport 5353 -j ACCEPT
    ${lib.optionalString server "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 6443 -j ACCEPT"}
    ${lib.optionalString server "-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 6443 -j ACCEPT"}
    ${lib.optionalString (
      server && builtins.elem "wg0" hostConfig.wireguard
    ) "-A HOMELAB_TCP -i wg0 -s ${topology.wg0.network} -p tcp --dport 6443 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 10250 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 10250 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9100 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 9100 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4240 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4244:4245 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 4244:4245 -j ACCEPT"}
    ${lib.optionalString server "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 2379:2381 -j ACCEPT"}
    ${lib.optionalString hostConfig.iscsiServer "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 3260 -j ACCEPT"}
    ${lib.optionalString gateway "-A HOMELAB_FORWARD -i wg0 -o wg0 -s ${topology.wg0.trustedNetwork} -d ${topology.wg0.edgeNetwork} -j ACCEPT\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s ${topology.wg0.edgeNetwork} -d ${topology.wg0.trustedNetwork} -j ACCEPT\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s ${topology.wg0.edgeNetwork} -d ${topology.wg0.edgeNetwork} -j DROP"}
  '';
  rules = ''
    *filter
    ${body}
    COMMIT
  '';
in
{
  options.homelab.firewall = {
    enable = lib.mkEnableOption "homelab firewall" // {
      default = true;
    };
    localNetwork = lib.mkOption {
      type = lib.types.str;
      default = "192.168.219.0/24";
      description = "Host-local trusted LAN CIDR.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.etc."homelab/firewall.rules" = {
      text = rules;
      mode = "0600";
    };
    systemd.services.homelab-firewall = {
      description = "Install idempotent homelab-owned iptables policy";
      wantedBy = [ "system-manager.target" ];
      wants = [ "network-pre.target" ];
      before = [
        "network-pre.target"
        "systemd-networkd.service"
        "homelab-k3s.service"
      ];
      path = [
        pkgs.iptables
        pkgs.coreutils
        pkgs.gawk
      ];
      script = ''
        set -eu
        iptables-save > /run/homelab-firewall.previous
        while iptables -C INPUT -j HOMELAB_INPUT 2>/dev/null; do iptables -D INPUT -j HOMELAB_INPUT; done
        while iptables -C FORWARD -j HOMELAB_FORWARD 2>/dev/null; do iptables -D FORWARD -j HOMELAB_FORWARD; done
        iptables-restore --noflush --wait < /etc/homelab/firewall.rules
        iptables -P INPUT DROP
        iptables -P FORWARD DROP
        iptables -P OUTPUT ACCEPT
        input_position=$(iptables -S INPUT | awk '/-j CILIUM_INPUT$/ || /-j KUBE-FIREWALL$/ { position = NR } END { print position ? position : 1 }')
        forward_position=$(iptables -S FORWARD | awk '/-j CILIUM_FORWARD$/ { position = NR } END { print position ? position : 1 }')
        iptables -I INPUT "$input_position" -j HOMELAB_INPUT
        iptables -I FORWARD "$forward_position" -j HOMELAB_FORWARD
      '';
      preStop = "test ! -s /run/homelab-firewall.previous || iptables-restore --wait < /run/homelab-firewall.previous";
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        DefaultDependencies = false;
      };
    };
  };
}
