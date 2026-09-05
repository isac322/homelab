{
  config,
  lib,
  pkgs,
  hostConfig,
  ...
}:
let
  cfg = config.homelab.distroPackages;
  preserveNasState = hostConfig.preserveNasState or false;
  nixPresent = with pkgs; [
    age
    htop
    jq
    kubectl
    kubernetes-helm
    sops
  ];
  aptPresent = [
    "locales"
    "systemd-resolved"
    "iptables-persistent"
    "systemd-zram-generator"
  ];
  archPresent = [ "zram-generator" ];
  iscsiClientPresent = lib.optionals hostConfig.iscsiClient (
    if hostConfig.packageBackend == "pacman" then
      [
        "open-iscsi"
        "lsscsi"
        "sg3_utils"
      ]
    else
      [
        "open-iscsi"
        "lsscsi"
        "sg3-utils"
        "scsitools"
      ]
  );
  iscsiServerPresent = lib.optionals (hostConfig.iscsiServer && !preserveNasState) [ "targetcli-fb" ];
  pacmanAbsent = [
    "networkmanager"
    "networkd-dispatcher"
    "cronie"
    "snapd"
    "ufw"
  ];
  commonPresent = [
    "curl"
    "vim"
    "wireguard-tools"
    "nvme-cli"
    "iptables"
  ];
  commonAbsent = [
    "age"
    "htop"
  ];
  baseAbsent =
    commonAbsent
    ++ (
      if hostConfig.packageBackend == "pacman" then
        pacmanAbsent
      else
        [
          "netplan.io"
          "network-manager"
          "networkd-dispatcher"
          "cron"
          "snapd"
          "ufw"
        ]
    );
  defaultAbsent =
    if preserveNasState then
      lib.remove (if hostConfig.packageBackend == "pacman" then "cronie" else "cron") baseAbsent
    else
      baseAbsent;
  list = lib.concatMapStringsSep " " lib.escapeShellArg;
  validateDistroPackages =
    packages:
    let
      globalPackageOverlap = lib.intersectLists (map lib.getName nixPresent) packages;
    in
    assert lib.assertMsg (globalPackageOverlap == [ ]) ''
      Linux packages must have one global owner; these are declared in both Nix and distro packages: ${lib.concatStringsSep ", " globalPackageOverlap}
    '';
    packages;
in
{
  options.homelab.distroPackages = {
    present = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default =
        commonPresent
        ++ (if hostConfig.packageBackend == "pacman" then archPresent else aptPresent)
        ++ iscsiClientPresent
        ++ iscsiServerPresent;
      apply = validateDistroPackages;
    };
    absent = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = defaultAbsent;
    };
    purgeAbsent = lib.mkOption {
      type = lib.types.bool;
      default = true;
    };
  };

  config = {
    environment.systemPackages = nixPresent;
    system-manager.preActivationAssertions.requiredDistroPackages = {
      enable = true;
      name = "requiredDistroPackages";
      script =
        if hostConfig.packageBackend == "pacman" then
          ''
            missing=""
            for package in ${list cfg.present}; do
              /usr/bin/pacman -Q "$package" >/dev/null 2>&1 || missing="$missing $package"
            done
            test -z "$missing" || {
              echo "required distro packages are missing:$missing; run reconcile-distro-packages first" >&2
              exit 1
            }
          ''
        else
          ''
            missing=""
            for package in ${list cfg.present}; do
              status=$(/usr/bin/dpkg-query -W -f='${"$"}{Status}' "$package" 2>/dev/null || true)
              test "$status" = "install ok installed" || missing="$missing $package"
            done
            test -z "$missing" || {
              echo "required distro packages are missing:$missing; run reconcile-distro-packages first" >&2
              exit 1
            }
          '';
    };
  };
}
