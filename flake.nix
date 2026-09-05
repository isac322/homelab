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
      linuxHosts = lib.filterAttrs (_: host: lib.hasSuffix "-linux" host.system) topology.deployableNodes;
      darwinHosts = lib.filterAttrs (
        _: host: lib.hasSuffix "-darwin" host.system
      ) topology.deployableNodes;
      forAllSystems = lib.genAttrs [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
      mkLinuxHost =
        commit: name: host:
        let
          hostModule = ./nix/hosts + "/${name}.nix";
        in
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
          ]
          ++ lib.optional (builtins.pathExists hostModule) hostModule;
          specialArgs = {
            inherit inputs name topology;
            hostConfig = host;
          };
        };
      mkDarwinHost =
        name: host:
        let
          hostModule = ./nix/hosts + "/${name}.nix";
        in
        nix-darwin.lib.darwinSystem {
          system = host.system;
          modules = [
            ./nix/modules/darwin/base.nix
          ]
          ++ lib.optional (builtins.pathExists hostModule) hostModule;
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
              n2p1Commit = self.systemConfigs."n2p1-commit".config;
              n2p1NixPackages = map lib.getName n2p1.environment.systemPackages;
              macmini = self.systemConfigs.macmini.config;
              macminiK3s = macmini.environment.etc."rancher/k3s/config.yaml".text;
              macminiLan = macmini.environment.etc."systemd/network/10-homelab-lan.network".text;
              macminiResolved = macmini.environment.etc."systemd/resolved.conf".text;
              rockWg = rock.environment.etc."systemd/network/99-wg0.netdev".text;
              rockNetworkdCredentials =
                rock.environment.etc."systemd/system/systemd-networkd.service.d/50-homelab-wireguard-credentials.conf".text;
              rockK3s = rock.environment.etc."rancher/k3s/config.yaml".text;
              firewall = rpi5.environment.etc."iptables/rules.v4".text;
              hosts = n2p1.environment.etc.hosts.text;
              rockLan = rock.environment.etc."systemd/network/10-homelab-lan.network".text;
              rockResolved = rock.environment.etc."systemd/resolved.conf".text;
              rockSsh = rock.environment.etc."ssh/sshd_config".text;
              rockCommitSsh = self.systemConfigs."rock5bp-commit".config.environment.etc."ssh/sshd_config".text;
              gracefulShutdownSourcePath = "homelab/kubelet/10-graceful-node-shutdown.conf";
              logindShutdownPath = "systemd/logind.conf.d/zz-kubelet-graceful-shutdown.conf";
              unattendedLogindPath = "systemd/logind.conf.d/unattended-upgrades-logind-maxdelay.conf";
              gracefulShutdownConfigured = lib.all (
                hostName:
                let
                  cfg = self.systemConfigs.${hostName}.config;
                in
                if linuxHosts.${hostName}.k3sRole == null then
                  !(builtins.hasAttr gracefulShutdownSourcePath cfg.environment.etc)
                  && !(lib.any (
                    rule:
                    lib.hasInfix "/var/lib/rancher/k3s/agent/etc/kubelet.conf.d/10-graceful-node-shutdown.conf" rule
                  ) cfg.systemd.tmpfiles.rules)
                  && !(builtins.hasAttr logindShutdownPath cfg.environment.etc)
                else
                  cfg.environment.etc.${gracefulShutdownSourcePath}.text == ''
                    apiVersion: kubelet.config.k8s.io/v1beta1
                    kind: KubeletConfiguration
                    shutdownGracePeriodByPodPriority:
                      - priority: 0
                        shutdownGracePeriodSeconds: 60
                      - priority: 900000000
                        shutdownGracePeriodSeconds: 45
                      - priority: 2000000000
                        shutdownGracePeriodSeconds: 30
                      - priority: 2000001000
                        shutdownGracePeriodSeconds: 45
                  ''
                  && builtins.elem "L+ /var/lib/rancher/k3s/agent/etc/kubelet.conf.d/10-graceful-node-shutdown.conf - - - - /etc/homelab/kubelet/10-graceful-node-shutdown.conf" cfg.systemd.tmpfiles.rules
                  &&
                    cfg.environment.etc.${logindShutdownPath}.text == ''
                      [Login]
                      InhibitDelayMaxSec=195s
                    ''
              ) (builtins.attrNames linuxHosts);
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
              globalPackageOwnershipIsExclusive = lib.all (
                hostName:
                let
                  cfg = self.systemConfigs.${hostName}.config;
                in
                lib.intersectLists (map lib.getName cfg.environment.systemPackages) cfg.homelab.distroPackages.present
                == [ ]
              ) (builtins.attrNames linuxHosts);
              preservationOwnershipIsExplicit = lib.all (
                hostName:
                let
                  host = linuxHosts.${hostName};
                  cfg = self.systemConfigs.${hostName}.config;
                  etc = cfg.environment.etc;
                in
                !host.preserveNasState
                || (
                  !cfg.homelab.firewall.manageRules
                  && !(builtins.hasAttr "democratic-csi" cfg.users.users)
                  && !(builtins.hasAttr "democratic-csi" cfg.users.groups)
                  && !(builtins.elem "targetcli-fb" cfg.homelab.distroPackages.present)
                  && !(builtins.hasAttr "homelab/firewall.rules" etc)
                  && !(builtins.hasAttr "iptables/rules.v4" etc)
                  && !(builtins.hasAttr "iptables/iptables.rules" etc)
                )
              ) (builtins.attrNames linuxHosts);
              frameworkEtcTargets = [
                "environment.d/10-system-manager.conf"
                "profile.d/system-manager-path.sh"
                "systemd/system"
                "tmpfiles.d"
              ];
              etcOwnershipIsExplicit =
                configName:
                let
                  entries = self.systemConfigs.${configName}.config.environment.etc;
                in
                lib.all (target: entries.${target}.replaceExisting || builtins.elem target frameworkEtcTargets) (
                  builtins.attrNames entries
                );
              projectEtcOwnershipIsExplicit = lib.all (
                hostName: etcOwnershipIsExplicit hostName && etcOwnershipIsExplicit "${hostName}-commit"
              ) (builtins.attrNames linuxHosts);
            in
            assert projectServiceOwnershipIsMinimal;
            assert projectEtcOwnershipIsExplicit;
            assert preservationOwnershipIsExplicit;
            assert globalPackageOwnershipIsExclusive;
            assert topology.nodes.rock5bp.preserveNasState;
            assert !(topology.nodes.n2p1.preserveNasState);
            assert topology.nodes.macmini.k3sRole == "agent";
            assert topology.nodes.macmini.iscsiClient;
            assert topology.nodes.macmini.resolvedDnsOverTls == "opportunistic";
            assert lib.hasInfix "DNSOverTLS=opportunistic" macminiResolved;
            assert lib.hasInfix "DNSOverTLS=yes" macminiLan;
            assert lib.hasInfix "server: https://k8s.backbone.homelab.bhyoo.com:6443" macminiK3s;
            assert lib.hasInfix "node-ip: 192.168.219.8" macminiK3s;
            assert lib.hasInfix "node-external-ip: 10.222.0.6" macminiK3s;
            assert lib.hasInfix "exec /usr/local/bin/k3s agent" macmini.systemd.services.homelab-k3s.script;
            assert builtins.elem "open-iscsi" macmini.homelab.distroPackages.present;
            assert builtins.elem "lsscsi" macmini.homelab.distroPackages.present;
            assert builtins.elem "sg3_utils" macmini.homelab.distroPackages.present;
            assert !(builtins.elem "sg3-utils" macmini.homelab.distroPackages.present);
            assert !(builtins.elem "scsitools" macmini.homelab.distroPackages.present);
            assert builtins.elem "curl" n2p1.homelab.distroPackages.present;
            assert builtins.elem "wireguard-tools" n2p1.homelab.distroPackages.present;
            assert builtins.elem "nvme-cli" n2p1.homelab.distroPackages.present;
            assert builtins.elem "vim" n2p1.homelab.distroPackages.present;
            assert !(builtins.elem "htop" n2p1.homelab.distroPackages.present);
            assert !(builtins.elem "vim" n2p1.homelab.distroPackages.absent);
            assert builtins.elem "age" n2p1.homelab.distroPackages.absent;
            assert builtins.elem "htop" n2p1.homelab.distroPackages.absent;
            assert !(builtins.elem "vim" n2p1NixPackages);
            assert builtins.elem "htop" n2p1NixPackages;
            assert builtins.elem "age" n2p1NixPackages;
            assert builtins.elem "jq" n2p1NixPackages;
            assert !(builtins.elem "curl" n2p1NixPackages);
            assert !(builtins.elem "wireguard-tools" n2p1NixPackages);
            assert builtins.elem "iptables.service" macmini.systemd.services.homelab-k3s.requires;
            assert builtins.elem "iscsid.service" macmini.systemd.services.homelab-k3s.after;
            assert builtins.elem "iscsi.service" macmini.systemd.services.homelab-k3s.after;
            assert !(builtins.elem "open-iscsi.service" macmini.systemd.services.homelab-k3s.after);
            assert rock.homelab.firewall.manageRules == false;
            assert rpi5.homelab.firewall.manageRules;
            assert !(builtins.elem "cron" rock.homelab.distroPackages.absent);
            assert builtins.elem "cron" n2p1.homelab.distroPackages.absent;
            assert !(builtins.hasAttr "democratic-csi" rock.users.users);
            assert !(builtins.hasAttr "democratic-csi" rock.users.groups);
            assert !(builtins.hasAttr "homelab/firewall.rules" rock.environment.etc);
            assert !(builtins.hasAttr "iptables/rules.v4" rock.environment.etc);
            assert !(builtins.hasAttr "iptables/iptables.rules" rock.environment.etc);
            assert builtins.hasAttr "systemd/system/netfilter-persistent.service.d/50-homelab-order.conf"
              rock.environment.etc;
            assert builtins.length topology.requiredLinks == 35;
            assert !(builtins.hasAttr "wg1" topology);
            assert gracefulShutdownConfigured;
            assert toString n2p1.environment.etc.${unattendedLogindPath}.source == "/dev/null";
            assert !(builtins.hasAttr unattendedLogindPath rock.environment.etc);
            assert lib.hasInfix "Address=192.168.219.6/24"
              rock.environment.etc."systemd/network/10-homelab-lan.network".text;
            assert lib.hasInfix "Endpoint=192.168.219.3:51902" rockWg;
            assert lib.hasInfix "AllowedIPs=10.222.0.1/32" rockWg;
            assert lib.hasInfix "PrivateKeyFile=/run/credentials/systemd-networkd.service/wg0-private" rockWg;
            assert lib.hasInfix "PresharedKeyFile=/run/credentials/systemd-networkd.service/wg0-psk-n2p1"
              rockWg;
            assert lib.hasInfix
              "LoadCredentialEncrypted=wg0-private:/var/lib/homelab-secrets/active/wg0-private.cred"
              rockNetworkdCredentials;
            assert lib.hasInfix "node-ip: 192.168.219.6" rockK3s;
            assert lib.hasInfix "advertise-address: 192.168.219.6" rockK3s;
            assert lib.hasInfix "--dport 9962" firewall && lib.hasInfix "--dport 9965" firewall;
            assert lib.hasInfix "MulticastDNS=yes" rockLan && lib.hasInfix "LLMNR=no" rockLan;
            assert lib.hasInfix "DNSSEC=yes" rockResolved;
            assert lib.hasInfix "DNSOverTLS=yes" rockResolved;
            assert lib.hasInfix "NTP=162.159.200.1 162.159.200.123"
              n2p1.environment.etc."systemd/timesyncd.conf".text;
            assert lib.hasInfix "FallbackNTP=" n2p1.environment.etc."systemd/timesyncd.conf".text;
            assert n2p1.environment.etc."systemd/timesyncd.conf".replaceExisting;
            assert !(lib.hasInfix "diffie-hellman-group-exchange-sha256" rockSsh);
            assert rock.users.users.root.shell == "/bin/bash";
            assert rock.environment.etc."sudoers.d/homelab-admin".text == "bhyoo ALL=(ALL) NOPASSWD: ALL\n";
            assert n2p1.environment.etc."sudoers.d/homelab-admin".text == "bhyoo ALL=(ALL) NOPASSWD: ALL\n";
            assert !(builtins.hasAttr "sudoers.d/democratic-csi" rock.environment.etc);
            assert rock.environment.etc."sudoers.d/homelab-admin".replaceExisting;
            assert n2p1.environment.etc."sudoers.d/homelab-admin".replaceExisting;
            assert n2p1.users.users.bhyoo.uid == 1000;
            assert lib.hasInfix "PermitRootLogin no" n2p1.environment.etc."ssh/sshd_config".text;
            assert n2p1.environment.etc."ssh/sshd_config".replaceExisting;
            assert !(builtins.hasAttr "ssh/sshd_config.d/90-homelab-hardening.conf" n2p1.environment.etc);
            assert n2p1.environment.etc."locale.conf".replaceExisting;
            assert n2p1.environment.etc."locale.gen".replaceExisting;
            assert n2p1.environment.etc.timezone.replaceExisting;
            assert n2p1.environment.etc."sysctl.d/99-kubernetes-network.conf".replaceExisting;
            assert n2p1.environment.etc."udev/rules.d/60-io-scheduler.rules".replaceExisting;
            assert
              n2p1.environment.etc."udev/rules.d/60-io-scheduler.rules".text
              == "ACTION==\"add|change\", KERNEL==\"mmcblk*\", ATTR{queue/scheduler}=\"none\"\n";
            assert rock.environment.etc."sysctl.d/99-memory.conf".replaceExisting;
            assert rock.environment.etc."modprobe.d/usb-autosuspend.conf".replaceExisting;
            assert lib.hasInfix "exec /usr/local/bin/k3s server" rock.systemd.services.homelab-k3s.script;
            assert
              !(lib.hasInfix "${topology.wg0.edgeNetwork} -d ${topology.wg0.edgeNetwork} -j ACCEPT" firewall);
            assert builtins.elem "open-iscsi" rock.homelab.distroPackages.present;
            assert !(builtins.elem "targetcli-fb" rock.homelab.distroPackages.present);
            assert !(builtins.elem "acl" rock.homelab.distroPackages.present);
            assert !(builtins.hasAttr "ssh/authorized_keys.d/democratic-csi" rock.environment.etc);
            assert lib.hasInfix "AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/authorized_keys.d/%u"
              rock.environment.etc."ssh/sshd_config".text;
            assert lib.hasInfix "AuthorizedKeysFile .ssh/authorized_keys /etc/ssh/authorized_keys.d/%u"
              rockCommitSsh;
            assert lib.hasInfix "AuthorizedKeysFile /etc/ssh/authorized_keys.d/%u"
              n2p1Commit.environment.etc."ssh/sshd_config".text;
            assert
              !(lib.hasInfix "AuthorizedKeysFile .ssh/authorized_keys"
                n2p1Commit.environment.etc."ssh/sshd_config".text
              );
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
          lifecycleFixtures =
            let
              baseNodes = {
                existing = {
                  lifecycle = "active";
                };
              };
              addedNodes = baseNodes // {
                new = {
                  lifecycle = "provisioning";
                };
              };
              changedNodes = baseNodes // {
                existing = {
                  lifecycle = "active";
                  lanAddress = "192.0.2.10";
                };
              };
              deletedNodes = baseNodes // {
                existing = {
                  lifecycle = "decommissioning";
                };
              };
              select = lifecycle: nodes: lib.filterAttrs (_: node: node.lifecycle == lifecycle) nodes;
              deployable = nodes: lib.filterAttrs (_: node: node.lifecycle != "decommissioning") nodes;
            in
            assert lib.attrNames (select "active" addedNodes) == [ "existing" ];
            assert lib.attrNames (select "provisioning" addedNodes) == [ "new" ];
            assert lib.attrNames (select "active" changedNodes) == [ "existing" ];
            assert lib.attrNames (select "decommissioning" deletedNodes) == [ "existing" ];
            assert lib.attrNames (deployable deletedNodes) == [ ];
            pkgs.runCommand "homelab-lifecycle-fixtures" { } "touch $out";
        in
        hostChecks
        // darwinChecks
        // {
          lifecycle-fixtures = lifecycleFixtures;
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
                nativeBuildInputs = [
                  pkgs.ansible
                  pkgs.bash
                  pkgs.jq
                  (pkgs.python3.withPackages (pythonPackages: [ pythonPackages.jinja2 ]))
                ];
              }
              ''
                HOMELAB_REQUIRE_ANSIBLE_RENDER=1 HOMELAB_REQUIRE_JINJA_RENDER=1 HOMELAB_SOURCE_ROOT=${self} python3 ${./nix/scripts/check-migration.py}
                for script in \
                  ${./nix/scripts/adopt-host} \
                  ${./nix/scripts/decommission-host} \
                  ${./nix/scripts/homelab-host} \
                  ${./nix/scripts/issue-kubeconfig} \
                  ${./nix/scripts/k3s-handoff} \
                  ${./nix/scripts/provision-host} \
                  ${./nix/scripts/render-macbook-wireguard} \
                  ${./nix/scripts/rollout-peers} \
                  ${./nix/scripts/sync-wireguard-runtime} \
                  ${./nix/scripts/sync-bootstrap-secret} \
                  ${./nix/scripts/verify-cluster} \
                  ${./nix/scripts/wireguard-secrets}; do
                  bash -n "$script"
                done
                touch $out
              '';
        }
        // lib.optionalAttrs (system == "aarch64-linux") { rendered-contracts = renderedContracts; }
      );
      formatter = forAllSystems (system: (import nixpkgs { inherit system; }).nixfmt-tree);
    };
}
