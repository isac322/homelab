# Cross-build environment for build-cross.sh
#
# Used when the host is amd64 (e.g. a developer workstation) and you want to
# build the rpi4 kernel package without setting up multiarch on the host
# itself. CI (which already runs on a `ubuntu-24.04-arm` runner) uses
# build-native.sh instead and does NOT need this image.
FROM debian:trixie
ENV DEBIAN_FRONTEND=noninteractive
RUN dpkg --add-architecture arm64 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
    build-essential \
    crossbuild-essential-arm64 gcc-arm-linux-gnueabihf gcc-14-arm-linux-gnueabihf lz4 kernel-wedge \
    bc bison flex \
    libssl-dev libssl-dev:arm64 \
    libelf-dev libelf-dev:arm64 \
    kmod cpio rsync gawk dwarves zstd xz-utils \
    python3 python3-toml python3-jinja2 python3-debian python3-six python3-dacite python3-pyparsing \
    quilt patchutils \
    debhelper devscripts dh-exec dh-python \
    fakeroot \
    pahole \
    ca-certificates curl gnupg \
    git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /work
