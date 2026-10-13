{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.homelab.zfsScrub;
  # The host owns ZFS: userland must match the running kmod, so call its zpool.
  zpool = "/usr/sbin/zpool";
  zfsScrub = pkgs.writeShellScript "homelab-zfs-scrub" ''
    set -euo pipefail
    export PATH=${
      lib.makeBinPath [
        pkgs.coreutils
        pkgs.gnugrep
      ]
    }

    test "$#" -eq 1 || { echo "usage: homelab-zfs-scrub <pool>" >&2; exit 2; }
    pool=$1

    # A scrub started by hand or by a previous run is waited for, not restarted.
    if ${zpool} status "$pool" | grep -q "scrub in progress"; then
      echo "homelab-zfs-scrub: $pool: scrub already running, waiting"
      ${zpool} wait -t scrub "$pool"
    else
      echo "homelab-zfs-scrub: $pool: starting scrub"
      ${zpool} scrub -w "$pool"
    fi

    scan=$(${zpool} status "$pool" | grep "scan:" || true)
    echo "homelab-zfs-scrub: $pool: $scan"
    health=$(${zpool} status -x "$pool")
    # Fail the unit (systemctl --failed) when the scrub found or left damage.
    if [ "$health" != "pool '$pool' is healthy" ]; then
      echo "homelab-zfs-scrub: $pool: $health" >&2
      exit 1
    fi
    case "$scan" in
      *"scrub repaired 0B"*"with 0 errors"*) ;;
      *)
        echo "homelab-zfs-scrub: $pool: scrub did not finish clean" >&2
        exit 1
        ;;
    esac
  '';
  unitName = pool: "homelab-zfs-scrub-${pool}";
in
{
  options.homelab.zfsScrub = {
    enable = lib.mkEnableOption "periodic scrubs of the host's ZFS pools";
    pools = lib.mkOption {
      type = lib.types.attrsOf (lib.types.strMatching ".+");
      default = { };
      example = {
        nas = "*-*-01 03:00:00";
      };
      description = ''
        Pool name to systemd OnCalendar expression. Stagger the times so pools on
        the same disks do not scrub together.
      '';
    };
  };
  config = lib.mkIf cfg.enable {
    systemd.services = lib.mapAttrs' (
      pool: _:
      lib.nameValuePair (unitName pool) {
        description = "Scrub ZFS pool ${pool}";
        requires = [ "zfs.target" ];
        after = [ "zfs.target" ];
        # system-manager restarts changed units on activation; a scrub must only
        # start from its timer, never from a generation switch.
        restartIfChanged = false;
        serviceConfig = {
          # Not oneshot: systemd skips ExecStop for a oneshot stopped while
          # ExecStart still runs, and a scrub takes hours. With exec the unit is
          # active during the scrub, so stopping it (shutdown, systemctl stop)
          # pauses the scrub and the next run resumes it. After a normal finish
          # the pause finds no scrub and its error is ignored.
          Type = "exec";
          ExecStart = "${zfsScrub} ${pool}";
          ExecStop = "-${zpool} scrub -p ${pool}";
        };
      }
    ) cfg.pools;
    systemd.timers = lib.mapAttrs' (
      pool: onCalendar:
      lib.nameValuePair (unitName pool) {
        description = "Periodic scrub of ZFS pool ${pool}";
        wantedBy = [ "timers.target" ];
        timerConfig = {
          OnCalendar = onCalendar;
          # Run after boot when the host was down at the scheduled time.
          Persistent = true;
          RandomizedDelaySec = "30m";
        };
      }
    ) cfg.pools;
  };
}
