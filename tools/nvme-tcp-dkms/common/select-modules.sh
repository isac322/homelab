#!/usr/bin/env bash
set -euo pipefail

if (( $# < 2 )); then
  echo "usage: $0 <kernel-release> <host|target|has-stock> [module]" >&2
  exit 2
fi

kernelver=$1
mode=$2
modules_root=${NVME_TCP_MODULES_ROOT:-/lib/modules}
kernel_dir="${modules_root}/${kernelver}"

case "$kernelver" in
  ""|*[!A-Za-z0-9._+~-]*)
    echo "invalid kernel release: $kernelver" >&2
    exit 2
    ;;
esac

stock_module_present() {
  local module=$1 dashed underscored found
  dashed=${module//_/-}
  underscored=${module//-/_}

  if [[ -r "${kernel_dir}/modules.builtin" ]] &&
    grep -Eq "/(${dashed}|${underscored})\.ko$" "${kernel_dir}/modules.builtin"; then
    return 0
  fi

  found=
  if [[ -d "${kernel_dir}/kernel" ]]; then
    found=$(find "${kernel_dir}/kernel" -type f \
      \( -name "${dashed}.ko" -o -name "${dashed}.ko.gz" -o -name "${dashed}.ko.xz" -o -name "${dashed}.ko.zst" \
         -o -name "${underscored}.ko" -o -name "${underscored}.ko.gz" -o -name "${underscored}.ko.xz" -o -name "${underscored}.ko.zst" \) \
      -print -quit)
  fi
  [[ -n "$found" ]]
}

case "$mode" in
  has-stock)
    (( $# == 3 )) || {
      echo "has-stock requires a module name" >&2
      exit 2
    }
    stock_module_present "$3"
    ;;
  host)
    missing=()
    stock_module_present nvme_fabrics || missing+=(nvme-fabrics)
    stock_module_present nvme_tcp || missing+=(nvme-tcp)
    printf '%s\n' "${missing[*]}"
    ;;
  target)
    if stock_module_present nvmet_tcp; then
      printf '\n'
    else
      printf '%s\n' nvmet-tcp
    fi
    ;;
  *)
    echo "unsupported role: $mode" >&2
    exit 2
    ;;
esac
