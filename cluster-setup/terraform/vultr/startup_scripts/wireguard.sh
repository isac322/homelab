#!/usr/bin/env sh

set -ex

mkdir -p /etc/systemd/network

# create files with right permissions (640) to prevent other system users to read secrets
(
  umask 0027;
  touch \
    "/etc/systemd/network/${interface_name}.netdev" \
    "/etc/systemd/network/${interface_name}.network"
)
chown root:systemd-network /etc/systemd/network/*

# create a pair of keys


cat <<EOF | tee "/etc/systemd/network/${interface_name}.netdev" > /dev/null
${networkd_netdev}
EOF

cat <<EOF | tee "/etc/systemd/network/${interface_name}.network" > /dev/null
${networkd_network}
EOF

systemctl daemon-reload
systemctl restart systemd-networkd