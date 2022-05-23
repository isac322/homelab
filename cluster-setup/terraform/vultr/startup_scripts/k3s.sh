#!/usr/bin/env sh

set -ex

# disable swap
sed -i -E '/\Wswap\W/d' /etc/fstab
swapoff /swapfile
rm -f /swapfile

apt update
apt install -y apparmor

(umask 0022; mkdir -p /etc/rancher/k3s/)
(umask 0077; touch /etc/rancher/k3s/config.yaml)
#external_ip=$(ip -4 -o addr show enp7s0 | awk '{print $4}' | cut -d "/" -f 1)
cat << EOF | tee /etc/rancher/k3s/config.yaml > /dev/null
token: "${k3s_token}"
node-ip: "${node_id}"
node-external-ip: "${node_external_ip}"
bind-address: "${node_id}"
advertise-address: "${node_id}"
flannel-iface: "${interface_name}"
flannel-backend: host-gw
disable:
  - local-storage
  - traefik
EOF
curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL=stable INSTALL_K3S_SKIP_START=true sh -