{ ... }: {
  homelab.zram = true;
  homelab.disabledServices = [ "wpa_supplicant.service" ];
}
