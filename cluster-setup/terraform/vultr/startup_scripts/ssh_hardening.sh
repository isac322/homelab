#!/usr/bin/env sh

set -ex

rm -f /etc/ssh/ssh_host_*

ssh-keygen -t rsa -b 4096 -f /etc/ssh/ssh_host_rsa_key -N ""
ssh-keygen -t ed25519 -f /etc/ssh/ssh_host_ed25519_key -N ""

awk '$5 >= 3071' /etc/ssh/moduli | tee /etc/ssh/moduli.safe > /dev/null

mv /etc/ssh/moduli.safe /etc/ssh/moduli
sed -i 's/^\#HostKey \/etc\/ssh\/ssh_host_\(rsa\|ed25519\)_key$/HostKey \/etc\/ssh\/ssh_host_\1_key/g' /etc/ssh/sshd_config
cat << EOF | tee /etc/ssh/sshd_config.d/ssh-audit_hardening.conf > /dev/null

# Restrict key exchange, cipher, and MAC algorithms, as per sshaudit.com hardening guide.
KexAlgorithms curve25519-sha256,curve25519-sha256@libssh.org,diffie-hellman-group14-sha256,diffie-hellman-group16-sha512,diffie-hellman-group18-sha512,diffie-hellman-group-exchange-sha256
Ciphers chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr
MACs hmac-sha2-256-etm@openssh.com,hmac-sha2-512-etm@openssh.com,umac-128-etm@openssh.com
HostKeyAlgorithms ssh-ed25519,ssh-ed25519-cert-v01@openssh.com,sk-ssh-ed25519@openssh.com,sk-ssh-ed25519-cert-v01@openssh.com,rsa-sha2-256,rsa-sha2-512,rsa-sha2-256-cert-v01@openssh.com,rsa-sha2-512-cert-v01@openssh.com
EOF

cat << EOF | tee /etc/ssh/sshd_config.d/ssh_hardening.conf > /dev/null
PermitRootLogin no
StrictModes yes
MaxAuthTries 1

PubkeyAuthentication yes
PasswordAuthentication no
PermitEmptyPasswords no
EOF
