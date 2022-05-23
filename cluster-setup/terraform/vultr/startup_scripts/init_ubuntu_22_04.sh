#!/usr/bin/env sh

set -ex

apt purge snapd cron ufw -y
apt autoremove -y
apt install nftables -y
systemctl enable nftables.service

sed -i -E 's/^\s*#?\s*SystemMaxUse\s*=.*$/SystemMaxUse=500M/' /etc/systemd/journald.conf
systemctl daemon-reload

cp -r /root/.ssh /home/ubuntu
chown ubuntu:ubuntu /home/ubuntu/.ssh
