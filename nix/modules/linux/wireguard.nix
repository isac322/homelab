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
  cfg = config.homelab.wireguard;
  has = interface: builtins.elem interface hostConfig.wireguard;
  stripPrefix = address: builtins.head (lib.splitString "/" address);
  pskPath = interface: peer: "${cfg.secretDirectory}/${interface}/psk-${peer}";
  privatePath = interface: "${cfg.secretDirectory}/${interface}/privatekey";
  privateVariable = interface: "wg_${interface}_private";
  pskVariable =
    interface: peer: "wg_${interface}_psk_${builtins.replaceStrings [ "-" ] [ "_" ] peer}";
  privateReference = interface: "$" + privateVariable interface;
  pskReference = interface: peer: "$" + pskVariable interface peer;

  wg0Node = topology.wg0.nodes.${name} or null;
  wg0PeerNames = lib.optionals (wg0Node != null) (
    lib.filter (peer: peer != name) (builtins.attrNames topology.wg0.nodes)
  );
  wg0EdgeNames = builtins.attrNames topology.wg0.edges;
  wg0RequiredPeers =
    wg0PeerNames ++ lib.optionals (wg0Node != null && name == topology.wg0.gateway) wg0EdgeNames;
  edgeAllowed = map (edge: topology.wg0.edges.${edge}.address) wg0EdgeNames;
  wg0SyncPeer =
    peer:
    let
      peerCfg = topology.wg0.nodes.${peer};
    in
    ''
      [Peer]
      PublicKey = ${peerCfg.publicKey}
      PresharedKey = ${pskReference "wg0" peer}
      AllowedIPs = ${
        lib.concatStringsSep "," (
          [ "${stripPrefix peerCfg.address}/32" ] ++ lib.optionals (peer == topology.wg0.gateway) edgeAllowed
        )
      }
      ${lib.optionalString (topology.nodes.${peer}.lanAddress != null)
        "Endpoint = ${topology.nodes.${peer}.lanAddress}:${toString topology.wg0.listenPort}"
      }
      PersistentKeepalive = 25
    '';
  wg0SyncEdge =
    edge:
    let
      edgeCfg = topology.wg0.edges.${edge};
    in
    ''
      [Peer]
      PublicKey = ${edgeCfg.publicKey}
      PresharedKey = ${pskReference "wg0" edge}
      AllowedIPs = ${edgeCfg.address}
    '';

  requiredPeers = _: wg0RequiredPeers;
  requiredSecrets =
    interface: [ (privatePath interface) ] ++ map (pskPath interface) wg0RequiredPeers;
  syncConfig = interface: port: peers: ''
    [Interface]
    PrivateKey = ${privateReference interface}
    ListenPort = ${toString port}

    ${lib.concatStringsSep "\n" peers}
  '';
  netdev = interface: port: ''
    [NetDev]
    Name=${interface}
    Kind=wireguard
    Description=Homelab ${interface}

    [WireGuard]
    ListenPort=${toString port}
    PrivateKeyFile=${privatePath interface}
  '';
  network = interface: address: ''
    [Match]
    Name=${interface}

    [Network]
    Address=${address}
    ConfigureWithoutCarrier=yes
  '';
  expectedPeerKeys =
    _:
    map (peer: topology.wg0.nodes.${peer}.publicKey) wg0PeerNames
    ++ lib.optionals (wg0Node != null && name == topology.wg0.gateway) (
      map (edge: topology.wg0.edges.${edge}.publicKey) wg0EdgeNames
    );
