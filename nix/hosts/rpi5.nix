{ ... }: {
  homelab.zram = true;
  homelab.disabledServices = [
    "bluetooth.service"
    "triggerhappy.service"
    "wpa_supplicant.service"
  ];
}
