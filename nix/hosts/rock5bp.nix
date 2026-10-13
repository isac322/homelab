{ ... }: {
  homelab.zram = true;
  homelab.emmcIoScheduler = true;
  homelab.usbDisableAutosuspend = true;
  # /tmp holds large tool caches; keep it on disk. Boot still empties it (/etc/tmpfiles.d/tmp.conf).
  homelab.tmpSize = null;
  homelab.firewall.manageRules = false;
  # The OS-owned rules.v4 feeds new inbound TCP SYNs to its TCP chain.
  homelab.firewall.pillar = {
    enable = true;
    parentChain = "TCP";
  };
  # #385: received frames lose their tail far less often when eth0 RX IRQs and
  # NAPI run on the in-order A55 cluster (cpu0-3) instead of the A76 (cpu4-7).
  homelab.irqAffinity = {
    enable = true;
    interface = "eth0";
    cpus = [
      0
      1
      2
      3
    ];
  };
  # Monthly scrubs (local time). hot-data and fast share the EX950 SSD, so they
  # run a week apart; nas (3x HDD raidz1, ~13 h) gets its own day.
  homelab.zfsScrub = {
    enable = true;
    pools = {
      nas = "*-*-01 05:00:00";
      hot-data = "*-*-08 05:00:00";
      fast = "*-*-15 05:00:00";
      temporal = "*-*-15 05:00:00";
    };
  };
  homelab.disabledServices = [
    "bluetooth.service"
    "wpa_supplicant.service"
  ];
}
