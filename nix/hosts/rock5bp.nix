{ ... }: {
  homelab.zram = true;
  homelab.emmcIoScheduler = true;
  homelab.usbDisableAutosuspend = true;
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
