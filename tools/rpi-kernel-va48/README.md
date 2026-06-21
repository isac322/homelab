# RPi v8 kernel with `CONFIG_ARM64_VA_BITS=48` for rpi4

Custom build of the official `linux-image-rpi-v8` package so it can run
software that assumes a 48-bit virtual address space on `aarch64` —
specifically Envoy / `cilium-envoy`, whose bundled `tcmalloc` hardcodes
`kAddressBits = 48` and aborts during init on the stock RPi kernel
(`CONFIG_ARM64_VA_BITS=39`, 512 GB user VA).

The build changes **only one Kconfig knob** in the upstream RPi source
(`bcm2711` defconfig, `arm64/rpi/config.v8`):

```diff
-CONFIG_ARM64_VA_BITS_39=y
+CONFIG_ARM64_VA_BITS_48=y
```

Everything else (page size, page table levels, RPi downstream patches,
device trees, overlays) is the unmodified upstream RPi v8 build.

## Automation

The [`rpi-kernel-va48`](../../.github/workflows/rpi-kernel-va48.yaml)
workflow runs daily on a `ubuntu-24.04-arm` runner, polls the RPi
`trixie` archive for the latest `src:linux` source version, and:

* **skips** if a release tagged for that exact version already exists,
* **builds + publishes** a GitHub release otherwise, attaching all the
  `.deb` artifacts.

So as soon as RPi cuts a new stable, this repo ships a `VA_BITS=48`
counterpart on the next daily run. Releases are named
`rpi-kernel-va48-<sanitized-version>` (e.g. `rpi-kernel-va48-1-6.18.34-1-rpt1`).

## How the build works

A single `Dockerfile` + a single `build.sh` cover both build modes:

| Host arch | Container arch | Build mode |
|---|---|---|
| amd64 (workstation) | amd64 | cross-build (amd64 → arm64) |
| arm64 (Pi5 / `ubuntu-24.04-arm`) | arm64 | native |

`docker build` resolves to the host architecture automatically; the
container then inspects its own `dpkg --print-architecture` and toggles
the cross-compile flags accordingly. Same image, same script, same set
of output `.deb` files — only the `dpkg-buildpackage` invocation differs.

### Manual build

```bash
cd <homelab repo root>
bash tools/rpi-kernel-va48/build.sh
# → out/*.deb (always against the current RPi `trixie` archive head)
```

Requires only `docker`. The first run builds the
`rpi-kernel-builder:trixie` image; subsequent runs reuse it. Takes
~8–10 minutes on a 16-core host. Output:

* `linux-image-6.18.34+rpt-rpi-v8_<ver>+isacva48.1_arm64.deb` — vmlinuz + modules + dtb
* `linux-headers-6.18.34+rpt-rpi-v8_…_arm64.deb`
* `linux-headers-6.18.34+rpt-common-rpi_…_all.deb`
* `linux-kbuild-6.18.34+rpt_…_arm64.deb`
* `linux-base-6.18.34+rpt-rpi-v8_…_arm64.deb`
* `linux-{image,base,headers}-rpi-v8_…_arm64.deb` (metapackages)
* (optional) matching `-dbg` packages

Package names are **identical to the official RPi packages** so `dpkg -i`
overwrites them in place. The version suffix `+isacva48.1` ranks higher
than `+rpt1`, so dpkg accepts it without `--force-downgrade`.

## Install on rpi4

### 1) Cache the stock build for offline downgrade

One-time, idempotent — needed for recovery if the new kernel panics.

```bash
# FAT32 backup of the currently-running kernel — accessible from
# a rescue host even when rpi4 won't boot.
sudo cp -n /boot/firmware/kernel8.img  /boot/firmware/kernel8.img.stable-backup
sudo cp -n /boot/firmware/initramfs8   /boot/firmware/initramfs8.stable-backup

# Package-level backup, used to repair the rootfs after a rescue boot.
sudo mkdir -p /var/backups/rpi-stable
cd /var/backups/rpi-stable
sudo apt-get download \
  linux-image-rpi-v8 linux-base-rpi-v8 linux-headers-rpi-v8 \
  "linux-image-$(uname -r)" "linux-headers-$(uname -r)" "linux-base-$(uname -r)"
```

### 2) Install the custom build

```bash
# Resolve the latest VA48 release tag.
TAG=$(gh release list --repo isac322/homelab --limit 50 \
        --json tagName -q '[.[] | select(.tagName | startswith("rpi-kernel-va48-"))][0].tagName')
WORK=$(mktemp -d) && cd "$WORK"

gh release download "$TAG" --repo isac322/homelab --pattern '*.deb'
rm -f *-dbg_*.deb linux-libc-dev_*.deb

# Replace the metapackages.
sudo apt-mark unhold linux-image-rpi-v8 linux-base-rpi-v8 linux-headers-rpi-v8 2>/dev/null || true

sudo dpkg -i \
  linux-kbuild-*+rpt_*_arm64.deb \
  linux-headers-*+rpt-common-rpi_*_all.deb \
  linux-base-*+rpt-rpi-v8_*_arm64.deb \
  linux-headers-*+rpt-rpi-v8_*_arm64.deb \
  linux-image-*+rpt-rpi-v8_*_arm64.deb \
  linux-base-rpi-v8_*_arm64.deb \
  linux-headers-rpi-v8_*_arm64.deb \
  linux-image-rpi-v8_*_arm64.deb

# Re-hold so apt cannot silently roll back to +rpt1 when RPi cuts
# a new stable — the workflow publishes a fresh VA48 release on
# its next daily run instead.
sudo apt-mark hold linux-image-rpi-v8 linux-base-rpi-v8 linux-headers-rpi-v8

# Verify VA_BITS=48 baked in + firmware copy matches /boot/vmlinuz-*.
KVER=$(ls -1 /boot/config-*+rpt-rpi-v8 | sed 's,/boot/config-,,' | tail -1)
grep '^CONFIG_ARM64_VA_BITS=' "/boot/config-$KVER"   # → 48
md5sum /boot/firmware/kernel8.img "/boot/vmlinuz-$KVER"

sudo reboot
```

After reboot `uname -r` is unchanged (`+rpt-rpi-v8`); only
`CONFIG_ARM64_VA_BITS=48` differs from the stock build.

## Recovery from a boot failure

If the new kernel panics, RPi firmware has no automatic fallback.
Power off, pull the microSD, and mount it externally on a rescue host.

### 1) Restore the stock kernel on the FAT32 boot partition

```bash
cp kernel8.img.stable-backup  kernel8.img
cp initramfs8.stable-backup   initramfs8
sync
```

### 2) Boot rpi4 and reinstall the stock packages

```bash
sudo apt-mark unhold linux-image-rpi-v8 linux-base-rpi-v8 linux-headers-rpi-v8
sudo dpkg -i /var/backups/rpi-stable/*.deb
```
