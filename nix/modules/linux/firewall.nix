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
  cfg = config.homelab.firewall;
  k3s = hostConfig.k3sRole != null;
  server = hostConfig.k3sRole == "server";
  gateway = hostConfig.firewall.wireguardGateway or false;
  sambaClients = cfg.sambaClients;
  netbios = cfg.netbios;
  localNetwork = cfg.localNetwork;
  podNetwork = topology.k3s.podNetwork;
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
    ${lib.optionalString server "-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 6443 -j ACCEPT"}
    ${lib.optionalString (
      server && builtins.elem "wg0" hostConfig.wireguard
    ) "-A HOMELAB_TCP -i wg0 -s ${topology.wg0.network} -p tcp --dport 6443 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 10250 -j ACCEPT\n-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 10250 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9100 -j ACCEPT\n-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 9100 -j ACCEPT"}
    ${lib.optionalString k3s "-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4240 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 4244:4245 -j ACCEPT\n-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 4244:4245 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9962 -j ACCEPT\n-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 9962 -j ACCEPT\n-A HOMELAB_TCP -s ${localNetwork} -p tcp --dport 9965 -j ACCEPT\n-A HOMELAB_TCP -s ${podNetwork} -p tcp --dport 9965 -j ACCEPT"}
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
  pillar = cfg.pillar;
  pillarChain = "HOMELAB_PILLAR";
  pillarMarker = "homelab-pillar";
  pillarInitiators = lib.mapAttrsToList (_: node: "${node.lanAddress}/32") (
    lib.filterAttrs (nodeName: node: nodeName != name && node.k3sRole != null) topology.activeNodes
  );
  pillarRule =
    port: source:
    "-A ${pillarChain} -s ${source} -p tcp -m tcp --dport ${toString port} -m comment --comment ${pillarMarker} -j ACCEPT";
  pillarRules = lib.concatStringsSep "\n" (
    map (pillarRule pillar.nvmeTcpPort) pillar.nvmeTcpSources
    ++ map (pillarRule pillar.agentPort) pillar.agentSources
  );
  # Owns only HOMELAB_PILLAR and its single marked jump from the parent chain.
  # Rules are swapped in one iptables-restore --noflush transaction, so a
  # reapply never exposes a window without the allowances and never touches
  # rules owned by the native firewall, Cilium, or K3s.
  pillarFirewall = pkgs.writeShellScript "homelab-pillar-firewall" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.iptables
        pkgs.gnugrep
        pkgs.coreutils
      ]
    }
    chain=${pillarChain}
    parent=${lib.escapeShellArg pillar.parentChain}
    jump_spec="-m comment --comment ${pillarMarker} -j $chain"
    jump_line="-A $parent $jump_spec"
    rule_suffix=" -m comment --comment ${pillarMarker} -j ACCEPT"
    rules_text=${lib.escapeShellArg pillarRules}
    expected="-N $chain"$'\n'"$rules_text"

    fail() {
      echo "homelab-pillar-firewall: $*" >&2
      exit 1
    }
    snapshot() {
      iptables --wait -S || fail "read of the filter table failed"
    }
    count_jumps() {
      grep -Fxc -- "$jump_line" <<<"$1" || true
    }
    assert_owned() {
      local rules=$1 line owned=0
      while IFS= read -r line; do
        case "$line" in
          "-A $chain "*)
            case "$line" in
              *"$rule_suffix") owned=$((owned + 1)) ;;
              *) fail "$chain contains a rule not owned by homelab: $line" ;;
            esac
            ;;
          *" -j $chain" | *" -g $chain")
            test "$line" = "$jump_line" || fail "foreign reference to $chain: $line"
            ;;
        esac
      done <<<"$rules"
      if grep -Fxq -- "-N $chain" <<<"$rules" && test "$owned" -eq 0; then
        fail "$chain already exists without homelab-owned rules; refusing to adopt it"
      fi
    }
    verify() {
      local rules actual
      rules=$(snapshot)
      actual=$(grep -E -- "^-[NA] $chain( |$)" <<<"$rules" || true)
      if test "$actual" != "$expected"; then
        fail "readback of $chain differs from the rendered rules"$'\n'"expected:"$'\n'"$expected"$'\n'"actual:"$'\n'"$actual"
      fi
      test "$(count_jumps "$rules")" -eq 1 || fail "$parent must contain exactly one $chain jump"
    }
    apply() {
      local rules jumps
      rules=$(snapshot)
      grep -Fxq -- "-N $parent" <<<"$rules" \
        || fail "parent chain $parent is missing; the native firewall must load first"
      assert_owned "$rules"
      jumps=$(count_jumps "$rules")
      {
        printf '%s\n' '*filter' ":$chain - [0:0]" "-F $chain" "$rules_text"
        if test "$jumps" -eq 0; then printf '%s\n' "-I $parent 1 $jump_spec"; fi
        printf '%s\n' COMMIT
      } | iptables-restore --wait --noflush || fail "atomic iptables-restore of $chain failed"
      while test "$jumps" -gt 1; do
        iptables --wait -D "$parent" -m comment --comment ${pillarMarker} -j "$chain" \
          || fail "delete of a duplicate $chain jump from $parent failed"
        jumps=$((jumps - 1))
      done
      verify
    }
    remove() {
      local rules jumps
      rules=$(snapshot)
      grep -Fxq -- "-N $chain" <<<"$rules" || return 0
      assert_owned "$rules"
      jumps=$(count_jumps "$rules")
      {
        printf '%s\n' '*filter'
        for _ in $(seq "$jumps"); do printf '%s\n' "-D $parent $jump_spec"; done
        printf '%s\n' "-F $chain" "-X $chain" COMMIT
      } | iptables-restore --wait --noflush || fail "atomic removal of $chain failed"
      rules=$(snapshot)
      if grep -Fxq -- "-N $chain" <<<"$rules" || grep -Eq -- " -[jg] $chain$" <<<"$rules"; then
        fail "$chain is still present after removal"
      fi
    }

    test "$#" -eq 1 || fail "usage: homelab-pillar-firewall apply|verify|remove"
    case "$1" in
      apply) apply ;;
      verify) verify ;;
      remove) remove ;;
      *) fail "unknown command: $1" ;;
    esac
  '';
