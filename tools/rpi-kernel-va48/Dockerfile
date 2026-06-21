# syntax=docker/dockerfile:1
#
# Build environment for the rpi4 kernel package. Same image is used for both
# native and cross builds:
#
#   * arm64 container (e.g. on `ubuntu-24.04-arm` or a Pi5): native build,
#     no multiarch / cross tooling needed.
#   * amd64 container (developer workstation): cross build into arm64,
#     pulls in crossbuild-essential-arm64 + arm64 multiarch headers.
#
# Pick the path by passing `--platform=linux/arm64` (or amd64) to `docker build`.
FROM debian:trixie
ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    host_arch=$(dpkg --print-architecture); \
    if [ "$host_arch" = "amd64" ]; then \
        dpkg --add-architecture arm64; \
        extra_pkgs="crossbuild-essential-arm64 gcc-arm-linux-gnueabihf gcc-14-arm-linux-gnueabihf libssl-dev:arm64 libelf-dev:arm64"; \
    else \
        extra_pkgs="gcc-arm-linux-gnueabihf"; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        bc bison flex \
        libssl-dev libelf-dev \
        kmod cpio rsync gawk dwarves zstd xz-utils lz4 \
        kernel-wedge \
        python3 python3-toml python3-jinja2 python3-debian python3-six python3-dacite python3-pyparsing \
        quilt patchutils \
        debhelper devscripts dh-exec dh-python \
        fakeroot pahole \
        ca-certificates curl \
        $extra_pkgs; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work
