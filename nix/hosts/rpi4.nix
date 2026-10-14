{ ... }: {
  homelab.zram = true;
  homelab.disabledServices = [ "wpa_supplicant.service" ];
  # 3.75 GiB node: live heap reaches ~920 MiB and non-heap runtime overhead
  # (span fragmentation, buck_hash_sys, goroutine stacks) adds ~530 MiB; 1536 MiB
  # keeps next_gc above the live heap without letting K3s spill into zram.
  homelab.k3s.goMemLimit = "1536MiB";
}
