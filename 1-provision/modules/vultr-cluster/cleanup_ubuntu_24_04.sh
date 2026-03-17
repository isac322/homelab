#!/usr/bin/env sh

set -ex

apt-get purge --auto-remove --purge -y cron snapd ufw

sed -i -E 's/^\s*#?\s*SystemMaxUse\s*=.*$/SystemMaxUse=500M/' /etc/systemd/journald.conf
systemctl daemon-reload

echo 'fs.inotify.max_user_instances=1024' > /etc/sysctl.d/99-inotify.conf
sysctl -w fs.inotify.max_user_instances=1024

cp -r /root/.ssh /home/ubuntu
chown ubuntu:ubuntu /home/ubuntu/.ssh
