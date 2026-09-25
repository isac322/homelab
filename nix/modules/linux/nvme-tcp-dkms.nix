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
in
{
  # The package is pinned to one kernel release, so a kernel change must be
  # re-declared before this host can take another generation.
  config = lib.mkIf (decl != null) {
    system-manager.preActivationAssertions.nvmeTcpDkms = {
      enable = true;
      name = "nvmeTcpDkms";
      script = ''
        read -r running < /proc/sys/kernel/osrelease
        test "$running" = ${lib.escapeShellArg decl.kernelRelease} || {
          echo "running kernel $running differs from the declared NVMe/TCP DKMS kernel ${decl.kernelRelease}; run 'nix run .#nvme-tcp-dkms -- select ${name}' and commit the result" >&2
          exit 1
        }
        ${installedVersion}
        test "$installed" = ${lib.escapeShellArg "${decl.version}-1"} || {
          echo "${decl.packageName} ${decl.version}-1 is not installed (found: ''${installed:-none}); run 'nix run .#nvme-tcp-dkms -- install ${name}'" >&2
          exit 1
        }
        status=$(/usr/sbin/dkms status -m ${decl.dkmsName} -v ${lib.escapeShellArg decl.version} -k "$running" 2>/dev/null || true)
        case "$status" in
          *": installed"*) ;;
          *)
            echo "DKMS module ${decl.dkmsName}/${decl.version} is not installed for $running" >&2
            exit 1
            ;;
        esac
      '';
    };
  };
}
