# Build one node's vgem DKMS package in its OS's native format.
#
# The DKMS source tree is the pinned release's complete drivers/gpu/drm/vgem
# directory. vgem only calls public DRM core APIs, so no private subsystem
# headers are shipped; the node's DKMS compiles it for any kernel of the same
# stable series and never downloads anything. When the pinned source registers
# its device on the faux bus (upstream since v6.17), the committed
# vgem-platform-device.patch restores the platform_device registration that
# libdrm's vgem discovery needs. vgem-abi-check then fails the DKMS build unless
# it can prove the module's imports resolve on the target kernel and the
# kernel does not already provide vgem.
{
  lib,
  stdenvNoCC,
  fetchurl,
  dpkg,
  libarchive,
  patch,
  xz,
  zstd,
  decl,
}:
let
  source = fetchurl {
    url = "mirror://kernel/linux/kernel/v${lib.versions.major decl.source.version}.x/linux-${decl.source.version}.tar.xz";
    inherit (decl.source) hash;
  };
  sourceDir = "usr/src/${decl.dkmsName}-${decl.version}";
  description =
    "vgem virtual GEM provider from Linux ${decl.source.version} for any ${decl.series}.x kernel"
    + lib.optionalString decl.platformPatch " (platform-device registration restored)";
  kbuild =
    "obj-m += ${decl.dkmsName}.o\n${decl.dkmsName}-y := vgem_drv.o vgem_fence.o\n"
    + "ccflags-y += -I$(src)\n";
  dkmsConf = ''
    PACKAGE_NAME="${decl.dkmsName}"
    PACKAGE_VERSION="${decl.version}"
    AUTOINSTALL="yes"
    BUILD_EXCLUSIVE_CONFIG="${decl.coreConfig}"
    MAKE[0]="make -C /lib/modules/''${kernelver}/build M=''${dkms_tree}/''${PACKAGE_NAME}/''${PACKAGE_VERSION}/build modules && bash ''${dkms_tree}/''${PACKAGE_NAME}/''${PACKAGE_VERSION}/build/vgem-abi-check ''${kernelver}"
    BUILT_MODULE_NAME[0]="${decl.dkmsName}"
    DEST_MODULE_LOCATION[0]="/updates/dkms"
  '';
  abiCheckConf = ''
    series='${decl.series}'
    own_module='${decl.dkmsName}'
  '';
  debControl = ''
    Package: ${decl.packageName}
    Version: ${decl.packageVersion}
    Architecture: all
    Maintainer: Byeonghoon Yoo <bhyoo@bhyoo.com>
    Section: kernel
    Priority: optional
    Depends: dkms (>= 3.0.10), binutils, kmod, pahole, ${decl.headersPackage}
    Homepage: https://github.com/isac322/homelab
    Description: ${description}
  '';
  debPostinst = ''
    #!/bin/sh
    set -e
    if [ "$1" = configure ]; then
      /usr/lib/dkms/common.postinst ${decl.dkmsName} ${decl.version} /usr/share/${decl.packageName} "" "$2"
    fi
  '';
  debPrerm = ''
    #!/bin/sh
    set -e
    case "$1" in
      remove|upgrade|deconfigure)
        dkms remove -m ${decl.dkmsName} -v ${decl.version} --all || true
        ;;
    esac
  '';
  fileName =
    if decl.packageFormat == "deb" then
      "${decl.packageName}_${decl.packageVersion}_all.deb"
    else
      "${decl.packageName}-${decl.packageVersion}-any.pkg.tar.zst";
