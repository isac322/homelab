# Per-node NVMe/TCP DKMS declarations.
#
# Every node that needs supplemental NVMe/TCP modules gets its own DKMS
# package, pinned to exactly one kernel release. The package keeps the shared
# NVMe headers from that kernel's upstream release (`baseline`) and replaces
# only the transport sources with the newest release of the same stable series
# that compiles and links against the node's real kernel (`transport`).
#
# `role` and `modules` are human decisions. `kernelRelease`, `headersPackage`,
# `baseline` and `transport` are written by `nix run .#nvme-tcp-dkms -- select
# <host>`, which test-builds the candidates on the node itself.
{ lib, topology }:
let
  declared = builtins.fromJSON (builtins.readFile ./nvme-tcp-dkms.json);
  roles = {
    host = {
      packageName = "nvme-tcp-host-dkms";
      dkmsName = "nvme-tcp-host";
      subdir = "host";
      allowedModules = [
        "nvme-fabrics"
        "nvme-tcp"
      ];
    };
    target = {
      packageName = "nvmet-tcp-target-dkms";
      dkmsName = "nvmet-tcp-target";
      subdir = "target";
      allowedModules = [ "nvmet-tcp" ];
    };
  };
  moduleSources = {
    nvme-fabrics = "fabrics.c";
    nvme-tcp = "tcp.c";
    nvmet-tcp = "tcp.c";
  };
  sriSha256 = hash: builtins.match "sha256-[A-Za-z0-9+/]{43}=" hash != null;
  release = builtins.match "([0-9]+)\\.([0-9]+)(\\.([0-9]+))?";
  seriesOf =
    version:
    let
      parts = release version;
    in
    assert parts != null;
    "${builtins.elemAt parts 0}.${builtins.elemAt parts 1}";
  sublevelOf =
    version:
    let
      level = builtins.elemAt (release version) 3;
    in
    if level == null then 0 else lib.toInt level;
  mkHost =
    name: decl:
    let
      role = roles.${decl.role};
      node = topology.nodes.${name};
      # Debian and pacman both accept this, and it changes whenever either the
      # transport release or the pinned kernel release changes.
      version = "${decl.transport.version}+${
        lib.concatStringsSep "." (
          builtins.filter (part: part != "") (lib.splitString "-" decl.kernelRelease)
        )
      }";
      packageFormat =
        {
          apt = "deb";
          pacman = "pacman";
        }
        .${node.packageBackend};
    in
    assert lib.assertMsg (builtins.hasAttr name topology.nodes) "nvme-tcp-dkms: unknown node ${name}";
    assert lib.assertMsg (builtins.hasAttr decl.role roles)
      "nvme-tcp-dkms: ${name} has invalid role ${decl.role}";
    assert lib.assertMsg (
      decl.modules != [ ] && lib.all (module: lib.elem module role.allowedModules) decl.modules
    ) "nvme-tcp-dkms: ${name} modules must be a non-empty subset of ${toString role.allowedModules}";
    assert lib.assertMsg (
      builtins.match "[A-Za-z0-9._+~-]+" decl.kernelRelease != null
    ) "nvme-tcp-dkms: ${name} has an invalid kernel release";
    assert lib.assertMsg (
      release decl.baseline.version != null && release decl.transport.version != null
    ) "nvme-tcp-dkms: ${name} versions must be upstream releases";
    assert lib.assertMsg (
      seriesOf decl.baseline.version == seriesOf decl.transport.version
      && sublevelOf decl.transport.version >= sublevelOf decl.baseline.version
    ) "nvme-tcp-dkms: ${name} transport must be the baseline or a newer release of the same series";
    assert lib.assertMsg (
      sriSha256 decl.baseline.hash && sriSha256 decl.transport.hash
    ) "nvme-tcp-dkms: ${name} source hashes must be SRI sha256";
    decl
    // {
      inherit
        name
        version
        packageFormat
        ;
      inherit (role) packageName dkmsName subdir;
      moduleSources = lib.getAttrs decl.modules moduleSources;
      transportFiles = lib.unique (map (module: moduleSources.${module}) decl.modules);
    };
in
{
  inherit roles moduleSources;
  hosts = lib.mapAttrs mkHost declared;
}
