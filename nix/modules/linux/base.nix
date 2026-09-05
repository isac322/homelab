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
  preserveNasState = hostConfig.preserveNasState or false;
  sshUser = builtins.head (lib.splitString "@" hostConfig.sshTarget);
  tuning = hostConfig.tuning or { };
  zramEnabled = cfg.zram;
  emmcIoScheduler = cfg.emmcIoScheduler;
  usbDisableAutosuspend = cfg.usbDisableAutosuspend;
  disabledServices = cfg.disabledServices;
  minFreeKb = toString (hostConfig.memoryMiB * 16);
  staticLan =
    hostConfig.lanAddress != null
    && hostConfig.gatewayAddress != null
    && hostConfig.defaultInterface != null;
  backboneApiHosts = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      _: host:
      lib.optionalString (
        host.k3sRole == "server" && host.lanAddress != null
      ) "${host.lanAddress} k8s.backbone.homelab.bhyoo.com"
    ) topology.nodes
  );
  adminKeys = map builtins.readFile [
    ../../../ssh_pub_keys/desktop.pub
    ../../../ssh_pub_keys/laptop.pub
    ../../../ssh_pub_keys/mobile.pub
    ../../../ssh_pub_keys/tablet.pub
    ../../../ssh_pub_keys/office.pub
  ];
  democraticCsiKey = builtins.readFile ../../../ssh_pub_keys/democratic-csi.pub;
  authorizedKeysFile =
    if preserveNasState then
      ".ssh/authorized_keys /etc/ssh/authorized_keys.d/%u"
    else if cfg.allowDestructiveCommit then
      "/etc/ssh/authorized_keys.d/%u"
    else
      ".ssh/authorized_keys /etc/ssh/authorized_keys.d/%u";
