#!/usr/bin/env bash
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
version=$(<"${root}/VERSION")
debian_version=$(dpkg-parsechangelog -l"${root}/debian/changelog" -SVersion)
debian_version=${debian_version%%-*}
arch_version=$(sed -n 's/^pkgver=//p' "${root}/arch/PKGBUILD")

[[ "$debian_version" == "$version" ]] || {
  echo "Debian version $debian_version does not match VERSION $version" >&2
  exit 1
}
[[ "$arch_version" == "$version" ]] || {
  echo "Arch version $arch_version does not match VERSION $version" >&2
  exit 1
}

echo "package versions match: $version"
