{ lib, topology, ... }:
{
  homelab.zram = true;
  homelab.distroPackages.present = lib.mkAfter [ "wireguard" "fail2ban" "python3-systemd" ];
  # v1 participates only in vpn0, not the backbone wg0 mesh.
  homelab.firewall.sshSources = [ topology.vpn0.network "125.186.132.27/32" ];

  systemd.services.fail2ban = {
    description = "Fail2ban SSH intrusion prevention";
    wantedBy = [ "multi-user.target" ];
    after = [ "network.target" "netfilter-persistent.service" ];
    serviceConfig = {
      Type = "simple";
      ExecStart = "/usr/bin/fail2ban-server -xf start";
      ExecReload = "/usr/bin/fail2ban-client reload";
      ExecStop = "/usr/bin/fail2ban-client stop";
      Restart = "on-failure";
      RuntimeDirectory = "fail2ban";
    };
  };

  environment.etc = {
    "fail2ban/jail.d/sshd.local" = {
      text = ''
        [sshd]
        enabled = true
        backend = systemd
        port = 22
        maxretry = 3
        findtime = 10m
        bantime = 1h
        ignoreip = 127.0.0.0/8 ::1 125.186.132.27 ${topology.vpn0.network}
      '';
      replaceExisting = true;
    };
    "sysctl.d/99-vultr-ipv6-privacy.conf" = {
      text = ''
        net.ipv6.conf.all.disable_ipv6=1
        net.ipv6.conf.default.disable_ipv6=1
        net.ipv6.conf.lo.disable_ipv6=1
      '';
      replaceExisting = true;
    };
    "systemd/network/10-homelab-wan.network" = {
      text = ''
        [Match]
        Name=enp1s0

        [Network]
        DHCP=ipv4
        LinkLocalAddressing=no
        IPv6AcceptRA=no
        DNS=1.1.1.1#cloudflare-dns.com
        DNS=1.0.0.1#cloudflare-dns.com
        DNSSEC=yes
        DNSOverTLS=yes
        MulticastDNS=no
        LLMNR=no

        [DHCPv4]
        RouteMetric=100
        UseMTU=yes

        [Link]
        RequiredForOnline=yes
      '';
      replaceExisting = true;
    };
  };
}
