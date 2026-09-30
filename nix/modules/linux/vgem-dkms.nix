{
  lib,
  name,
  topology,
  hostConfig,
  ...
}:
let
  declared = (import ../../lib/vgem-dkms.nix { inherit lib topology; }).hosts;
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
  config = lib.mkIf (decl != null) {
    # Declared nodes must boot-load vgem so the issue-agent gets a software
    # GEM render device without depending on the node's real GPU.
    environment.etc."modules-load.d/vgem.conf" = {
      text = "vgem\n";
      replaceExisting = true;
    };
    # The package builds for every kernel of the declared stable series that
    # passes the in-package ABI check, so a series change or a DKMS module
    # missing for any headers-installed kernel must be re-declared and
    # re-installed before this host can take another generation.
    system-manager.preActivationAssertions.vgemDkms = {
      enable = true;
      name = "vgemDkms";
      script = ''
        read -r running < /proc/sys/kernel/osrelease
        case "$running" in
          ${decl.series}.*) ;;
          *)
            echo "running kernel $running is not in the declared vgem DKMS series ${decl.series}; run 'nix run .#vgem-dkms -- select ${name}' and commit the result" >&2
            exit 1
            ;;
        esac
        ${installedVersion}
        test "$installed" = ${lib.escapeShellArg decl.packageVersion} || {
          echo "${decl.packageName} ${decl.packageVersion} is not installed (found: ''${installed:-none}); run 'nix run .#vgem-dkms -- install ${name}'" >&2
          exit 1
        }
        kernels="$running"
        for dir in /lib/modules/*; do
          test -e "$dir/build" || continue
          k=''${dir##*/}
          test "$k" = "$running" || kernels="$kernels $k"
        done
        for k in $kernels; do
          # DKMS excludes kernels without the DRM core (BUILD_EXCLUSIVE_CONFIG);
          # vgem cannot work there with any package, e.g. a vendor rescue kernel.
          if test "$k" != "$running" && ! /usr/bin/grep -qE '^${decl.coreConfig}=(y|m)$' "/lib/modules/$k/build/.config" 2>/dev/null; then
            continue
          fi
          case "$k" in
            ${decl.series}.*) ;;
            *)
              echo "kernel $k has headers installed but is not in the declared vgem DKMS series ${decl.series}; run 'nix run .#vgem-dkms -- select ${name}' and commit the result" >&2
              exit 1
              ;;
          esac
          status=$(/usr/sbin/dkms status -m ${decl.dkmsName} -v ${lib.escapeShellArg decl.version} -k "$k" 2>/dev/null || true)
          case "$status" in
            *": installed"*) ;;
            *)
              echo "DKMS module ${decl.dkmsName}/${decl.version} is not installed for $k; the ABI check output is in /var/lib/dkms/${decl.dkmsName}/${decl.version}/build/make.log" >&2
              exit 1
              ;;
          esac
        done
      '';
    };
  };
}
