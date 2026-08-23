{
  lib,
  pkgs,
  name,
  topology,
  ...
}:
let
  node = topology.wg0.nodes.${name};
  secretDirectory = "/Library/Application Support/Homelab/WireGuard";
  configFile = "${secretDirectory}/active/wg0.conf";
  stripPrefix = address: builtins.head (lib.splitString "/" address);
  routeNetworks = [
    topology.wg0.trustedNetwork
  ]
  ++ map (edge: topology.wg0.edges.${edge}.address) (builtins.attrNames topology.wg0.edges);
  peerCount = builtins.length (
    builtins.filter (peer: peer != name) (builtins.attrNames topology.wg0.peerNodes)
  );
in
{
  environment.systemPackages = [
    pkgs.age
    pkgs.sops
    pkgs.wireguard-go
    pkgs.wireguard-tools
  ];

  launchd.daemons.homelab-wireguard = {
    serviceConfig = {
      ProgramArguments = [
        "/bin/sh"
        "-c"
        ''
          set -eu
          test -L ${lib.escapeShellArg "${secretDirectory}/active"}
          active=$(/usr/bin/readlink ${lib.escapeShellArg "${secretDirectory}/active"})
          case "$active" in generations/*) ;; *) exit 1 ;; esac
          test -s ${lib.escapeShellArg configFile}
          ! /usr/bin/grep -q '__[A-Z0-9_-]*__' ${lib.escapeShellArg configFile}
          stripped=$(/usr/bin/mktemp -t homelab-wg0.XXXXXX)
          trap '/bin/rm -f "$stripped"' EXIT
          ${pkgs.wireguard-tools}/bin/wg-quick strip ${lib.escapeShellArg configFile} > "$stripped"
          if ! /sbin/ifconfig wg0 >/dev/null 2>&1; then
            ${pkgs.wireguard-go}/bin/wireguard-go wg0
          fi
          ${pkgs.wireguard-tools}/bin/wg setconf wg0 "$stripped"
          /sbin/ifconfig wg0 inet ${stripPrefix node.address} netmask 255.255.255.255 up
          ${lib.concatMapStringsSep "\n" (
            network:
            "/sbin/route -n add -net ${network} -interface wg0 2>/dev/null || /sbin/route -n change -net ${network} -interface wg0"
          ) routeNetworks}
          test "$(${pkgs.wireguard-tools}/bin/wg show wg0 public-key)" = ${lib.escapeShellArg node.publicKey}
          test "$(${pkgs.wireguard-tools}/bin/wg show wg0 peers | /usr/bin/wc -w | /usr/bin/tr -d ' ')" -eq ${toString peerCount}
        ''
      ];
      RunAtLoad = true;
      KeepAlive = false;
      StandardOutPath = "/var/log/homelab-wireguard.log";
      StandardErrorPath = "/var/log/homelab-wireguard.log";
    };
  };

  system.stateVersion = 6;
}
