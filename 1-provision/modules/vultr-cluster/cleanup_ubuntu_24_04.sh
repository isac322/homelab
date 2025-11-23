#!/usr/bin/env sh

set -ex

apt-get purge --auto-remove --purge -y cron snapd ufw

sed -i -E 's/^\s*#?\s*SystemMaxUse\s*=.*$/SystemMaxUse=500M/' /etc/systemd/journald.conf
systemctl daemon-reload

cp -r /root/.ssh /home/ubuntu
chown ubuntu:ubuntu /home/ubuntu/.ssh
