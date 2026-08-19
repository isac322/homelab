{
  config,
  lib,
  name,
  hostConfig,
  topology,
  ...
}:
let
  has = interface: builtins.elem interface hostConfig.wireguard;
  stripPrefix = address: builtins.head (lib.splitString "/" address);
  encryptedRoot = "/var/lib/homelab-secrets/active";
  credentialName = interface: kind: "${interface}-${kind}";
  privateCredential = interface: credentialName interface "private";
  peerCredential =
    interface: peer: credentialName interface "psk-${builtins.replaceStrings [ "." ] [ "-" ] peer}";
  credentialPath = credential: "/run/credentials/systemd-networkd.service/${credential}";
  encryptedPath = credential: "${encryptedRoot}/${credential}.cred";

  wg0Node = topology.wg0.nodes.${name} or null;
  wg0PeerNames = lib.optionals (wg0Node != null) (
    lib.filter (peer: peer != name) (builtins.attrNames topology.wg0.nodes)
  );
  wg0EdgeNames = builtins.attrNames topology.wg0.edges;
  wg0RequiredPeers =
    wg0PeerNames ++ lib.optionals (wg0Node != null && name == topology.wg0.gateway) wg0EdgeNames;
  edgeAllowed = map (edge: topology.wg0.edges.${edge}.address) wg0EdgeNames;
  wg0Peer =
    peer:
    let
      peerCfg = topology.wg0.nodes.${peer};
    in
    ''
      [WireGuardPeer]
      PublicKey=${peerCfg.publicKey}
      PresharedKeyFile=${credentialPath (peerCredential "wg0" peer)}
      AllowedIPs=${
        lib.concatStringsSep "," (
          [ "${stripPrefix peerCfg.address}/32" ] ++ lib.optionals (peer == topology.wg0.gateway) edgeAllowed
        )
      }
      ${lib.optionalString (topology.nodes.${peer}.lanAddress != null)
        "Endpoint=${topology.nodes.${peer}.lanAddress}:${toString topology.wg0.listenPort}"
      }
      PersistentKeepaliveSec=25
    '';
  wg0Edge =
    edge:
    let
      edgeCfg = topology.wg0.edges.${edge};
    in
    ''
      [WireGuardPeer]
      PublicKey=${edgeCfg.publicKey}
      PresharedKeyFile=${credentialPath (peerCredential "wg0" edge)}
      AllowedIPs=${edgeCfg.address}
    '';

  wg1Node = topology.wg1.nodes.${name} or null;
  wg1PeerNames = lib.optionals (wg1Node != null) (
    lib.filter (peer: peer != name) (builtins.attrNames topology.wg1.nodes)
  );
  wg1RequiredPeers = wg1PeerNames;
  wg1Peer =
    peer:
    let
      peerCfg = topology.wg1.nodes.${peer};
    in
    ''
      [WireGuardPeer]
      PublicKey=${peerCfg.publicKey}
      PresharedKeyFile=${credentialPath (peerCredential "wg1" peer)}
      AllowedIPs=${stripPrefix peerCfg.address}/32
      Endpoint=${topology.nodes.${peer}.lanAddress}:${toString topology.wg1.listenPort}
      PersistentKeepaliveSec=25
    '';

  requiredPeers = interface: if interface == "wg0" then wg0RequiredPeers else wg1RequiredPeers;
  credentials = lib.concatMap (
    interface:
    [ (privateCredential interface) ] ++ map (peerCredential interface) (requiredPeers interface)
  ) hostConfig.wireguard;
  netdev = interface: port: peers: ''
    [NetDev]
    Name=${interface}
    Kind=wireguard
    Description=Homelab ${interface}

    [WireGuard]
    ListenPort=${toString port}
    PrivateKeyFile=${credentialPath (privateCredential interface)}

    ${lib.concatStringsSep "\n" peers}
  '';
  network = interface: address: ''
    [Match]
    Name=${interface}

    [Network]
    Address=${address}
    ConfigureWithoutCarrier=yes

    [Link]
    RequiredForOnline=no
  '';
in
{
  config = lib.mkMerge [
    (lib.mkIf (has "wg0" && wg0Node != null) {
      environment.etc."systemd/network/99-wg0.netdev" = {
        text = netdev "wg0" topology.wg0.listenPort (
          (map wg0Peer wg0PeerNames)
          ++ lib.optionals (name == topology.wg0.gateway) (map wg0Edge wg0EdgeNames)
        );
        replaceExisting = true;
        mode = "0644";
      };
      environment.etc."systemd/network/99-wg0.network" = {
        text = network "wg0" wg0Node.address;
        replaceExisting = true;
      };
    })
    (lib.mkIf (has "wg1" && wg1Node != null) {
      environment.etc."systemd/network/99-wg1.netdev" = {
        text = netdev "wg1" topology.wg1.listenPort (map wg1Peer wg1PeerNames);
        replaceExisting = true;
        mode = "0644";
      };
      environment.etc."systemd/network/99-wg1.network" = {
        text = network "wg1" wg1Node.address;
        replaceExisting = true;
      };
    })
    (lib.mkIf (hostConfig.wireguard != [ ]) {
      environment.etc."systemd/system/systemd-networkd.service.d/50-homelab-wireguard-credentials.conf" =
        {
          text = ''
            [Service]
            ${lib.concatMapStringsSep "\n" (
              credential: "LoadCredentialEncrypted=${credential}:${encryptedPath credential}"
            ) credentials}
          '';
          mode = "0644";
        };
    })
  ];
}