in
{
  options.homelab.wireguard.secretDirectory = lib.mkOption {
    type = lib.types.str;
    default = config.homelab.secretDirectory;
  };

  config = lib.mkMerge [
    (lib.mkIf (has "wg0" && wg0Node != null) {
      environment.etc."systemd/network/99-wg0.netdev" = {
        text = netdev "wg0" topology.wg0.listenPort;
        replaceExisting = true;
        mode = "0640";
      };
      environment.etc."systemd/network/99-wg0.network" = {
        text = network "wg0" wg0Node.address;
        replaceExisting = true;
      };
    })
    (lib.mkIf (hostConfig.wireguard != [ ]) {
      systemd.services.homelab-wireguard = {
        description = "Validate active secrets and reconfigure homelab WireGuard interfaces";
        wantedBy = [ "system-manager.target" ];
        after = [
          "homelab-distro-packages.service"
          "systemd-networkd.service"
        ];
        before = [
          "homelab-firewall.service"
          "homelab-k3s.service"
        ];
        path = [
          pkgs.coreutils
          pkgs.iproute2
          pkgs.systemd
          pkgs.util-linux
          pkgs.wireguard-tools
        ];
        script = ''
          set -eu
          test -L ${lib.escapeShellArg cfg.secretDirectory}
          active=$(readlink -f ${lib.escapeShellArg cfg.secretDirectory})
          case "$active" in /run/homelab-secrets/generations/*) ;; *) echo "invalid active secret generation" >&2; exit 1 ;; esac
          ${lib.concatMapStringsSep "\n" (interface: ''
            ${lib.concatMapStringsSep "\n" (secret: "test -s ${lib.escapeShellArg secret}") (
              requiredSecrets interface
            )}
            previous_config=/run/homelab-wireguard-${interface}.previous
            desired_config=$(mktemp)
            new_keys=$(mktemp)
            expected_keys=$(mktemp)
            had_interface=0
            if ip link show ${lib.escapeShellArg interface} >/dev/null 2>&1; then
              had_interface=1
              wg showconf ${lib.escapeShellArg interface} > "$previous_config"
              chmod 0600 "$previous_config"
            fi
            rollback_interface() {
              status=$?
              if [ "$status" -ne 0 ]; then
                if [ "$had_interface" -eq 1 ]; then
                  wg setconf ${lib.escapeShellArg interface} "$previous_config" || true
                else
                  ip link delete ${lib.escapeShellArg interface} >/dev/null 2>&1 || true
                fi
              fi
              rm -f "$desired_config" "$new_keys" "$expected_keys" "$previous_config"
              exit "$status"
            }
            trap rollback_interface EXIT
            ${privateVariable interface}=$(cat ${lib.escapeShellArg (privatePath interface)})
            test -n "${privateReference interface}"
            ${lib.concatMapStringsSep "\n" (
              peer:
              let
                variable = pskVariable interface peer;
              in
              ''
                ${variable}=$(cat ${lib.escapeShellArg (pskPath interface peer)})
                test -n "${pskReference interface peer}"
              ''
            ) (requiredPeers interface)}
            cat > "$desired_config" <<EOF
            ${syncConfig interface topology.wg0.listenPort (
              (map wg0SyncPeer wg0PeerNames)
              ++ lib.optionals (name == topology.wg0.gateway) (map wg0SyncEdge wg0EdgeNames)
            )}
            EOF
            unset ${privateVariable interface}
            unset ${lib.concatStringsSep " " (map (pskVariable interface) (requiredPeers interface))}
            if grep -Eq '^(PrivateKey|PresharedKey) = $' "$desired_config"; then
              echo "empty WireGuard secret in ${interface} config" >&2
              exit 1
            fi
            chmod 0600 "$desired_config"
            : > "$expected_keys"
            ${lib.concatMapStringsSep "\n" (
              key: "printf '%s\\n' ${lib.escapeShellArg key} >> \"$expected_keys\""
            ) (expectedPeerKeys interface)}
            sort -o "$expected_keys" "$expected_keys"
            networkctl reload
            for attempt in $(seq 1 20); do
              ip link show ${lib.escapeShellArg interface} >/dev/null 2>&1 && break
              sleep 1
            done
            ip link show ${lib.escapeShellArg interface} >/dev/null
            wg syncconf ${lib.escapeShellArg interface} "$desired_config"
            test "$(wg show ${lib.escapeShellArg interface} listen-port)" = "${toString topology.wg0.listenPort}"
            wg show ${lib.escapeShellArg interface} peers | tr ' ' '\n' | sed '/^$/d' | sort > "$new_keys"
            if ! cmp -s "$expected_keys" "$new_keys"; then
              echo "unexpected peer set after syncing ${interface}; previous runtime config will be restored" >&2
              exit 1
            fi
            rm -f "$desired_config" "$new_keys" "$expected_keys" "$previous_config"
            trap - EXIT
          '') hostConfig.wireguard}
        '';
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };
    })
  ];
}
