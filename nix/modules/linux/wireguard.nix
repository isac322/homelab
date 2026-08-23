{
  lib,
  name,
  hostConfig,
  topology,
  ...
}:
let
  stripPrefix = address: builtins.head (lib.splitString "/" address);
  encryptedRoot = "/var/lib/homelab-secrets/active";
  privateCredential = "wg0-private";
  peerCredential = peer: "wg0-psk-${builtins.replaceStrings [ "." ] [ "-" ] peer}";
  credentialPath = credential: "/run/credentials/systemd-networkd.service/${credential}";
  encryptedPath = credential: "${encryptedRoot}/${credential}.cred";

  wg0Node = topology.wg0.nodes.${name} or null;
  wg0PeerNames = lib.optionals (wg0Node != null) (
    lib.filter (peer: peer != name) (builtins.attrNames topology.wg0.peerNodes)
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
      PresharedKeyFile=${credentialPath (peerCredential peer)}
      AllowedIPs=${
        lib.concatStringsSep "," (
          [ "${stripPrefix peerCfg.address}/32" ] ++ lib.optionals (peer == topology.wg0.gateway) edgeAllowed
        )
      }
      ${lib.optionalString (topology.nodes.${peer}.lanAddress != null)
        "Endpoint=${topology.nodes.${peer}.lanAddress}:${toString topology.wg0.listenPort}"
      }
      PersistentKeepalive=25
    '';
  wg0Edge =
    edge:
    let
      edgeCfg = topology.wg0.edges.${edge};
    in
    ''
      [WireGuardPeer]
      PublicKey=${edgeCfg.publicKey}
      PresharedKeyFile=${credentialPath (peerCredential edge)}
      AllowedIPs=${edgeCfg.address}
    '';
  credentials = [ privateCredential ] ++ map peerCredential wg0RequiredPeers;
in
{
  config = lib.mkIf (builtins.elem "wg0" hostConfig.wireguard && wg0Node != null) {
    environment.etc = {
      "systemd/network/99-wg0.netdev" = {
        text = ''
          [NetDev]
          Name=wg0
          Kind=wireguard
          Description=Homelab wg0

          [WireGuard]
          ListenPort=${toString topology.wg0.listenPort}
          PrivateKeyFile=${credentialPath privateCredential}

          ${lib.concatStringsSep "\n" (
            (map wg0Peer wg0PeerNames)
            ++ lib.optionals (name == topology.wg0.gateway) (map wg0Edge wg0EdgeNames)
          )}
        '';
        replaceExisting = true;
        mode = "0644";
      };
      "systemd/network/99-wg0.network" = {
        text = ''
          [Match]
          Name=wg0

          [Network]
          Address=${wg0Node.address}
          ConfigureWithoutCarrier=yes

          [Link]
          RequiredForOnline=no
        '';
        replaceExisting = true;
      };
      "systemd/system/systemd-networkd.service.d/50-homelab-wireguard-credentials.conf" = {
        text = ''
          [Service]
          ${lib.concatMapStringsSep "\n" (
            credential: "LoadCredentialEncrypted=${credential}:${encryptedPath credential}"
          ) credentials}
        '';
        mode = "0644";
      };
    };
  };
}
