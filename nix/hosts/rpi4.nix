{ ... }: {
  homelab.zram = true;
  homelab.disabledServices = [ "wpa_supplicant.service" ];
  # 3.75 GiB node: live heap peaks near 860 MiB (14-day max next_gc / 2), so a
  # 2 GiB soft limit let the server grow into zram and thrash.
  homelab.k3s.goMemLimit = "1280MiB";
}
