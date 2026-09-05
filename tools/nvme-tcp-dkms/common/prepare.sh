#!/usr/bin/env bash
set -euo pipefail

if (( $# != 4 )); then
  echo "usage: $0 <kernel-release> <host|target> <module-list> <build-directory>" >&2
  exit 2
fi

KERNELVER=$1
role=$2
module_list=$3
module_list=${module_list//,/ }
build_dir=$4
export KERNELVER

case "$KERNELVER" in
  ""|*[!A-Za-z0-9._+~-]*)
    echo "invalid kernel release: $KERNELVER" >&2
    exit 2
    ;;
esac
case "$role" in
  host|target) ;;
  *) echo "unsupported role: $role" >&2; exit 2 ;;
esac

# Source precedence is: root-owned override, complete installed vendor source,
# then a kernel.org tarball matching the numeric kernel release. An override may
# set NVME_TCP_SOURCE_DIR or both NVME_TCP_SOURCE_URL and
# NVME_TCP_SOURCE_SHA256 in /etc/nvme-tcp-dkms/source.conf.
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
selector="${script_dir}/select-modules.sh"
config=/etc/nvme-tcp-dkms/source.conf

if [[ -e "$config" ]]; then
  read -r owner mode < <(stat -c '%u %a' "$config")
  if [[ "$owner" != 0 ]] || (( (8#$mode & 022) != 0 )); then
    echo "$config must be owned by root and not writable by group or other" >&2
    exit 1
  fi
  # shellcheck source=/dev/null
  source "$config"
fi
cache_dir=${NVME_TCP_CACHE_DIR:-/var/cache/nvme-tcp-dkms}
expected_signer=${NVME_TCP_KERNEL_SIGNING_FINGERPRINT:-647F28654894E3BD457199BE38DBBDC86092693E}


case "$role" in
  host)
    "$selector" "$KERNELVER" has-stock nvme_core || {
      echo "the vendor kernel must provide nvme_core; this package never replaces it" >&2
      exit 1
    }
    allowed=' nvme-fabrics nvme-tcp '
    source_subdir=host
    ;;
  target)
    "$selector" "$KERNELVER" has-stock nvmet || {
      echo "the vendor kernel must provide nvmet; this package only supplements nvmet_tcp" >&2
      exit 1
    }
    allowed=' nvmet-tcp '
    source_subdir=target
    ;;
esac

read -r -a modules <<< "$module_list"
(( ${#modules[@]} > 0 )) || {
  echo "no modules selected" >&2
  exit 2
}
for module in "${modules[@]}"; do
  [[ "$allowed" == *" $module "* ]] || {
    echo "module $module is invalid for role $role" >&2
    exit 2
  }
done

mkdir -p "$cache_dir"
exec 9>"${cache_dir}/.lock"
flock 9

find_source_root() {
  local root=$1 nvme_dir source_root
  if [[ -d "${root}/drivers/nvme" ]]; then
    source_root=$root
  else
    nvme_dir=$(find "$root" -type d -path '*/drivers/nvme' -print -quit 2>/dev/null)
    [[ -n "$nvme_dir" ]] || return 1
    source_root=${nvme_dir%/drivers/nvme}
  fi
  [[ -f "${source_root}/drivers/nvme/host/tcp.c" ]] || return 1
  [[ -f "${source_root}/drivers/nvme/target/tcp.c" ]] || return 1
  printf '%s\n' "$source_root"
}

find_installed_source() {
  local candidate source_root
  for candidate in \
    "/lib/modules/${KERNELVER}/source" \
    "/usr/lib/modules/${KERNELVER}/source" \
    "/usr/src/linux-${KERNELVER}"; do
    if source_root=$(find_source_root "$candidate"); then
      printf '%s\n' "$source_root"
      return 0
    fi
  done
  return 1
}

download() {
  local url=$1 destination=$2 temporary
  [[ -s "$destination" ]] && return 0
  temporary="${destination}.tmp.$$"
  if ! curl --fail --location --silent --show-error --retry 3 --connect-timeout 15 \
      "$url" -o "$temporary"; then
    rm -f "$temporary"
    return 1
  fi
  mv "$temporary" "$destination"
}

source_root=
if [[ -n "${NVME_TCP_SOURCE_DIR:-}" ]]; then
  source_root=$(find_source_root "$NVME_TCP_SOURCE_DIR") || {
    echo "NVME_TCP_SOURCE_DIR does not contain complete NVMe host and target sources: $NVME_TCP_SOURCE_DIR" >&2
    exit 1
  }
elif source_root=$(find_installed_source); then
  :
elif [[ -n "${NVME_TCP_SOURCE_URL:-}" ]]; then
  [[ "${NVME_TCP_SOURCE_SHA256:-}" =~ ^[0-9a-fA-F]{64}$ ]] || {
    echo "NVME_TCP_SOURCE_SHA256 is required with NVME_TCP_SOURCE_URL" >&2
    exit 1
  }
  archive_name=${NVME_TCP_SOURCE_URL%%\?*}
  archive_name=${archive_name##*/}
  [[ "$archive_name" =~ \.tar(\.gz|\.xz|\.bz2|\.zst)?$ ]] || {
    echo "unsupported source archive name: $archive_name" >&2
    exit 1
  }
  archive="${cache_dir}/${NVME_TCP_SOURCE_SHA256,,}-${archive_name}"
  extract_dir="${cache_dir}/vendor-${NVME_TCP_SOURCE_SHA256,,}"
  download "$NVME_TCP_SOURCE_URL" "$archive"
  printf '%s  %s\n' "${NVME_TCP_SOURCE_SHA256,,}" "$archive" | sha256sum --check --status
  if ! find_source_root "$extract_dir" >/dev/null; then
    temporary=$(mktemp -d "${cache_dir}/extract.XXXXXX")
    trap 'rm -rf "$temporary"' EXIT
    tar -xf "$archive" -C "$temporary"
    extracted_root=$(find_source_root "$temporary") || {
      echo "source archive does not contain drivers/nvme" >&2
      exit 1
    }
    rm -rf "$extract_dir"
    mkdir -p "$extract_dir"
    cp -a "${extracted_root}/." "$extract_dir/"
    rm -rf "$temporary"
    trap - EXIT
  fi
  source_root=$(find_source_root "$extract_dir")
else
  upstream_version=$(printf '%s\n' "$KERNELVER" | grep -oE '^[0-9]+\.[0-9]+\.[0-9]+' || true)
  [[ -n "$upstream_version" ]] || {
    echo "cannot derive an upstream version from $KERNELVER" >&2
    exit 1
  }
  source_version=$upstream_version
  if [[ "$source_version" == *.0 ]]; then
    source_version=${source_version%.0}
  fi
  major=${upstream_version%%.*}
  base_url="https://cdn.kernel.org/pub/linux/kernel/v${major}.x/linux-${source_version}.tar"
  archive="${cache_dir}/linux-${source_version}.tar.xz"
  signature="${cache_dir}/linux-${source_version}.tar.sign"
  extract_dir="${cache_dir}/linux-${source_version}"

  download "${base_url}.xz" "$archive"
  download "${base_url}.sign" "$signature"

  gnupg_home="${cache_dir}/gnupg"
  mkdir -p "$gnupg_home"
  chmod 0700 "$gnupg_home"
  if ! gpg --homedir "$gnupg_home" --batch --with-colons --fingerprint "$expected_signer" \
      2>/dev/null | grep -q "^fpr:::::::::${expected_signer}:"; then
    gpg --homedir "$gnupg_home" --batch --auto-key-locate clear,wkd \
      --locate-keys gregkh@kernel.org
  fi
  gpg --homedir "$gnupg_home" --batch --with-colons --fingerprint "$expected_signer" \
    | grep -q "^fpr:::::::::${expected_signer}:" || {
      echo "kernel signing key fingerprint did not match $expected_signer" >&2
      exit 1
    }

  status=$(mktemp "${cache_dir}/gpg-status.XXXXXX")
  trap 'rm -f "$status"' EXIT
  xz -dc "$archive" | gpg --homedir "$gnupg_home" --batch --status-fd 3 \
    --verify "$signature" - 3>"$status"
  grep -q "^\[GNUPG:\] VALIDSIG ${expected_signer} " "$status" || {
    echo "kernel source signature was not made by $expected_signer" >&2
    exit 1
  }
  rm -f "$status"
  trap - EXIT

  if ! find_source_root "$extract_dir" >/dev/null; then
    temporary=$(mktemp -d "${cache_dir}/extract.XXXXXX")
    trap 'rm -rf "$temporary"' EXIT
    tar -xJf "$archive" --strip-components=1 -C "$temporary" \
      "linux-${source_version}/drivers/nvme"
    rm -rf "$extract_dir"
    mv "$temporary" "$extract_dir"
    trap - EXIT
  fi
  source_root=$(find_source_root "$extract_dir")
fi

source_dir="${source_root}/drivers/nvme/${source_subdir}"
[[ -d "$source_dir" ]] || {
  echo "source tree lacks $source_dir" >&2
  exit 1
}

rm -rf "$build_dir"
mkdir -p "$build_dir"
cp -a "${source_dir}/." "$build_dir/"

{
  printf '%s\n' '# Generated by nvme-tcp-dkms prepare.sh.'
  for module in "${modules[@]}"; do
    case "$module" in
      nvme-fabrics)
        printf '%s\n' 'obj-m += nvme-fabrics.o' 'nvme-fabrics-y := fabrics.o'
        ;;
      nvme-tcp)
        printf '%s\n' 'obj-m += nvme-tcp.o' 'nvme-tcp-y := tcp.o'
        ;;
      nvmet-tcp)
        printf '%s\n' "ccflags-y += -I\$(src)" 'obj-m += nvmet-tcp.o' 'nvmet-tcp-y := tcp.o'
        ;;
    esac
  done
} > "${build_dir}/Makefile"

printf 'prepared %s modules (%s) for %s from %s\n' \
  "$role" "$module_list" "$KERNELVER" "$source_root"
