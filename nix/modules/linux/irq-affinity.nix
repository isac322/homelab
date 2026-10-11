{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.irqAffinity;
  cpus = lib.unique (lib.sort lib.lessThan cfg.cpus);
  cpuList = lib.concatMapStringsSep "," toString cpus;
  device = "sys-subsystem-net-devices-${cfg.interface}.device";
  # Pins every IRQ named <interface> or <interface>-* in /proc/interrupts. The
  # driver requests its vectors when the link is opened, not when the device
  # appears, so apply waits for them; a user-set affinity survives later
  # down/up cycles of the same device, and a re-probe re-runs the unit through
  # BindsTo/WantedBy on the device unit.
  irqAffinity = pkgs.writeShellScript "homelab-irq-affinity" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.coreutils
        pkgs.gawk
        pkgs.procps
      ]
    }
    iface=${lib.escapeShellArg cfg.interface}
    want_list=${lib.escapeShellArg cpuList}
    want=${lib.escapeShellArg (lib.concatMapStringsSep " " toString cpus)}
    wait_seconds=${toString cfg.waitSeconds}

    log() {
      echo "homelab-irq-affinity: $*"
    }
    fail() {
      echo "homelab-irq-affinity: $*" >&2
      exit 1
    }
    scan() {
      irqs=$(awk -v ifc="$iface" '
        $1 ~ /^[0-9]+:$/ {
          name = $NF
          if (name == ifc || index(name, ifc "-") == 1) {
            sub(":", "", $1)
            printf "%s ", $1
          }
        }
      ' /proc/interrupts) || fail "read of /proc/interrupts failed"
      irqs=''${irqs% }
    }
    # Expands a kernel cpulist such as 0-3,6 into "0 1 2 3 6".
    expand() {
      local part out="" c
      local -a parts
      IFS=, read -ra parts <<<"$1"
      for part in "''${parts[@]}"; do
        case "$part" in
          "") ;;
          *-*)
            for ((c = ''${part%-*}; c <= ''${part#*-}; c++)); do out+="$c "; done
            ;;
          *) out+="$part " ;;
        esac
      done
      printf '%s' "''${out% }"
    }
    pin() {
      local irq
      for irq in $irqs; do
        echo "$want_list" >"/proc/irq/$irq/smp_affinity_list" \
          || fail "write of CPUs $want_list to /proc/irq/$irq/smp_affinity_list failed"
      done
    }
    verify() {
      local irq aff eff cpu bad=0 count=0 summary=""
      scan
      test -n "$irqs" || fail "no $iface IRQ in /proc/interrupts"
      for irq in $irqs; do
        count=$((count + 1))
        aff=$(<"/proc/irq/$irq/smp_affinity_list") || fail "read of IRQ $irq affinity failed"
        eff=$(<"/proc/irq/$irq/effective_affinity_list") || fail "read of IRQ $irq effective affinity failed"
        if test "$(expand "$aff")" != "$want"; then
          echo "homelab-irq-affinity: IRQ $irq smp_affinity_list is $aff, expected $want_list" >&2
          bad=$((bad + 1))
          continue
        fi
        if test -z "$(expand "$eff")"; then
          echo "homelab-irq-affinity: IRQ $irq has no effective CPU" >&2
          bad=$((bad + 1))
          continue
        fi
        for cpu in $(expand "$eff"); do
          case " $want " in
            *" $cpu "*) ;;
            *)
              echo "homelab-irq-affinity: IRQ $irq is effective on CPU $eff, outside $want_list" >&2
              bad=$((bad + 1))
              continue 2
              ;;
          esac
        done
        summary+=" $irq:$eff"
      done
      if pgrep -x irqbalance >/dev/null; then
        fail "irqbalance is running and would override the $iface IRQ affinity"
      fi
      test "$bad" -eq 0 || fail "$bad of $count $iface IRQs are not pinned to CPUs $want_list"
      log "$count $iface IRQs pinned to CPUs $want_list (irq:effective$summary)"
    }
    apply() {
      local deadline=$((SECONDS + wait_seconds)) previous attempt
      scan
      while test -z "$irqs"; do
        test "$SECONDS" -lt "$deadline" \
          || fail "no $iface IRQ appeared in /proc/interrupts within ''${wait_seconds}s"
        sleep 1
        scan
      done
      # The driver requests its vectors one by one; pin until the set is stable.
      for attempt in 1 2 3 4 5; do
        previous=$irqs
        pin
        sleep 1
        scan
        test "$irqs" != "$previous" || break
        test "$attempt" -lt 5 || fail "$iface IRQ set did not settle"
      done
      verify
    }
    reset() {
      local irq default
      default=$(</proc/irq/default_smp_affinity)
      scan
      for irq in $irqs; do
        echo "$default" >"/proc/irq/$irq/smp_affinity" \
          || fail "reset of /proc/irq/$irq/smp_affinity to $default failed"
      done
      log "reset ''${irqs:-no} $iface IRQs to the default mask $default"
    }

    test "$#" -eq 1 || fail "usage: homelab-irq-affinity apply|verify|reset"
    case "$1" in
      apply) apply ;;
      verify) verify ;;
      reset) reset ;;
      *) fail "unknown command: $1" ;;
    esac
  '';
in
{
  options.homelab.irqAffinity = {
    enable = lib.mkEnableOption "pinning every IRQ of one network interface to a CPU set";
    interface = lib.mkOption {
      type = lib.types.strMatching "[A-Za-z0-9_]+";
      example = "eth0";
      description = "Kernel interface name whose IRQs (named <interface> or <interface>-* in /proc/interrupts) are pinned.";
    };
    cpus = lib.mkOption {
      type = lib.types.nonEmptyListOf lib.types.ints.unsigned;
      example = [
        0
        1
        2
        3
      ];
      description = "CPUs every IRQ of the interface may run on; written to smp_affinity_list and checked against effective_affinity_list.";
    };
    waitSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 120;
      description = "How long apply waits for the driver to request the interface IRQs (it does so when the link is opened).";
    };
  };
  config = lib.mkIf cfg.enable {
    # irqbalance would rewrite the affinity behind the unit's back.
    systemd.maskedUnits = [ "irqbalance.service" ];
    systemd.services.homelab-irq-affinity = {
      description = "Pin ${cfg.interface} IRQs to CPUs ${cpuList}";
      # The device unit re-starts it when the NIC is re-probed; BindsTo stops
      # it when the device goes away so the next appearance runs apply again.
      wantedBy = [
        "multi-user.target"
        device
      ];
      bindsTo = [ device ];
      after = [ device ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${irqAffinity} apply";
        # system-manager reloads changed units that support it.
        ExecReload = "${irqAffinity} apply";
        ExecStop = "${irqAffinity} reset";
        TimeoutStartSec = cfg.waitSeconds + 30;
      };
    };
  };
}
