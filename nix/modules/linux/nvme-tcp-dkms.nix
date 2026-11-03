{
  lib,
  name,
  topology,
  hostConfig,
  ...
}:
let
  declared = (import ../../lib/nvme-tcp-dkms.nix { inherit lib topology; }).hosts;
  decl = declared.${name} or null;
  installedVersion =
    if hostConfig.packageBackend == "pacman" then
      ''
        installed=$(/usr/bin/pacman -Q ${decl.packageName} 2>/dev/null || true)
        installed=''${installed#${decl.packageName} }
      ''
    else
      ''
        installed=$(/usr/bin/dpkg-query -W -f='${"$"}{Version}' ${decl.packageName} 2>/dev/null || true)
      '';
  sysfsModules = map (module: lib.replaceStrings [ "-" ] [ "_" ] module) decl.modules;
in
{
  # The package builds for every kernel of the declared stable series that
  # passes the in-package NVMe ABI check, so a series change or a DKMS module
  # missing for any headers-installed kernel must be re-declared and
  # re-installed before this host can take another generation. Before rebooting
  # into a newly upgraded kernel series, activation is allowed once the live
  # kernel still has the declared modules loaded in /sys/module and every newer
  # headers-installed NVMe kernel belongs to the new series and has DKMS built.
  config = lib.mkIf (decl != null) {
    system-manager.preActivationAssertions.nvmeTcpDkms = {
      enable = true;
      name = "nvmeTcpDkms";
      script = ''
        read -r running < /proc/sys/kernel/osrelease
        ${installedVersion}
        test "$installed" = ${lib.escapeShellArg decl.packageVersion} || {
          echo "${decl.packageName} ${decl.packageVersion} is not installed (found: ''${installed:-none}); run 'nix run .#nvme-tcp-dkms -- install ${name}'" >&2
          exit 1
        }
        check_dkms_installed() {
          status=$(/usr/sbin/dkms status -m ${decl.dkmsName} -v ${lib.escapeShellArg decl.version} -k "$1" 2>/dev/null || true)
          case "$status" in
            *": installed"*) ;;
            *)
              echo "DKMS module ${decl.dkmsName}/${decl.version} is not installed for $1; the ABI check output is in /var/lib/dkms/${decl.dkmsName}/${decl.version}/build/make.log" >&2
              exit 1
              ;;
          esac
        }
        case "$running" in
          ${decl.series}.*)
            kernels="$running"
            for dir in /lib/modules/*; do
              test -e "$dir/build" || continue
              k=''${dir##*/}
              test "$k" = "$running" && continue
              /usr/bin/grep -qE '^${decl.coreConfig}=(y|m)$' "/lib/modules/$k/build/.config" 2>/dev/null || continue
              kernels="$kernels $k"
            done
            for k in $kernels; do
              case "$k" in
                ${decl.series}.*) ;;
                *)
                  echo "kernel $k has headers installed but is not in the declared NVMe/TCP DKMS series ${decl.series}; run 'nix run .#nvme-tcp-dkms -- select ${name}' and commit the result" >&2
                  exit 1
                  ;;
              esac
              check_dkms_installed "$k"
            done
            ;;
          *)
            for mod in ${lib.escapeShellArgs sysfsModules}; do
              test -d "/sys/module/$mod" || {
                echo "running kernel $running is outside declared series ${decl.series} and module $mod is not loaded; run 'nix run .#nvme-tcp-dkms -- select ${name}' or load $mod before switching series" >&2
                exit 1
              }
            done
            staged=""
            for dir in /lib/modules/*; do
              test -e "$dir/build" || continue
              k=''${dir##*/}
              test "$k" = "$running" && continue
              /usr/bin/grep -qE '^${decl.coreConfig}=(y|m)$' "/lib/modules/$k/build/.config" 2>/dev/null || continue
              newest=$(printf '%s\n%s\n' "$running" "$k" | /usr/bin/sort -V | /usr/bin/tail -n 1)
              test "$newest" = "$k" || continue
              case "$k" in
                ${decl.series}.*) ;;
                *)
                  echo "staged kernel $k is not in the declared NVMe/TCP DKMS series ${decl.series}; run 'nix run .#nvme-tcp-dkms -- select ${name}' and commit the result" >&2
                  exit 1
                  ;;
              esac
              check_dkms_installed "$k"
              staged="$staged $k"
            done
            test -n "$staged" || {
              echo "running kernel $running is not in the declared NVMe/TCP DKMS series ${decl.series} and no newer ${decl.series}.x kernel headers are staged; run 'nix run .#nvme-tcp-dkms -- select ${name}' and commit the result" >&2
              exit 1
            }
            ;;
        esac
      '';
    };
  };
}
