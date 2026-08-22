{ ... }: {
  homelab.emmcIoScheduler = true;
  homelab.disabledServices = [ "ModemManager.service" ];
}
