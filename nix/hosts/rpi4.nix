{ ... }: {
  homelab.zram = true;
  homelab.disabledServices = [ "wpa_supplicant.service" ];
  # 3.75 GiB node: live heap reaches ~975 MiB when rpi4 holds control-plane
  # leadership and non-heap runtime overhead (span fragmentation, buck_hash_sys,
  # 12k goroutine stacks) adds ~570 MiB; 1792 MiB keeps next_gc ~250 MiB above
  # the live heap without letting K3s spill into zram.
  homelab.k3s.goMemLimit = "1792MiB";
}
