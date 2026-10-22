{ lib, ... }:
{
  homelab.zram = true;
  homelab.distroPackages.present = lib.mkAfter [ "wireguard" ];

  environment.etc = {
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
