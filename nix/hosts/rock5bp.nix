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
  homelab.disabledServices = [
    "bluetooth.service"
    "wpa_supplicant.service"
  ];
}
