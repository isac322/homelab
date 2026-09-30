# Per-node vgem DKMS declarations.
# Every node that needs the vgem (virtual GEM) kernel module gets its own DKMS
# package. The shipped source is the complete drivers/gpu/drm/vgem directory of
# one pinned upstream release of the node's kernel stable series: vgem only
# calls public DRM core APIs, so no private subsystem headers are shipped.
# Same-series sources are still checked against the target vendor kernel:
# vgem-abi-check fails the DKMS build unless every imported symbol resolves
# (with CRCs when the kernel uses MODVERSIONS) and unless the kernel does not
# already provide vgem.
#
# Kernels >= 6.17 (the upstream "drm/vgem: convert to use faux devices"
# series, first shipped by v6.17) register the vgem device on the faux bus;
# libdrm's vgem discovery and KWin's virtual OpenGL backend need the platform
# device, so such sources are built after applying
# nix/pkgs/vgem-platform-device.patch. `platformPatch` records the expected
# source form; the build verifies the tarball content and fails if the two
# disagree, so pinning a series the declaration was not checked against fails
# closed instead of shipping a mismatched module.
#
# `kernelRelease` and `headersPackage` are written by `nix run .#vgem-dkms --
# select <host>`, which test-builds the newest same-series release on the node
# itself; `kernelRelease` records the kernel `select` validated against and
# does not pin the build.
{ lib, topology }:
let
  declared = builtins.fromJSON (builtins.readFile ./vgem-dkms.json);
  packageName = "vgem-dkms";
  dkmsName = "vgem";
  # Upstream sources below this release register a platform device natively.
  fauxSince = "6.17";
  sourceFiles = [
    "vgem_drv.c"
    "vgem_drv.h"
    "vgem_fence.c"
  ];
  sriSha256 = hash: builtins.match "sha256-[A-Za-z0-9+/]{43}=" hash != null;
  release = builtins.match "([0-9]+)\\.([0-9]+)(\\.([0-9]+))?";
  seriesOf =
    version:
    let
      parts = release version;
    in
    assert parts != null;
    "${builtins.elemAt parts 0}.${builtins.elemAt parts 1}";
  mkHost =
    name: decl:
    let
      node = topology.nodes.${name};
      version = decl.source.version;
      # Distro package release; bump it when the packaging itself (dkms.conf,
      # the platform patch, the ABI check) changes for the same source so
      # nodes pick it up.
      packageVersion = "${version}-1";
      # Kernels of this stable series ("<major>.<minor>.*") build the package;
      # the in-package ABI check refuses kernels whose DRM exports differ.
      series = seriesOf version;
      platformPatch = lib.versionAtLeast version fauxSince;
      packageFormat =
        {
          apt = "deb";
          pacman = "pacman";
        }
        .${node.packageBackend};
    in
    assert lib.assertMsg (builtins.hasAttr name topology.nodes) "vgem-dkms: unknown node ${name}";
    assert lib.assertMsg (
      builtins.match "[A-Za-z0-9._+~-]+" decl.kernelRelease != null
    ) "vgem-dkms: ${name} has an invalid kernel release";
    assert lib.assertMsg (
      release decl.source.version != null
    ) "vgem-dkms: ${name} source must be an upstream release";
    assert lib.assertMsg (sriSha256 decl.source.hash)
      "vgem-dkms: ${name} source hash must be SRI sha256";
    decl
    // {
      inherit
        name
        version
        packageVersion
        series
        platformPatch
        packageFormat
        packageName
        dkmsName
        sourceFiles
        ;
      # vgem cannot work on a kernel without the DRM core.
      coreConfig = "CONFIG_DRM";
    };
in
{
  inherit fauxSince sourceFiles;
  hosts = lib.mapAttrs mkHost declared;
}
