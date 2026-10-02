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
  homelab.disabledServices = [
    "bluetooth.service"
    "wpa_supplicant.service"
  ];
}