in
stdenvNoCC.mkDerivation {
  pname = decl.packageName;
  version = "${decl.version}-${decl.name}";
  dontUnpack = true;
  nativeBuildInputs = [
    dpkg
    libarchive
    patch
    xz
    zstd
  ];
  env.SOURCE_DATE_EPOCH = "1";
  passAsFile = [
    "kbuild"
    "abiCheckConf"
    "dkmsConf"
    "debControl"
    "debPostinst"
    "debPrerm"
  ];
  inherit
    kbuild
    abiCheckConf
    dkmsConf
    debControl
    debPostinst
    debPrerm
    ;

  buildPhase = ''
    runHook preBuild
    pkgroot=$PWD/pkgroot
    src_dir=$pkgroot/${sourceDir}
    mkdir -p "$src_dir"
    tar -xJf ${source} --strip-components=5 -C "$src_dir" \
      linux-${decl.source.version}/drivers/gpu/drm/vgem
    rm -f "$src_dir/Makefile" "$src_dir/Kconfig"
    for file in ${lib.concatStringsSep " " decl.sourceFiles}; do
      test -f "$src_dir/$file" || {
        echo "vgem-dkms: linux-${decl.source.version} lacks drivers/gpu/drm/vgem/$file" >&2
        exit 1
      }
    done
    # Kernels >= 6.17 register vgem on the faux bus; the committed patch
    # restores the platform device libdrm's software-render-node discovery needs. The pinned
    # tarball must look the way the declaration expects, so both directions
    # fail the build rather than shipping a mismatched module.
    if grep -q 'faux_device_create' "$src_dir/vgem_drv.c"; then uses_faux=1; else uses_faux=0; fi
    if [ "$uses_faux" != "${if decl.platformPatch then "1" else "0"}" ]; then
      echo "vgem-dkms: linux-${decl.source.version} vgem_drv.c uses faux_device=$uses_faux, but the declaration expected platformPatch=${lib.boolToString decl.platformPatch}; re-check the pinned source" >&2
      exit 1
    fi
    if [ "$uses_faux" = 1 ]; then
      patch -d "$src_dir" -p1 --no-backup-if-mismatch < ${./vgem-platform-device.patch}
      ! grep -q 'faux_device' "$src_dir/vgem_drv.c" || {
        echo "vgem-dkms: platform-device patch left faux_device references in vgem_drv.c" >&2
        exit 1
      }
    fi
    cp "$kbuildPath" "$src_dir/Makefile"
    cp "$dkmsConfPath" "$src_dir/dkms.conf"
    cp "$abiCheckConfPath" "$src_dir/vgem-abi-check.conf"
    printf '%s\n' \
      'series=${decl.series}' \
      'validated-kernel=${decl.kernelRelease}' \
      'source=${decl.source.version} (${lib.concatStringsSep " " decl.sourceFiles})' \
      'platform-device-patch=${lib.boolToString decl.platformPatch}' \
      > "$src_dir/SOURCE_SELECTION"
    find "$pkgroot" -type d -exec chmod 0755 {} +
    find "$pkgroot" -type f -exec chmod 0644 {} +
    install -m 0755 ${./vgem-abi-check} "$src_dir/vgem-abi-check"
    ${
      if decl.packageFormat == "deb" then
        ''
          mkdir -p "$pkgroot/DEBIAN"
          cp "$debControlPath" "$pkgroot/DEBIAN/control"
          install -m 0755 "$debPostinstPath" "$pkgroot/DEBIAN/postinst"
          install -m 0755 "$debPrermPath" "$pkgroot/DEBIAN/prerm"
          find "$pkgroot" -exec touch -h -d @1 {} +
          dpkg-deb --root-owner-group -Zxz --build "$pkgroot" ${fileName}
        ''
      else
        ''
          size=$(du -sk --apparent-size "$pkgroot" | cut -f1)
          cat > "$pkgroot/.PKGINFO" <<EOF
          pkgname = ${decl.packageName}
          pkgbase = ${decl.packageName}
          pkgver = ${decl.packageVersion}
          pkgdesc = ${description}
          url = https://github.com/isac322/homelab
          builddate = 1
          packager = homelab Nix
          size = $((size * 1024))
          arch = any
          license = MIT
          depend = dkms
          depend = binutils
          depend = kmod
          depend = pahole
          depend = ${decl.headersPackage}
          EOF
          find "$pkgroot" -exec touch -h -d @1 {} +
          cd "$pkgroot"
          # A Darwin builder would otherwise add AppleDouble ._ entries.
          tar_flags="--no-mac-metadata --no-xattrs --no-acls --no-fflags --uid 0 --gid 0 --uname root --gname root"
          bsdtar $tar_flags -czf .MTREE --format=mtree \
            --options='!all,use-set,type,uid,gid,mode,time,size,md5,sha256,link' .PKGINFO usr
          touch -h -d @1 .MTREE
          bsdtar $tar_flags -cnf - .MTREE .PKGINFO \
            $(find usr | LC_ALL=C sort) | zstd -19 -q -o ../${fileName}
          cd ..
        ''
    }
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p $out/vgem-src
    cp ${fileName} $out/
    printf '%s\n' ${fileName} > $out/package-file
    # The prepared build tree (patched sources plus the Kbuild Makefile) is
    # also exposed so the same pinned source can be test-compiled against any
    # kernel headers, e.g. `make -C /lib/modules/$(uname -r)/build
    # M=$out/vgem-src modules` in a disposable guest or on a node.
    cp "$src_dir"/*.c "$src_dir"/*.h "$src_dir/Makefile" "$src_dir/SOURCE_SELECTION" \
      "$src_dir/vgem-abi-check" "$src_dir/vgem-abi-check.conf" $out/vgem-src/
    runHook postInstall
  '';

  meta = {
    inherit description;
    license = lib.licenses.mit;
  };
}