in
{
  options.homelab = {
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
          ${backboneApiHosts}
        '';
        replaceExisting = true;
      };
      "systemd/resolved.conf" = {
        text = ''
          [Resolve]
          DNS=1.1.1.1#cloudflare-dns.com
          FallbackDNS=1.0.0.1#cloudflare-dns.com
          DNSSEC=yes
          DNSOverTLS=${hostConfig.resolvedDnsOverTls}
          MulticastDNS=yes
          LLMNR=no
        '';
        replaceExisting = true;
      };
      "systemd/timesyncd.conf" = {
        text = ''
          [Time]
          NTP=162.159.200.1 162.159.200.123
          FallbackNTP=
        '';
        replaceExisting = true;
      };
      "locale.conf" = {
        text = "LANG=ko_KR.UTF-8\n";
        replaceExisting = true;
      };
      "locale.gen" = {
        text = "ko_KR.UTF-8 UTF-8\n";
        replaceExisting = true;
      };
      timezone = {
        text = "Asia/Seoul\n";
        replaceExisting = true;
      };
      "localtime" = {
        source = "${pkgs.tzdata}/share/zoneinfo/Asia/Seoul";
        replaceExisting = true;
      };
      "tmpfiles.d/20-homelab-resolv.conf" = {
        text = "L+ /etc/resolv.conf - - - - /run/systemd/resolve/stub-resolv.conf\n";
        replaceExisting = true;
      };
      "systemd/zram-generator.conf" = lib.mkIf zramEnabled {
        text = ''
          [zram0]
          zram-size = ram / 2
          compression-algorithm = zstd
          swap-priority = 100
        '';
        replaceExisting = true;
      };
      "tmpfiles.d/60-homelab-runtime-tuning.conf" = lib.mkIf zramEnabled {
        text = ''
          w- /sys/kernel/mm/transparent_hugepage/enabled - - - - always
          w- /sys/kernel/mm/transparent_hugepage/defrag - - - - madvise
          w- /sys/kernel/mm/ksm/run - - - - 1
          w- /sys/kernel/mm/ksm/sleep_millisecs - - - - 100
          w- /sys/kernel/mm/ksm/pages_to_scan - - - - 200
        '';
        replaceExisting = true;
      };
      "systemd/network/10-homelab-lan.network" = lib.mkIf staticLan {
        text = ''
          [Match]
          Name=${hostConfig.defaultInterface}

          [Network]
          Address=${hostConfig.lanAddress}/24
          Gateway=${hostConfig.gatewayAddress}
          DNS=1.1.1.1#cloudflare-dns.com
          DNS=1.0.0.1#cloudflare-dns.com
          DNSSEC=yes
          DNSOverTLS=yes
          MulticastDNS=yes
          LLMNR=no
          IPv6AcceptRA=yes

          [Link]
          RequiredForOnline=yes
        '';
        replaceExisting = true;
      };
      "sudoers.d/democratic-csi" = lib.mkIf (hostConfig.iscsiServer && !preserveNasState) {
        text = "democratic-csi ALL=(ALL) NOPASSWD: ALL\n";
        mode = "0440";
        replaceExisting = true;
      };
      "sudoers.d/homelab-admin" = lib.mkIf (sshUser != "root") {
        text = "${sshUser} ALL=(ALL) NOPASSWD: ALL\n";
        mode = "0440";
        replaceExisting = true;
      };
      "ssh/sshd_config" = {
        text = ''
          Port 22
          AddressFamily any
          ListenAddress 0.0.0.0
          HostKey /etc/ssh/ssh_host_rsa_key
          HostKey /etc/ssh/ssh_host_ed25519_key
          HostKeyAlgorithms sk-ssh-ed25519-cert-v01@openssh.com,ssh-ed25519-cert-v01@openssh.com,rsa-sha2-512-cert-v01@openssh.com,rsa-sha2-256-cert-v01@openssh.com,sk-ssh-ed25519@openssh.com,ssh-ed25519,rsa-sha2-512,rsa-sha2-256
          StrictModes yes
          SyslogFacility AUTH
          LogLevel INFO
          LoginGraceTime 30s
          MaxAuthTries 2
          MaxSessions 10
          MaxStartups 10:30:60
          PubkeyAuthentication yes
          AuthenticationMethods publickey
          PasswordAuthentication no
          PermitEmptyPasswords no
          KbdInteractiveAuthentication no
          ChallengeResponseAuthentication no
          PermitRootLogin no
          UsePAM yes
          IgnoreRhosts yes
          IgnoreUserKnownHosts yes
          HostbasedAuthentication no
          KerberosAuthentication no
          GSSAPIAuthentication no
          TCPKeepAlive no
          ClientAliveInterval 300
          ClientAliveCountMax 3
          PermitTunnel no
          AllowTcpForwarding no
          AllowAgentForwarding no
          GatewayPorts no
          X11Forwarding no
          PermitUserEnvironment no
          Compression no
          UseDNS no
          PrintMotd no
          PrintLastLog yes
          Banner none
          AuthorizedKeysFile ${authorizedKeysFile}
          KexAlgorithms sntrup761x25519-sha512@openssh.com,curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512
          Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
          MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com,umac-128-etm@openssh.com
          Subsystem sftp internal-sftp -l INFO -f LOCAL6 -u 0027
        '';
        replaceExisting = true;
      };
      "ssh/authorized_keys.d/root" = {
        text = lib.concatStringsSep "\n" adminKeys + "\n";
        mode = "0644";
        replaceExisting = true;
      };
      "ssh/authorized_keys.d/bhyoo" = {
        text = lib.concatStringsSep "\n" adminKeys + "\n";
        mode = "0644";
        replaceExisting = true;
      };
      "ssh/authorized_keys.d/democratic-csi" = lib.mkIf (hostConfig.iscsiServer && !preserveNasState) {
        text = democraticCsiKey;
        mode = "0644";
        replaceExisting = true;
      };
      "sysctl.d/99-kubernetes-network.conf" = lib.mkIf k8sMember {
        text = ''
          net.ipv4.neigh.default.gc_thresh1=4096
          net.ipv4.neigh.default.gc_thresh2=8192
          net.ipv4.neigh.default.gc_thresh3=16384
        '';
        replaceExisting = true;
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
        replaceExisting = true;
      };
      "sysctl.d/99-wireguard-forwarding.conf" = lib.mkIf k8sMember {
        text = "net.ipv4.ip_forward=1\n";
        replaceExisting = true;
      };
      "udev/rules.d/60-io-scheduler.rules" = lib.mkIf emmcIoScheduler {
        text = ''
          ACTION=="add|change", KERNEL=="mmcblk*", ATTR{queue/scheduler}="none"
        '';
        replaceExisting = true;
      };
      "modprobe.d/usb-autosuspend.conf" = lib.mkIf usbDisableAutosuspend {
        replaceExisting = true;
        text = "options usbcore autosuspend=-1\n";
      };
    };

    users.groups = lib.mkMerge [
      { bhyoo.gid = 1000; }
      (lib.mkIf (hostConfig.iscsiServer && !preserveNasState) { democratic-csi.gid = 1001; })
    ];
    users.users = lib.mkMerge [
      {
        root.shell = "/bin/bash";
        bhyoo = {
          isNormalUser = true;
          uid = 1000;
          group = "bhyoo";
          home = "/home/bhyoo";
          shell = pkgs.bashInteractive;
          extraGroups = [ "sudo" ];
        };
      }
      (lib.mkIf (hostConfig.iscsiServer && !preserveNasState) {
        democratic-csi = {
          isNormalUser = true;
          uid = 1001;
          group = "democratic-csi";
          home = "/home/democratic-csi";
          shell = pkgs.bashInteractive;
        };
      })
    ];

    systemd.tmpfiles.rules = [
      "d /etc 0755 root root -"
      "d /etc/ssh 0755 root root -"
      "d /etc/ssh/authorized_keys.d 0755 root root -"
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
  };
}
