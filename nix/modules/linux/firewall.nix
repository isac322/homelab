{
  config,
  lib,
  hostConfig,
  topology,
  ...
}:
let
  cfg = config.homelab.firewall;
  k3s = hostConfig.k3sRole != null;
  server = hostConfig.k3sRole == "server";
  gateway = hostConfig.firewall.wireguardGateway or false;
  sambaClients = cfg.sambaClients;
  netbios = cfg.netbios;
  localNetwork = cfg.localNetwork;
  nativeRulesPath =
    if hostConfig.packageBackend == "pacman" then "iptables/iptables.rules" else "iptables/rules.v4";
  firewallService =
    if hostConfig.packageBackend == "pacman" then
      "iptables.service"
    else
      "netfilter-persistent.service";
  wgPorts = lib.optional (builtins.elem "wg0" hostConfig.wireguard) topology.wg0.listenPort;
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
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4240 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4244:4245 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 4244:4245 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9962 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 9962 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9965 -j ACCEPT\n-A HOMELAB_TCP -s 10.42.0.0/16 -p tcp --dport 9965 -j ACCEPT"}
    ${lib.optionalString server "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 2379:2381 -j ACCEPT"}
    ${lib.optionalString hostConfig.iscsiServer "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 3260 -j ACCEPT"}
    ${lib.concatMapStringsSep "\n" (
      source: "-A HOMELAB_TCP -s ${source} -p tcp --dport 445 -j ACCEPT"
    ) sambaClients}
    ${lib.optionalString netbios "-A HOMELAB_UDP -s ${localNetwork} -p udp --dport 137:138 -j ACCEPT"}
    ${lib.optionalString gateway "-A HOMELAB_FORWARD -i wg0 -o wg0 -s ${topology.wg0.trustedNetwork} -d ${topology.wg0.edgeNetwork} -j ACCEPT\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s ${topology.wg0.edgeNetwork} -d ${topology.wg0.trustedNetwork} -j ACCEPT\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s 10.222.0.128/26 -d 10.222.0.128/26 -j DROP\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s 10.222.0.192/27 -d 10.222.0.192/27 -j DROP\n-A HOMELAB_FORWARD -i wg0 -o wg0 -s 10.222.0.224/27 -d 10.222.0.224/27 -j DROP"}
  '';
  liveRules = ''
    *filter
    ${body}
    COMMIT
  '';
  bootRules = ''
    *filter
    :INPUT DROP [0:0]
    :FORWARD DROP [0:0]
    :OUTPUT ACCEPT [0:0]
    ${body}
    -A INPUT -j HOMELAB_INPUT
    -A FORWARD -j HOMELAB_FORWARD
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
    sambaClients = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = hostConfig.firewall.sambaClients or [ ];
      description = "Source CIDRs allowed to reach the host Samba service.";
    };
    netbios = lib.mkOption {
      type = lib.types.bool;
      default = hostConfig.firewall.netbios or false;
      description = "Allow LAN NetBIOS datagrams on UDP ports 137-138.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.etc."homelab/firewall.rules" = {
      text = liveRules;
      mode = "0600";
    };
    environment.etc.${nativeRulesPath} = {
      text = bootRules;
      mode = "0600";
      replaceExisting = true;
    };
    environment.etc."systemd/system/${firewallService}.d/50-homelab-order.conf".text = ''
      [Unit]
      Before=homelab-k3s.service
    '';
  };
}
