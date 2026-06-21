#!/usr/bin/env bash
# Build RPi v8 kernel package with CONFIG_ARM64_VA_BITS_48=y for rpi4.
#
# Always picks up the LATEST source version currently published by RPi in the
# trixie archive — no version pinning. The resulting .deb files use the same
# package names as the official linux-image-rpi-v8 metapackage chain, with the
# version suffix "+isacva48.1" so dpkg treats them as a higher version and
# correctly overwrites the official files (including kernel8.img).
#
# Why this build exists:
#   The official RPi kernel (linux-image-rpi-v8) is built with
#   CONFIG_ARM64_VA_BITS=39, which causes Envoy's bundled tcmalloc
#   (hardcoded 48-bit VA assumption on aarch64) to abort during init.
#   This rebuild changes only that one Kconfig knob to VA_BITS=48.
#
# Usage (local):
#   bash tools/rpi-kernel-va48/build.sh
#   # → out/*.deb (or $BUILD_DIR/out/*.deb if BUILD_DIR is set)
#
# Env vars (optional):
#   BUILD_DIR   working directory (default: $PWD)
#   DOCKER_HOST docker daemon endpoint (default: docker default)
#
# Requirements:
#   * docker (any modern version)
#   * curl, sha256sum, sed, awk (standard host tools)

set -euo pipefail

BUILD_DIR=${BUILD_DIR:-$(pwd)}
SRC_DIR=$BUILD_DIR/src
OUT_DIR=$BUILD_DIR/out
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RPI_POOL=https://archive.raspberrypi.com/debian/pool/main/l/linux
SOURCES_URL=https://archive.raspberrypi.com/debian/dists/trixie/main/source/Sources.gz
BUILDER_IMAGE=rpi-kernel-builder:trixie

mkdir -p "$SRC_DIR" "$OUT_DIR"

echo "[0/7] builder 이미지 준비 (없으면 build)..."
if ! docker image inspect "$BUILDER_IMAGE" >/dev/null 2>&1; then
  echo "   building $BUILDER_IMAGE from $SCRIPT_DIR/Dockerfile"
  docker build -t "$BUILDER_IMAGE" "$SCRIPT_DIR"
else
  echo "   $BUILDER_IMAGE already exists - skipping"
fi

echo "[1/7] archive에서 latest linux source version 자동 조회..."
curl -sfL -m 30 "$SOURCES_URL" -o /tmp/Sources.gz
gunzip -c /tmp/Sources.gz > /tmp/Sources.txt
LATEST_VER=$(awk '/^Package: linux$/{found=1; next} found && /^Version:/{print $2; exit} /^$/{found=0}' /tmp/Sources.txt)
[ -n "$LATEST_VER" ] || { echo "FAILED to fetch latest version"; exit 1; }
FILE_VER="${LATEST_VER#1:}"
ORIG_VER="${FILE_VER%-*}"
echo "   latest source: $LATEST_VER  (orig=$ORIG_VER)"

# Expose for callers (e.g. CI) that want to know what got built without
# parsing logs.
echo "$LATEST_VER" > "$BUILD_DIR/.latest-version"

echo "[2/7] dsc + orig + debian tarball 다운로드 (캐시되어 있으면 skip)..."
cd "$SRC_DIR"
for f in "linux_${FILE_VER}.dsc" "linux_${ORIG_VER}.orig.tar.xz" "linux_${FILE_VER}.debian.tar.xz"; do
  if [ ! -f "$f" ]; then
    echo "   fetching $f"
    curl -fsSL -o "$f" "$RPI_POOL/$f"
  fi
done

echo "[3/7] sha256 무결성 검증..."
grep -A2 "Checksums-Sha256:" "linux_${FILE_VER}.dsc" | grep -E "tar\.xz$" | awk '{print $1"  "$3}' > .expected-sums
sha256sum -c .expected-sums

echo "[4/7] source 추출 + debian/ overlay..."
rm -rf "linux-${ORIG_VER}"
tar xf "linux_${ORIG_VER}.orig.tar.xz"
cd "linux-${ORIG_VER}"
tar xf "../linux_${FILE_VER}.debian.tar.xz"