in
{
  options.homelab.firewall = {
    enable = lib.mkEnableOption "homelab firewall" // {
      default = true;
    };
    manageRules = lib.mkOption {
      type = lib.types.bool;
      default = !(hostConfig.preserveNasState or false);
      description = "Manage homelab firewall rule files and runtime chains.";
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
    pillar = {
      enable = lib.mkEnableOption "scoped pillar-csi NVMe/TCP and agent gRPC allowances in a homelab-owned chain";
      parentChain = lib.mkOption {
        type = lib.types.str;
        example = "TCP";
        description = "Existing native filter chain, reached only by new inbound TCP SYNs, that receives the single jump into HOMELAB_PILLAR.";
      };
      nvmeTcpPort = lib.mkOption {
        type = lib.types.port;
        default = 4420;
        description = "nvmet TCP listener port.";
      };
      agentPort = lib.mkOption {
        type = lib.types.port;
        default = 9500;
        description = "pillar-agent gRPC port.";
      };
      nvmeTcpSources = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = pillarInitiators;
        description = "Canonical source CIDRs of NVMe/TCP initiators: every other active K3s node. Loopback already covers this host.";
      };
      agentSources = lib.mkOption {
        type = lib.types.listOf lib.types.str;
        default = [ podNetwork ];
        description = "Canonical source CIDRs allowed to reach the agent: the controller runs in the pod network; kubelet probes arrive over loopback.";
      };
    };
  };
  config = lib.mkIf cfg.enable {
    environment.etc."homelab/firewall.rules" = lib.mkIf cfg.manageRules {
      text = liveRules;
      mode = "0600";
      replaceExisting = true;
    };
    environment.etc.${nativeRulesPath} = lib.mkIf cfg.manageRules {
      text = bootRules;
      mode = "0600";
      replaceExisting = true;
    };
    environment.etc."systemd/system/${firewallService}.d/50-homelab-order.conf" = {
      text = ''
        [Unit]
        Before=homelab-k3s.service
      '';
      replaceExisting = true;
    };
    assertions = [
      {
        assertion = !(pillar.enable && cfg.manageRules);
        message = "homelab.firewall.pillar is for hosts whose native firewall is not homelab-managed; add the allowances to HOMELAB_TCP instead.";
      }
      {
        assertion = !pillar.enable || (pillar.nvmeTcpSources != [ ] && pillar.agentSources != [ ]);
        message = "homelab.firewall.pillar requires at least one NVMe/TCP and one agent source.";
      }
    ];
    systemd.services.homelab-pillar-firewall = lib.mkIf pillar.enable {
      description = "Apply scoped pillar-csi firewall allowances";
      wantedBy = [ "multi-user.target" ];
      # netfilter-persistent has no reload; any restart replaces the whole filter
      # table, so PartOf reapplies the owned chain after it.
      after = [ firewallService ];
      partOf = [ firewallService ];
      before = [ "homelab-k3s.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pillarFirewall} apply";
        # system-manager reloads changed units that support it, replacing the
        # rules in place instead of stopping (removing) them first.
        ExecReload = "${pillarFirewall} apply";
        ExecStop = "${pillarFirewall} remove";
      };
    };
  };
}
