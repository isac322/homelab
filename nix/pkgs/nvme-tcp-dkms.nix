# Build one node's NVMe/TCP DKMS package in its OS's native format.
#
# The DKMS source tree is the baseline release's drivers/nvme/<role> directory
# (so every shared header matches the node's kernel) with only the transport
# sources replaced from the pinned newer release. The node's DKMS compiles it
# for any kernel of the same stable series and never downloads anything;
# nvme-tcp-abi-check then fails the build unless it can prove the shipped
# headers' ABI matches the running kernel.
{
  lib,
  stdenvNoCC,
  fetchurl,
  dpkg,
  libarchive,
  xz,
  zstd,
  decl,
}:
let
  tarball =
    version: hash:
    fetchurl {
      url = "mirror://kernel/linux/kernel/v${lib.versions.major version}.x/linux-${version}.tar.xz";
      inherit hash;
    };
  baseline = tarball decl.baseline.version decl.baseline.hash;
  transport = tarball decl.transport.version decl.transport.hash;
  sourceDir = "usr/src/${decl.dkmsName}-${decl.version}";
  description =
    "NVMe/TCP ${decl.subdir} transport (${lib.concatStringsSep ", " decl.modules}) from Linux "
    + "${decl.transport.version} for any ${decl.series}.x kernel with a matching NVMe ABI";
  kbuild =
    lib.concatMapStrings (
      module:
      "obj-m += ${module}.o\n${module}-y := ${lib.removeSuffix ".c" decl.moduleSources.${module}}.o\n"
    ) decl.modules
    + "ccflags-y += -I$(src)\n";
  dkmsConf = ''
    PACKAGE_NAME="${decl.dkmsName}"
    PACKAGE_VERSION="${decl.version}"
    AUTOINSTALL="yes"
    BUILD_EXCLUSIVE_CONFIG="${decl.coreConfig}"
    MAKE[0]="make -C /lib/modules/''${kernelver}/build M=''${dkms_tree}/''${PACKAGE_NAME}/''${PACKAGE_VERSION}/build modules && bash ''${dkms_tree}/''${PACKAGE_NAME}/''${PACKAGE_VERSION}/build/nvme-tcp-abi-check ''${kernelver}"
  ''
  + lib.concatImapStrings (index: module: ''
    BUILT_MODULE_NAME[${toString (index - 1)}]="${module}"
    DEST_MODULE_LOCATION[${toString (index - 1)}]="/updates/dkms"
  '') decl.modules;
  abiCheckConf = ''
    series='${decl.series}'
    own_sources='${lib.concatStringsSep " " (map (module: decl.moduleSources.${module}) decl.modules)}'
    modules='${lib.concatStringsSep " " decl.modules}'
  '';
  debControl = ''
    Package: ${decl.packageName}
    Version: ${decl.packageVersion}
    Architecture: all
    Maintainer: Byeonghoon Yoo <bhyoo@bhyoo.com>
    Section: kernel
    Priority: optional
    Depends: dkms (>= 3.0.10), binutils, ${decl.headersPackage}
    Conflicts: nvme-extras-dkms
    Replaces: nvme-extras-dkms
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
    mkdir -p "$src_dir" transport
    tar -xJf ${baseline} --strip-components=4 -C "$src_dir" \
      linux-${decl.baseline.version}/drivers/nvme/${decl.subdir}
    tar -xJf ${transport} --strip-components=4 -C transport \
      ${lib.concatMapStringsSep " " (
        file: "linux-${decl.transport.version}/drivers/nvme/${decl.subdir}/${file}"
      ) decl.transportFiles}
    cp transport/* "$src_dir/"
    cp "$kbuildPath" "$src_dir/Makefile"
    cp "$dkmsConfPath" "$src_dir/dkms.conf"
    cp "$abiCheckConfPath" "$src_dir/nvme-tcp-abi-check.conf"
    printf '%s\n' \
      'series=${decl.series}' \
      'validated-kernel=${decl.kernelRelease}' \
      'baseline=${decl.baseline.version}' \
      'transport=${decl.transport.version} (${lib.concatStringsSep " " decl.transportFiles})' \
      > "$src_dir/SOURCE_SELECTION"
    find "$pkgroot" -type d -exec chmod 0755 {} +
    find "$pkgroot" -type f -exec chmod 0644 {} +
    install -m 0755 ${./nvme-tcp-abi-check} "$src_dir/nvme-tcp-abi-check"
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
          license = GPL-2.0-only
          conflict = nvme-extras-dkms
          replaces = nvme-extras-dkms
          depend = dkms
          depend = binutils
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
    mkdir -p $out
    cp ${fileName} $out/
    printf '%s\n' ${fileName} > $out/package-file
    runHook postInstall
  '';

  meta = {
    inherit description;
    license = lib.licenses.gpl2Only;
  };
}
