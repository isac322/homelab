{
  config,
  lib,
  pkgs,
  hostConfig,
  ...
}:
let
  cfg = config.homelab.distroPackages;
  aptPresent = [
    "open-iscsi"
    "lsscsi"
    "sg3-utils"
    "scsitools"
    "iptables"
    "locales"
  ]
  ++ lib.optionals hostConfig.iscsiServer [
    "targetcli-fb"
    "acl"
  ];
  pacmanPresent = [
    "networkmanager"
    "networkd-dispatcher"
    "cronie"
    "snapd"
    "ufw"
  ];
  commonPresent = [
    "vim"
    "htop"
    "wireguard-tools"
    "iptables"
  ];
  k3sPresent = lib.optionals (hostConfig.k3sRole != null) [ "open-iscsi" ];
  defaultAbsent =
    if hostConfig.packageBackend == "pacman" then
      pacmanPresent
    else
      [
        "netplan.io"
        "network-manager"
        "networkd-dispatcher"
        "cron"
        "snapd"
        "ufw"
      ];
  list = lib.concatMapStringsSep " " lib.escapeShellArg;
in
{
  options.homelab.distroPackages = {
    present = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default =
        if hostConfig.packageBackend == "pacman" then
          commonPresent
        else
          commonPresent ++ aptPresent ++ k3sPresent;
    };
    absent = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = defaultAbsent;
    };
    purgeAbsent = lib.mkOption {
      type = lib.types.bool;
      default = false;
    };
  };

  config = {
    environment.systemPackages = with pkgs; [
      vim
      htop
      kubectl
      kubernetes-helm
      wireguard-tools
      sops
      age
    ];
    systemd.services.homelab-distro-packages = {
      description = "Install required distro packages without distro upgrades";
      wantedBy = [ "system-manager.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      script =
        if hostConfig.packageBackend == "pacman" then
          ''
            set -eu
            missing=""
            for package in ${list cfg.present}; do
              pacman -Q "$package" >/dev/null 2>&1 || missing="$missing $package"
            done
            if [ -n "$missing" ]; then pacman --noconfirm --needed -S $missing; fi
            if [ "${if cfg.purgeAbsent then "1" else "0"}" = 1 ] && [ "${
              if config.homelab.allowDestructiveCommit then "1" else "0"
            }" = 1 ]; then
              installed=""
              for package in ${list cfg.absent}; do
                pacman -Q "$package" >/dev/null 2>&1 && installed="$installed $package" || true
              done
              if [ -n "$installed" ]; then pacman --noconfirm -Rns $installed; fi
            fi
          ''
        else
          ''
            set -eu
            export DEBIAN_FRONTEND=noninteractive
            missing=""
            for package in ${list cfg.present}; do
              dpkg-query -W -f='${"$"}{Status}' "$package" 2>/dev/null | grep -qx 'install ok installed' || missing="$missing $package"
            done
            if [ -n "$missing" ]; then
              apt-get update
              apt-get install -y --no-install-recommends $missing
            fi
            if [ "${if cfg.purgeAbsent then "1" else "0"}" = 1 ] && [ "${
              if config.homelab.allowDestructiveCommit then "1" else "0"
            }" = 1 ]; then
              installed=""
              for package in ${list cfg.absent}; do
                dpkg-query -W -f='${"$"}{Status}' "$package" 2>/dev/null | grep -qx 'install ok installed' && installed="$installed $package" || true
              done
              if [ -n "$installed" ]; then apt-get purge -y $installed; fi
            fi
          '';
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
    };
  };
}
