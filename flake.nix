{
  description = "Declarative host management for the homelab";

  nixConfig = {
    extra-substituters = [ "https://cache.numtide.com" ];
    extra-trusted-public-keys = [ "niks3.numtide.com-1:DTx8wZduET09hRmMtKdQDxNNthLQETkc/yaX7M4qK0g=" ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    system-manager.url = "github:numtide/system-manager/48d47346e0c6ad05b6c869ea92649c47723d1cfc";
    nix-darwin.url = "github:nix-darwin/nix-darwin/nix-darwin-26.05";
    nix-darwin.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    inputs@{
      self,
      nixpkgs,
      system-manager,
      nix-darwin,
      ...
    }:
    let
      lib = nixpkgs.lib;
      topology = import ./nix/lib/topology.nix { inherit lib; };
      linuxHosts = lib.filterAttrs (_: host: lib.hasSuffix "-linux" host.system) topology.nodes;
      darwinHosts = lib.filterAttrs (_: host: lib.hasSuffix "-darwin" host.system) topology.nodes;
      forAllSystems = lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      mkLinuxHost =
        commit: name: host:
        system-manager.lib.makeSystemConfig {
          modules = [
            ({ ... }: {
              nixpkgs.hostPlatform = host.system;
              homelab.allowDestructiveCommit = commit;
            })
            ./nix/modules/linux/base.nix
            ./nix/modules/linux/packages.nix
            ./nix/modules/linux/firewall.nix
            ./nix/modules/linux/wireguard.nix
            ./nix/modules/linux/k3s-host.nix
            ./nix/hosts/${name}.nix
          ];
          specialArgs = {
            inherit inputs name topology;
            hostConfig = host;
          };
        };
      mkDarwinHost =
        name: host:
        nix-darwin.lib.darwinSystem {
          system = host.system;
          modules = [
            ./nix/modules/darwin/base.nix
            ./nix/hosts/${name}.nix
          ];
          specialArgs = {
            inherit inputs name topology;
            hostConfig = host;
          };
        };
    in
    {
      inherit topology;
      systemConfigs =
        (lib.mapAttrs (mkLinuxHost false) linuxHosts)
        // (lib.mapAttrs' (
          name: host: lib.nameValuePair "${name}-commit" (mkLinuxHost true name host)
        ) linuxHosts);
      darwinConfigurations = lib.mapAttrs mkDarwinHost darwinHosts;
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        import ./nix/packages.nix { inherit pkgs self topology; }
      );
      apps = forAllSystems (
        system:
        let
          packages = self.packages.${system};
        in
        lib.mapAttrs (_: package: {
          type = "app";
          program = "${package}/bin/${package.meta.mainProgram}";
          meta.description = package.meta.description or "Homelab administration command";
        }) packages
      );
      checks = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          hostChecks = lib.mapAttrs' (name: config: lib.nameValuePair "host-${name}" config) (
            lib.filterAttrs (
              name: _:
              let
                baseName = lib.removeSuffix "-commit" name;
              in
              builtins.hasAttr baseName linuxHosts && linuxHosts.${baseName}.system == system
            ) self.systemConfigs
          );
          darwinChecks = lib.mapAttrs' (name: config: lib.nameValuePair "host-${name}" config.system) (
            lib.filterAttrs (_: host: host.system == system) self.darwinConfigurations
          );
          renderedContracts =
            let
              rock = self.systemConfigs.rock5bp.config;
              rpi5 = self.systemConfigs.rpi5.config;
              n2p1 = self.systemConfigs.n2p1.config;
              rockWg = rock.environment.etc."systemd/network/99-wg1.netdev".text;
              rockNetworkdCredentials =
                rock.environment.etc."systemd/system/systemd-networkd.service.d/50-homelab-wireguard-credentials.conf".text;
              rockK3s = rock.environment.etc."rancher/k3s/config.yaml".text;
              firewall = rpi5.environment.etc."iptables/rules.v4".text;
              hosts = n2p1.environment.etc.hosts.text;
              projectServices =
                cfg:
                lib.filter (service: lib.hasPrefix "homelab-" service) (builtins.attrNames cfg.systemd.services);
              projectServiceOwnershipIsMinimal = lib.all (
                hostName:
                let
                  expected = lib.optional (linuxHosts.${hostName}.k3sRole != null) "homelab-k3s";
                in
                projectServices self.systemConfigs.${hostName}.config == expected
                && projectServices self.systemConfigs."${hostName}-commit".config == expected
              ) (builtins.attrNames linuxHosts);
            in
            assert projectServiceOwnershipIsMinimal;
            assert lib.hasInfix "Address=192.168.219.6/24"
              rock.environment.etc."systemd/network/10-homelab-lan.network".text;
            assert lib.hasInfix "Endpoint=192.168.219.3:51903" rockWg;
            assert lib.hasInfix "AllowedIPs=10.223.0.68/32" rockWg;
            assert lib.hasInfix "PrivateKeyFile=/run/credentials/systemd-networkd.service/wg1-private" rockWg;
            assert lib.hasInfix "PresharedKeyFile=/run/credentials/systemd-networkd.service/wg1-psk-n2p1"
              rockWg;
            assert lib.hasInfix
              "LoadCredentialEncrypted=wg1-private:/var/lib/homelab-secrets/active/wg1-private.cred"
              rockNetworkdCredentials;
            assert lib.hasInfix "node-ip: 192.168.219.6" rockK3s;
            assert lib.hasInfix "advertise-address: 192.168.219.6" rockK3s;
            assert lib.hasInfix "--dport 9962" firewall && lib.hasInfix "--dport 9965" firewall;
            assert
              !(lib.hasInfix "${topology.wg0.edgeNetwork} -d ${topology.wg0.edgeNetwork} -j ACCEPT" firewall);
            assert builtins.elem "open-iscsi" rock.homelab.distroPackages.present;
            assert builtins.elem "targetcli-fb" rock.homelab.distroPackages.present;
            assert !(builtins.elem "acl" rock.homelab.distroPackages.present);
            assert
              rock.environment.etc."ssh/authorized_keys.d/democratic-csi".text
              == builtins.readFile ./ssh_pub_keys/democratic-csi.pub;
            assert lib.hasInfix "AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/authorized_keys.d/%u"
              rock.environment.etc."ssh/sshd_config.d/90-homelab-hardening.conf".text;
            assert !(builtins.hasAttr "homelab-host-settings" rock.systemd.services);
            assert !(builtins.hasAttr "homelab-wireguard" rock.systemd.services);
            assert !(builtins.hasAttr "homelab-firewall" rock.systemd.services);
            assert !(builtins.hasAttr "homelab-runtime-tuning" rock.systemd.services);
            assert !(builtins.hasAttr "homelab-k3s-legacy-cleanup" rock.systemd.services);
            assert !(builtins.hasAttr "homelab-legacy-tuning-cleanup" rock.systemd.services);
            assert builtins.hasAttr "systemd/zram-generator.conf" rock.environment.etc;
            assert builtins.hasAttr "tmpfiles.d/60-homelab-runtime-tuning.conf" rock.environment.etc;
            assert builtins.elem "systemd-networkd.service" rock.systemd.services.homelab-k3s.after;
            assert builtins.elem "netfilter-persistent.service" rock.systemd.services.homelab-k3s.after;
            assert builtins.elem "netfilter-persistent.service" rock.systemd.services.homelab-k3s.requires;
            assert !(builtins.elem "netfilter-persistent.service" rock.systemd.services.homelab-k3s.wants);
            assert builtins.elem "dev-zram0.swap" rock.systemd.services.homelab-k3s.after;
            assert
              rock.systemd.services.homelab-k3s.serviceConfig.LoadCredentialEncrypted
              == [ "k3s-token:/var/lib/homelab-secrets/active/k3s-token.cred" ];
            assert !(builtins.hasAttr "homelab-democratic-csi-access" rock.systemd.services);
            assert builtins.elem "iscsid.service" rock.systemd.services.homelab-k3s.after;
            assert builtins.elem "open-iscsi.service" rock.systemd.services.homelab-k3s.after;
            assert
              lib.count (line: lib.hasSuffix " k8s.backbone.homelab.bhyoo.com" line) (lib.splitString "\n" hosts)
              == 3;
            pkgs.runCommand "homelab-rendered-contracts" { } "touch $out";
        in
        hostChecks
        // darwinChecks
        // {
          topology =
            pkgs.runCommand "homelab-topology-check"
              {
                nativeBuildInputs = [ pkgs.python3 ];
              }
              ''
                HOMELAB_SOURCE_ROOT=${self} python3 ${./nix/scripts/check-topology.py}
                touch $out
              '';
          migration-contracts =
            pkgs.runCommand "homelab-migration-contracts"
              {
                nativeBuildInputs = [ pkgs.python3 ];
              }
              ''
                HOMELAB_SOURCE_ROOT=${self} python3 ${./nix/scripts/check-migration.py}
                touch $out
              '';
        }
        // lib.optionalAttrs (system == "aarch64-linux") { rendered-contracts = renderedContracts; }
      );
      formatter = forAllSystems (system: (import nixpkgs { inherit system; }).nixfmt-tree);
    };
}
