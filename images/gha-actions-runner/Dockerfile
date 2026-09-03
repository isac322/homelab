FROM ghcr.io/actions/actions-runner:2.337.0@sha256:e5496277be5d09bc968b3d64911b74e219ac4a3f2edce956a3ecf9271bea1ef4

# Official ARC image has no C toolchain (no cc, gcc, clang, or ld).
# Match isac322/cc-lb .github/runner-image: clang for cc-rs, not gcc.
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        clang \
        mold \
        libc6-dev \
        pkg-config \
        libssl-dev \
        make \
        postgresql-client \
    && ln -sf /usr/bin/clang /usr/local/bin/cc \
    && ln -sf /usr/bin/clang++ /usr/local/bin/c++ \
    && rm -rf /var/lib/apt/lists/*
ENV CC=clang \
    CXX=clang++
USER runner
