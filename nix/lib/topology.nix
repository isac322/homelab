{ lib }:
let
  readPublicKey = path: lib.removeSuffix "\n" (builtins.readFile path);
  mkNode =
    nodeId: displayName: system: osFamily: packageBackend: sshTarget: lanAddress: gatewayAddress: defaultInterface: memoryMiB: extra:
    let
      lifecycle = extra.lifecycle or "active";
      resolvedDnsOverTls = extra.resolvedDnsOverTls or "yes";
    in
    assert lib.elem lifecycle [
      "provisioning"
      "active"
      "decommissioning"
    ];
    assert lib.elem resolvedDnsOverTls [
      "yes"
      "no"
      "opportunistic"
    ];
    {
      inherit
        nodeId
        displayName
        system
        osFamily
        packageBackend
        sshTarget
        lanAddress
        gatewayAddress
        defaultInterface
        memoryMiB
        lifecycle
        resolvedDnsOverTls
        ;
      wireguardEndpointHost = extra.wireguardEndpointHost or null;
      k3sRole = extra.k3sRole or null;
      k3sServer = extra.k3sServer or null;
      k3sLabels = extra.k3sLabels or [ ];
      wireguard = extra.wireguard or [ ];
      firewall = extra.firewall or { };
      tuning = extra.tuning or { };
      preserveNasState = extra.preserveNasState or false;
      iscsiServer = extra.iscsiServer or false;
      iscsiClient = extra.iscsiClient or false;
    };

  nodes = {
    n2p1 =
      mkNode "node-n2p1" "n2p1" "aarch64-linux" "debian" "apt" "bhyoo@192.168.219.3" "192.168.219.3"
        "192.168.219.1"
        "eth0"
        4096
        {
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "agent";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          k3sLabels = [
            "homelab.bhyoo.com/gpu=mali"
            "homelab.bhyoo.com/cilium-envoy=true"
          ];
          tuning.emmcIoScheduler = true;
          iscsiClient = true;
        };
    n2p2 =
      mkNode "node-n2p2" "n2p2" "aarch64-linux" "debian" "apt" "bhyoo@192.168.219.4" "192.168.219.4"
        "192.168.219.1"
        "eth0"
        4096
        {
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "agent";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          k3sLabels = [
            "homelab.bhyoo.com/gpu=mali"
            "homelab.bhyoo.com/cilium-envoy=true"
          ];
          tuning.emmcIoScheduler = true;
          iscsiClient = true;
        };
    rpi4 =
      mkNode "node-rpi4" "rpi4" "aarch64-linux" "debian" "apt" "bhyoo@192.168.219.7" "192.168.219.7"
        "192.168.219.1"
        "eth0"
        4096
        {
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "server";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          tuning = {
            zram = true;
            disabledServices = [ "wpa_supplicant.service" ];
          };
          iscsiClient = true;
        };
    rpi5 =
      mkNode "node-rpi5" "rpi5" "aarch64-linux" "debian" "apt" "bhyoo@192.168.219.5" "192.168.219.5"
        "192.168.219.1"
        "eth0"
        8192
        {
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "server";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          k3sLabels = [
            "homelab.bhyoo.com/vpn-gateway=true"
            "homelab.bhyoo.com/cilium-envoy=true"
          ];
          firewall.wireguardGateway = true;
          tuning = {
            zram = true;
            disabledServices = [
              "bluetooth.service"
              "triggerhappy.service"
              "wpa_supplicant.service"
            ];
          };
          iscsiClient = true;
        };
    rock5bp =
      mkNode "node-rock5bp" "rock5bp" "aarch64-linux" "debian" "apt" "bhyoo@192.168.219.6" "192.168.219.6"
        "192.168.219.1"
        "eth0"
        32768
        {
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "server";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          k3sLabels = [
            "homelab.bhyoo.com/gpu=mali"
            "homelab.bhyoo.com/nn-sdk=rknn"
            "homelab.bhyoo.com/media-api=rkmpp"
            "homelab.bhyoo.com/zfs-node=true"
            "homelab.bhyoo.com/cilium-envoy=true"
          ];
          tuning = {
            zram = true;
            emmcIoScheduler = true;
            usbDisableAutosuspend = true;
            disabledServices = [
              "bluetooth.service"
              "wpa_supplicant.service"
            ];
          };
          preserveNasState = true;
          iscsiServer = true;
          iscsiClient = true;
        };
    macmini =
      mkNode "node-macmini" "macmini" "aarch64-linux" "arch" "pacman" "bhyoo@192.168.219.8"
        "192.168.219.8"
        "192.168.219.1"
        "end0"
        16384
        {
          resolvedDnsOverTls = "opportunistic";
          wireguardEndpointHost = "backbone.bhyoo.com";
          wireguard = [ "wg0" ];
          k3sRole = "agent";
          k3sServer = "https://k8s.backbone.homelab.bhyoo.com:6443";
          iscsiClient = true;
        };
    bhyoo-macbook-pro =
      mkNode "node-bhyoo-macbook-pro" "bhyoo-macbook-pro" "aarch64-darwin" "darwin" "darwin" null null
        null
        null
        32768
        {
          wireguard = [ "wg0" ];
        };
  };

  wg0Nodes = {
    n2p1 = {
      address = "10.222.0.1/24";
      publicKey = readPublicKey ./../identities/wireguard/node-n2p1.pub;
    };
    n2p2 = {
      address = "10.222.0.2/24";
      publicKey = readPublicKey ./../identities/wireguard/node-n2p2.pub;
    };
    rpi5 = {
      address = "10.222.0.3/24";
      publicKey = readPublicKey ./../identities/wireguard/node-rpi5.pub;
    };
    rock5bp = {
      address = "10.222.0.4/24";
      publicKey = readPublicKey ./../identities/wireguard/node-rock5bp.pub;
    };
    rpi4 = {
      address = "10.222.0.5/24";
      publicKey = readPublicKey ./../identities/wireguard/node-rpi4.pub;
    };
    macmini = {
      address = "10.222.0.6/24";
      publicKey = readPublicKey ./../identities/wireguard/node-macmini.pub;
    };
    bhyoo-macbook-pro = {
      address = "10.222.0.7/24";
      publicKey = readPublicKey ./../identities/wireguard/node-bhyoo-macbook-pro.pub;
    };
  };
  wg0Edges = {
    bhyoo-phone = {
      address = "10.222.0.129/32";
      publicKey = "xfgEARokf69yKE1QAk+HmmUfI0hUvxoph11JgIHGUyc=";
    };
    bhyoo-desktop = {
      address = "10.222.0.130/32";
      publicKey = "QnZHHW6OsIxW04bum06IhoCVdQQl37QYBEf11xfMfyw=";
    };
    bhyoo-laptop = {
      address = "10.222.0.131/32";
      publicKey = "oW34Dc2LV4fCBGJfofh3tI1Ph6KsuEXkwmRF4ANo0hc=";
    };
    bhyoo-tablet = {
      address = "10.222.0.132/32";
      publicKey = "phtoLYNd/umuzYLxmv91iaITO86T+OGzVK13SQyz3l4=";
    };
    bhyoo-office = {
      address = "10.222.0.133/32";
      publicKey = "/ydTJITQdRUFvsZleC2oRWSW2IBxum17TRgAAUqA6Wo=";
    };
    jay-phone = {
      address = "10.222.0.193/32";
      publicKey = "ordBkoKHEvwMy9iJw5WLDis6Hb4ix16zvBSHy41yjzo=";
    };
    jay-tablet = {
      address = "10.222.0.194/32";
      publicKey = "lF0+5p6i2B9ca32XTWCEVbhcXuXSlwAOab7xTEacvFA=";
    };
    jay-desktop = {
      address = "10.222.0.195/32";
      publicKey = "qhLHqMrXfamYQ9jvaFB+G1zQ5efU4TRtH1XS2/adiRY=";
    };
    yjyoo-phone = {
      address = "10.222.0.225/32";
      publicKey = "NXZLnxi5gPwhH3KhBjYFXbpuzPYPJVAmZIBIah60KE0=";
    };
    gyhan-phone = {
      address = "10.222.0.226/32";
      publicKey = "oQ4lKvr58kmkqKH801+HLdUsPrJahwdtH9F+D3Nci0Y=";
    };
    gyhan-tablet = {
      address = "10.222.0.227/32";
      publicKey = "Z1jQlXSMQSFB4QmOerdEj4pp3dBoPByY0FoFkjOCdzU=";
    };
    jsyoo-phone = {
      address = "10.222.0.228/32";
      publicKey = "/juxTIeIUst4LeK4UGmrUMybr54sUlFXdnkuX9JfSn4=";
    };
    shchoi-phone = {
      address = "10.222.0.229/32";
      publicKey = "m0JRYDYup5msuFB+HkXKzO01+13mrYTSCXU+7jXTt1U=";
    };
    jhjeong-phone = {
      address = "10.222.0.230/32";
      publicKey = "vRSVWjIMwGadIPmdPYEOheYLQQ0t7eIIHq3wCaW+aXc=";
    };
  };

  combinations =
    values: lib.concatMap (a: map (b: { inherit a b; }) (lib.filter (b: b > a) values)) values;
  fullMeshLinks =
    network: names:
    map (pair: {
      linkId = "${network}-${pair.a}-${pair.b}";
      inherit network;
      aName = pair.a;
      bName = pair.b;
      aNodeId = nodes.${pair.a}.nodeId;
      bNodeId = nodes.${pair.b}.nodeId;
      managed = pair.a != "bhyoo-macbook-pro" && pair.b != "bhyoo-macbook-pro";
    }) (combinations names);
  wg0PeerNodes = lib.filterAttrs (
    name: _: (nodes.${name}.lifecycle or "active") != "decommissioning"
  ) wg0Nodes;
  wg0RequiredLinks =
    fullMeshLinks "wg0" (builtins.attrNames wg0PeerNodes)
    ++ map (edge: {
      linkId = "wg0-rpi5-${edge}";
      network = "wg0";
      aName = "rpi5";
      bName = edge;
      aNodeId = nodes.rpi5.nodeId;
      bNodeId = "edge-${edge}";
      managed = false;
    }) (builtins.attrNames wg0Edges);
  activeNodes = lib.filterAttrs (_: node: node.lifecycle == "active") nodes;
  provisioningNodes = lib.filterAttrs (_: node: node.lifecycle == "provisioning") nodes;
  decommissioningNodes = lib.filterAttrs (_: node: node.lifecycle == "decommissioning") nodes;
  deployableNodes = lib.filterAttrs (_: node: node.lifecycle != "decommissioning") nodes;
in
{
  hosts = nodes;
  inherit
    nodes
    activeNodes
    provisioningNodes
    decommissioningNodes
    deployableNodes
    wg0Nodes
    wg0PeerNodes
    wg0Edges
    ;
  trustedNodes = {
    bhyoo-macbook-pro = wg0Nodes.bhyoo-macbook-pro;
  };
  requiredLinks = wg0RequiredLinks;
  wg0 = {
    interface = "wg0";
    network = "10.222.0.0/24";
    trustedNetwork = "10.222.0.0/26";
    edgeNetwork = "10.222.0.128/25";
    listenPort = 51902;
    gateway = "rpi5";
    endpoint = "backbone.bhyoo.com:51902";
    nodes = wg0Nodes;
    peerNodes = wg0PeerNodes;
    edges = wg0Edges;
  };
  secretRecipients = {
    operator = "age1ghdfjncup4cw6rfmvm4z0rnvdg7230svt5u2dxn8ced6uq4ze5wsdy22sd";
    recovery = "age1xgfve9gexpqlrnmgu05kgej9fjwk9qvw0k0h5449hnwdha85vyzq9n5ats";
  };
}
