#!/usr/bin/env sh

set -ex

mkdir -p /etc/systemd/network

# create files with right permissions (640) to prevent other system users to read secrets
(
  umask 0027;
  touch \
    "/etc/systemd/network/${interface_name}.netdev" \
    "/etc/systemd/network/${interface_name}.network" \
    "/etc/systemd/network/wg-preshared.key" \
    "/etc/systemd/network/wg-private.key" \
    "/etc/systemd/network/wg-public.key"
)
chown root:systemd-network /etc/systemd/network/*

# create a pair of keys


cat <<EOF | tee /etc/systemd/network/wg-private.key > /dev/null
${private_key}
EOF
cat <<EOF | tee /etc/systemd/network/wg-public.key > /dev/null
${public_key}
EOF
cat <<EOF | tee /etc/systemd/network/wg-preshared.key > /dev/null
${preshared_key}
EOF


cat <<EOF | tee "/etc/systemd/network/${interface_name}.netdev" > /dev/null
[NetDev]
Name = ${interface_name}
Kind = wireguard
Description = ${interface_name} server ${subnet}

[WireGuard]
PrivateKeyFile = /etc/systemd/network/wg-private.key
ListenPort = ${port}

#[WireGuardPeer]
#PublicKey = <content of client's wg-public.key>
#AllowedIPs = 10.222.0.2/32
#PresharedKeyFile = /etc/systemd/network/wg-preshared.key
EOF

cat <<EOF | tee "/etc/systemd/network/${interface_name}.network" > /dev/null
[Match]
Name = ${interface_name}

[Network]
Address = ${ip}/32

[Route]
Gateway = ${ip}
Destination = ${subnet}
EOF

systemctl daemon-reload
systemctl reload-or-restart systemd-networkd