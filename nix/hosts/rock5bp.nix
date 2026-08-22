{ ... }: {
  homelab.zram = true;
  homelab.emmcIoScheduler = true;
  homelab.usbDisableAutosuspend = true;
  homelab.disabledServices = [
    "bluetooth.service"
    "wpa_supplicant.service"
  ];
}
