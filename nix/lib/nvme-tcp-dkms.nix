# Per-node NVMe/TCP DKMS declarations.
# Every node that needs supplemental NVMe/TCP modules gets its own DKMS
# package, which builds for any kernel of the declared stable series whose
# NVMe ABI matches the shipped headers. The package keeps the shared NVMe
# headers from the node's upstream release (`baseline`) and replaces only the
# transport sources with the newest release of the same stable series that
# compiles and links against the node's real kernel (`transport`).
#
# `role`, `modules` and `patches` are human decisions. `kernelRelease`,
# `headersPackage`, `baseline` and `transport` are written by `nix run
# .#nvme-tcp-dkms -- select <host>`, which test-builds the candidates on the
# node itself; `kernelRelease` records the kernel `select` validated against
# and does not pin the build. `patches` (optional, default none) names local
# backports in nix/pkgs/nvme-tcp-dkms-patches/<name>.patch, applied in order
# over the transport sources when the package is built.
{ lib, topology }:
let
  declared = builtins.fromJSON (builtins.readFile ./nvme-tcp-dkms.json);
  roles = {
    host = {
      packageName = "nvme-tcp-host-dkms";
      dkmsName = "nvme-tcp-host";
      subdir = "host";
      # Kernels without the NVMe host core cannot load the transports at all.
      coreConfig = "CONFIG_NVME_CORE";
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
      # Kernels without the NVMe target core cannot load nvmet-tcp at all.
      coreConfig = "CONFIG_NVME_TARGET";
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
      patches = decl.patches or [ ];
      patchFile = patch: ../pkgs/nvme-tcp-dkms-patches + "/${patch}.patch";
      patchFiles = map patchFile patches;
      # Debian and pacman both accept this, and it changes whenever the
      # baseline or the transport release changes. The kernel release is no
      # longer part of it: one package build covers the whole series. Local
      # patches add a "+p<hash>" marker over their contents, so a changed
      # patch set also changes the DKMS source tree's version.
      patchMarker =
        lib.optionalString (patches != [ ])
          "+p${
            builtins.substring 0 8 (
              builtins.hashString "sha256" (lib.concatMapStrings builtins.readFile patchFiles)
            )
          }";
      version = "${decl.transport.version}+${decl.baseline.version}${patchMarker}";
      # Distro package release; bump it when the packaging itself (dkms.conf,
      # the ABI check) changes for the same sources so nodes pick it up.
      packageVersion = "${version}-2";
      # Kernels of this stable series ("<major>.<minor>.*") build the package;
      # the in-package ABI check refuses kernels whose NVMe headers differ.
      series = seriesOf decl.baseline.version;
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
    assert lib.assertMsg (lib.all
      (patch: builtins.match "[A-Za-z0-9._-]+" patch != null && builtins.pathExists (patchFile patch))
      patches
    ) "nvme-tcp-dkms: ${name} patches must name files in nix/pkgs/nvme-tcp-dkms-patches/<name>.patch";
    decl
    // {
      inherit
        name
        version
        packageVersion
        series
        packageFormat
        patches
        patchFiles
        ;
      inherit (role)
        packageName
        dkmsName
        subdir
        coreConfig
        ;
      moduleSources = lib.getAttrs decl.modules moduleSources;
      transportFiles = lib.unique (map (module: moduleSources.${module}) decl.modules);
    };
in
{
  inherit roles moduleSources;
  hosts = lib.mapAttrs mkHost declared;
}
