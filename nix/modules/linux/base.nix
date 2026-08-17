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
  cfg = config.homelab;
  k8sMember = hostConfig.k3sRole != null;
  tuning = hostConfig.tuning or { };
  zramEnabled = cfg.zram;
  emmcIoScheduler = cfg.emmcIoScheduler;
  usbDisableAutosuspend = cfg.usbDisableAutosuspend;
  disabledServices = cfg.disabledServices;
  minFreeKb = toString (hostConfig.memoryMiB * 16);
  zramSizeMiB = toString (builtins.div hostConfig.memoryMiB 2);
  adminKeys = map builtins.readFile [
    ../../../ssh_pub_keys/desktop.pub
    ../../../ssh_pub_keys/mobile.pub
    ../../../ssh_pub_keys/tablet.pub
    ../../../ssh_pub_keys/office.pub
  ];
  tuningAfter = [
    "homelab-distro-packages.service"
    "homelab-wireguard.service"
    "homelab-firewall.service"
  ];
in
{
  options.homelab = {
    secretDirectory = lib.mkOption {
      type = lib.types.str;
      default = "/run/homelab-secrets/active";
      description = "Atomic active generation populated by stage-secrets before activation.";
    };
    allowDestructiveCommit = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable only for the explicit post-reboot commit generation.";
    };
    zram = lib.mkOption {
      type = lib.types.bool;
      default = tuning.zram or false;
    };
    emmcIoScheduler = lib.mkOption {
      type = lib.types.bool;
      default = tuning.emmcIoScheduler or false;
    };
    usbDisableAutosuspend = lib.mkOption {
      type = lib.types.bool;
      default = tuning.usbDisableAutosuspend or false;
    };
    disabledServices = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = tuning.disabledServices or [ ];
    };
  };

  config = {
    system-manager.allowAnyDistro = hostConfig.osFamily == "arch";
    users.mutableUsers = true;
    services.userborn.enable = true;
    systemd.maskedUnits = disabledServices;

    environment.systemPackages = with pkgs; [
      age
      curl
      htop
      jq
      kubectl
      kubernetes-helm
      sops
      vim
      wireguard-tools
    ];

    environment.etc = {
      hostname = {
        text = "${name}\n";
        replaceExisting = true;
      };
      hosts = {
        text = ''
          127.0.0.1 localhost
          ::1 localhost ip6-localhost ip6-loopback
          ${lib.concatStringsSep "\n" (
            lib.mapAttrsToList (
              hostName: h: lib.optionalString (h.lanAddress != null) "${h.lanAddress} ${hostName}"
            ) topology.nodes
          )}
          192.168.219.7 k8s.backbone.homelab.bhyoo.com
        '';
        replaceExisting = true;
      };
      "systemd/resolved.conf" = {
        text = ''
          [Resolve]
          DNS=1.1.1.1
          FallbackDNS=8.8.8.8
          DNSSEC=allow-downgrade
        '';
        replaceExisting = true;
      };
      "locale.conf".text = "LANG=ko_KR.UTF-8\n";
      "timezone".text = "Asia/Seoul\n";
      "ssh/sshd_config.d/90-homelab-hardening.conf" = {
        text = ''
          PrintLastLog yes
          PrintMotd no
          Banner none
          PermitRootLogin ${if name == "n2p1" || name == "n2p2" then "prohibit-password" else "no"}
          PasswordAuthentication no
          KexAlgorithms sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,diffie-hellman-group-exchange-sha256
          Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
          MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com,umac-128-etm@openssh.com
          HostKey /etc/ssh/ssh_host_rsa_key
          HostKey /etc/ssh/ssh_host_ed25519_key
          LogLevel INFO
        '';
      };
      "ssh/authorized_keys.d/homelab-admins" = {
        text = lib.concatStringsSep "" adminKeys;
        mode = "0644";
      };
      "sysctl.d/99-kubernetes-network.conf" = lib.mkIf k8sMember {
        text = ''
          net.ipv4.neigh.default.gc_thresh1=4096
          net.ipv4.neigh.default.gc_thresh2=8192
          net.ipv4.neigh.default.gc_thresh3=16384
        '';
      };
      "sysctl.d/99-memory.conf" = lib.mkIf zramEnabled {
        text = ''
          vm.swappiness=150
          vm.page-cluster=0
          vm.vfs_cache_pressure=200
          vm.watermark_boost_factor=0
          vm.watermark_scale_factor=125
          vm.dirty_background_ratio=1
          vm.dirty_ratio=10
          vm.min_free_kbytes=${minFreeKb}
        '';
      };
      "sysctl.d/99-wireguard-forwarding.conf" = lib.mkIf (hostConfig.firewall.wireguardGateway or false) {
        text = "net.ipv4.ip_forward=1\n";
      };
      "udev/rules.d/60-io-scheduler.rules" = lib.mkIf emmcIoScheduler {
        text = ''ACTION=="add|change", KERNEL=="mmcblk*", ATTR{queue/scheduler}="none"\n'';
      };
      "modprobe.d/usb-autosuspend.conf" = lib.mkIf usbDisableAutosuspend {
        text = "options usbcore autosuspend=-1\n";
      };
    };

    users.groups = lib.mkMerge [
      { bhyoo.gid = 1000; }
      (lib.mkIf hostConfig.iscsiServer { democratic-csi.gid = 1001; })
    ];
    users.users = lib.mkMerge [
      (lib.mkIf (name != "n2p1" && name != "n2p2") {
        bhyoo = {
          isNormalUser = true;
          uid = 1000;
          group = "bhyoo";
          home = "/home/bhyoo";
          shell = pkgs.bashInteractive;
          extraGroups = [ "sudo" ];
        };
      })
      (lib.mkIf hostConfig.iscsiServer {
        democratic-csi = {
          isNormalUser = true;
          uid = 1001;
          group = "democratic-csi";
          home = "/home/democratic-csi";
          shell = pkgs.bashInteractive;
        };
      })
    ];

    systemd.mounts = lib.optionals k8sMember [
      {
        what = "tmpfs";
        where = "/tmp";
        type = "tmpfs";
        options = "defaults,noatime,nosuid,nodev,mode=1777,size=256M";
        wantedBy = [ "system-manager.target" ];
      }
      {
        what = "tmpfs";
        where = "/var/tmp";
        type = "tmpfs";
        options = "defaults,noatime,nosuid,nodev,mode=1777,size=128M";
        wantedBy = [ "system-manager.target" ];
      }
    ];

    systemd.services = {
      homelab-authorized-keys = {
        description = "Install homelab SSH authorized keys";
        wantedBy = [ "system-manager.target" ];
        before = [ "sshd.service" ];
        path = [
          pkgs.coreutils
          pkgs.getent
        ];
        script = ''
          set -eu
          keys=/etc/ssh/authorized_keys.d/homelab-admins
          for user in root bhyoo; do
            if id "$user" >/dev/null 2>&1; then
              home=$(getent passwd "$user" | cut -d: -f6)
              install -d -m 0700 -o "$user" -g "$(id -gn "$user")" "$home/.ssh"
              install -m 0600 -o "$user" -g "$(id -gn "$user")" "$keys" "$home/.ssh/authorized_keys"
            fi
          done
        '';
        serviceConfig.Type = "oneshot";
      };
      homelab-sysctl = {
        description = "Apply homelab sysctl configuration";
        wantedBy = [ "system-manager.target" ];
        after = tuningAfter;
        before = [ "homelab-k3s.service" ];
        script = "${pkgs.procps}/bin/sysctl --system";
        serviceConfig.Type = "oneshot";
      };
      homelab-thp = lib.mkIf zramEnabled {
        description = "Set transparent hugepage defrag to madvise";
        wantedBy = [ "system-manager.target" ];
        after = tuningAfter;
        before = [ "homelab-k3s.service" ];
        script = "test ! -e /sys/kernel/mm/transparent_hugepage/defrag || echo madvise > /sys/kernel/mm/transparent_hugepage/defrag";
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };
      homelab-ksm = lib.mkIf zramEnabled {
        description = "Enable KSM";
        wantedBy = [ "system-manager.target" ];
        after = tuningAfter;
        before = [ "homelab-k3s.service" ];
        script = ''
          test ! -e /sys/kernel/mm/ksm/run || {
            echo 1 > /sys/kernel/mm/ksm/run
            echo 100 > /sys/kernel/mm/ksm/sleep_millisecs
            echo 200 > /sys/kernel/mm/ksm/pages_to_scan
          }
        '';
        preStop = "test ! -e /sys/kernel/mm/ksm/run || echo 0 > /sys/kernel/mm/ksm/run";
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };
      homelab-zram = lib.mkIf zramEnabled {
        description = "Configure zram swap";
        wantedBy = [ "system-manager.target" ];
        after = tuningAfter ++ [ "local-fs.target" ];
        before = [ "homelab-k3s.service" ];
        path = [
          pkgs.coreutils
          pkgs.kmod
          pkgs.util-linux
        ];
        script = ''
          set -eu
          modprobe zram
          echo zstd > /sys/block/zram0/comp_algorithm
          echo ${zramSizeMiB}M > /sys/block/zram0/disksize
          mkswap /dev/zram0
          swapon -p 100 /dev/zram0
        '';
        preStop = "swapoff /dev/zram0 || true; echo 1 > /sys/block/zram0/reset || true";
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
      };
    };
  };
}