echo "[5/7] config.v8: VA_BITS_39 → VA_BITS_48 패치..."
if grep -q '^CONFIG_ARM64_VA_BITS_39=y$' debian/config/arm64/rpi/config.v8; then
  sed -i 's/^CONFIG_ARM64_VA_BITS_39=y$/CONFIG_ARM64_VA_BITS_48=y/' debian/config/arm64/rpi/config.v8
  echo "   patched"
else
  echo "   WARNING: VA_BITS_39 line not found - upstream may have changed. inspecting:"
  head -5 debian/config/arm64/rpi/config.v8
fi

echo "[6/7] defines.toml: v8 flavour만 남기고 v8-rt/2712 제거 + changelog 패치..."
python3 <<PY
from pathlib import Path
import re
p = Path("debian/config/arm64/defines.toml")
t = p.read_text()
# Remove flavour blocks for v8-rt, 2712
for f in ('v8-rt', '2712'):
    t = re.sub(r"\[\[flavour\]\]\nname = '" + f + r"'(?:\n(?!\[\[).*)*\n*", "", t)
# Remove the corresponding featureset.flavour children
for f in ('v8-rt', '2712'):
    t = re.sub(r"\[\[featureset\.flavour\]\]\nname = '" + f + r"'\n", "", t)
p.write_text(t)
PY

NEW_VER="${LATEST_VER}+isacva48.1"
TS="$(LC_ALL=C date -R)"
python3 <<PY
from pathlib import Path
p = Path("debian/changelog")
old = p.read_text()
header = "linux (${NEW_VER}) trixie; urgency=medium\n\n"
body = (
    "  * Local build: enable CONFIG_ARM64_VA_BITS_48 on arm64 v8 flavour\n"
    "    to fix Google TCMalloc startup crash on Pi 4 (Envoy / cilium-envoy).\n"
    "    PGTABLE_LEVELS=4 implied. 4K page size preserved.\n"
    "    Other flavours (v8-rt, 2712, v6, v7) NOT built here.\n"
    "  * Based on raspberrypi/linux $LATEST_VER (source verified by sha256).\n"
    "\n"
    " -- Isac Yoo <isac@runbear.io>  ${TS}\n"
    "\n"
)
p.write_text(header + body + old)
PY
# Drop the official 1:<ORIG_VER>-1+rpt1 entry so the gencontrol ABINAME stays
# as plain +rpt (matching the official package name), instead of +rpt+1 which
# would collide with z50-raspi-firmware's sort -V check on the next install.
sed -i "/^linux (1:${ORIG_VER}-1+rpt1) trixie;/,/^ -- Serge Schneider/d" debian/changelog
head -10 debian/changelog

echo "[7/7] 컨테이너에서 cross-build (v8 only)..."
cd "$BUILD_DIR"
docker run --rm \
  -v "$BUILD_DIR":/work \
  -e HOME=/tmp \
  -w "/work/src/linux-${ORIG_VER}" \
  "$BUILDER_IMAGE" \
  bash -c '
set -eu
export DEB_BUILD_PROFILES="cross nocheck pkg.linux.mintools pkg.linux.nokerneldoc pkg.linux.nosource pkg.linux.norust nodoc"
export DEB_BUILD_OPTIONS="parallel=$(nproc) nocheck"

# Regenerate debian/control from templates
rm -f debian/control debian/control.md5sum
make -f debian/rules debian/control 2>&1 | tail -3 || true

echo "=== dpkg-buildpackage start $(date) ==="
dpkg-buildpackage -b -aarm64 -uc -us -d \
  -Pcross,nocheck,pkg.linux.mintools,pkg.linux.nokerneldoc,pkg.linux.nosource,pkg.linux.norust,nodoc \
  2>&1
echo "=== dpkg-buildpackage end $(date) ==="

# Collect .deb output to /work/out (host visible).
mkdir -p /work/out
cp -v /work/src/*.deb /work/out/
ls -la /work/out
'

echo
echo "=== build 완료: $OUT_DIR ==="
ls -la "$OUT_DIR"
echo "latest version: $(cat "$BUILD_DIR/.latest-version")"
