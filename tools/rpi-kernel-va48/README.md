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
* **builds + publishes** a GitHub release otherwise, attaching all 8
  `.deb` artifacts.

So as soon as RPi cuts a new stable, this repo ships a `VA_BITS=48`
counterpart on the next daily run. Releases are named
`rpi-kernel-va48-<sanitized-version>` (e.g. `rpi-kernel-va48-1-6.18.34-1-rpt1`).

## Two build scripts

This directory ships two complementary entry points. They produce the
**same set of .deb files** — they only differ in how they reach an
aarch64 build environment:

| Script | Host arch | Container? | Used by |
|---|---|---|---|
| `build-native.sh` | arm64 (e.g. rpi5 / `ubuntu-24.04-arm`) | no | the daily workflow |
| `build-cross.sh`  | amd64 workstation                     | yes (`Dockerfile`) | local developer builds |

`build-cross.sh` carries the extra weight needed to cross-compile from
x86_64 (multiarch arm64 apt, `crossbuild-essential-arm64`,
`-aarm64`/`cross` build profile, `-d` to skip the cross-only
`gcc-14-for-host` virtual dep). `build-native.sh` does none of that —
it just installs build-deps and runs `dpkg-buildpackage -b` directly.

### Manual native build (on an arm64 host)

```bash
cd <homelab repo root>
bash tools/rpi-kernel-va48/build-native.sh
# → out/*.deb (always against the current RPi `trixie` archive head)
```

Requires a Debian trixie (or compatible) arm64 host with `sudo`. The
script `apt-get install`s its own build-deps on first run; set
`SKIP_APT_INSTALL=1` to suppress that step on repeated runs.

### Manual cross build (on an amd64 host)

```bash
cd <homelab repo root>
bash tools/rpi-kernel-va48/build-cross.sh
# → out/*.deb (always against the current RPi `trixie` archive head)
```

Requires only `docker`. The first run builds the `rpi-kernel-builder:trixie`
container image from this directory's `Dockerfile`; subsequent runs reuse it.

Either path takes ~8–10 minutes on a 16-core host. Output is the same set
of files:

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

```bash
# Download the 8 release assets to /tmp/, then:
sudo dpkg -i /tmp/linux-kbuild-6.18.34+rpt_*.deb \
             /tmp/linux-headers-6.18.34+rpt-common-rpi_*.deb \
             /tmp/linux-base-6.18.34+rpt-rpi-v8_*.deb \
             /tmp/linux-headers-6.18.34+rpt-rpi-v8_*.deb \
             /tmp/linux-image-6.18.34+rpt-rpi-v8_*.deb \
             /tmp/linux-base-rpi-v8_*.deb \
             /tmp/linux-headers-rpi-v8_*.deb \
             /tmp/linux-image-rpi-v8_*.deb

# Pin the three metapackages so apt does not silently roll back when
# RPi publishes a new stable — the workflow will build a fresh release
# instead, which the user explicitly opts into.
sudo apt-mark hold linux-image-rpi-v8 linux-base-rpi-v8 linux-headers-rpi-v8

# kernel8.img / initramfs8 / dtbs are updated automatically by the
# raspi-firmware postinst hook. Verify:
grep '^CONFIG_ARM64_VA_BITS=' /boot/config-6.18.34+rpt-rpi-v8   # → 48
md5sum /boot/firmware/kernel8.img /boot/vmlinuz-6.18.34+rpt-rpi-v8  # equal

sudo reboot
```

After reboot, `uname -r` reports the same name as before
(`6.18.34+rpt-rpi-v8` — package name unchanged), and
`grep CONFIG_ARM64_VA_BITS= /boot/config-$(uname -r)` reports `48`.

## Recovery from a boot failure

If the new kernel panics, RPi firmware has no fallback. Recovery is
done with the microSD card mounted externally over USB:

1. Mount the FAT32 boot partition (first partition).
2. Restore the stock kernel (kept on the partition by the workflow run
   that installed the custom build):
   ```bash
   cp kernel8.img.stable-backup    kernel8.img
   cp initramfs8.stable-backup     initramfs8
   sync
   ```
3. Boot rpi4. After SSH is back, the cached `.deb` files at
   `/var/backups/rpi-stable-6.18.34/` provide a fully-package-managed
   downgrade path back to the official RPi build.
