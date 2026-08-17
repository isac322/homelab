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
      );
      formatter = forAllSystems (system: (import nixpkgs { inherit system; }).nixfmt-tree);
    };
}
