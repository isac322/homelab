#!/usr/bin/env sh

set -ex

apt purge snapd cron -y
apt autoremove -y

sed -i -E '/\Wswap\W/d' /etc/fstab

sed -i -E 's/^\s*#?\s*SystemMaxUse\s*=.*$/SystemMaxUse=500M/' /etc/systemd/journald.conf
systemctl daemon-reload

cp -r /root/.ssh /home/ubuntu
chown ubuntu:ubuntu /home/ubuntu/.ssh
