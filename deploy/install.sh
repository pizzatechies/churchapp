#!/bin/bash
# Ecclesia: one-step server setup for Ubuntu 24.04 (Oracle Cloud Always Free, or any VPS).
#
# Paste this whole file into "Initialization script" when you create the server
# (see deploy/ORACLE.md), or run it on a fresh server with:  sudo bash install.sh
#
# It installs Docker and Caddy, downloads Ecclesia, starts both apps with their own
# PostgreSQL database, turns on HTTPS, opens the firewall and schedules nightly backups.
# Progress is logged to /var/log/ecclesia-install.log; when it finishes, the addresses
# are in /root/ecclesia-READY.txt and at http://<server IP>/.

# ---- Change these before you use the script ------------------------------------
# Keep the single quotes around each value, and don't use ' inside a value.
CHURCH_NAME='LifeSource Church'
CHURCH_COUNTRY='KE'                     # KE = Kenya (KSh, Kenyan payroll). Two-letter code.
ADMIN_USERNAME='admin'
# Change this! At least 8 characters: letters, numbers and . _ ! @ % + = , : - (no spaces).
ADMIN_PASSWORD='Choose-A-Long-Password'
ADMIN_EMAIL='pizzatechies@gmail.com'
# Your own web addresses, if you have them (point both at the server's IP first).
# Leave empty to use free addresses made from the server's IP, e.g. admin.203-0-113-5.sslip.io
ADMIN_DOMAIN=''
MEMBERS_DOMAIN=''
# DEMO='yes' loads the sample church with one-click demo logins and resets it every
# night, for showing Ecclesia to visitors. Never use it for a real church.
DEMO='no'
REPO='https://github.com/pizzatechies/churchapp.git'
# ---------------------------------------------------------------------------------

set -euo pipefail
exec > >(tee -a /var/log/ecclesia-install.log) 2>&1
echo "=== Ecclesia install started $(date -u) ==="
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"
APP_DIR=/opt/ecclesia
BACKUP_DIR=/opt/ecclesia-backups
APT="apt-get -o DPkg::Lock::Timeout=900 -y -q"

if ! [[ "$ADMIN_PASSWORD" =~ ^[A-Za-z0-9._!@%+=,:-]{8,}$ ]]; then
  echo "ADMIN_PASSWORD must be at least 8 characters, using only letters, numbers and . _ ! @ % + = , : -" >&2
  exit 1
fi

# Small servers (such as Oracle's free 1 GB VM.Standard.E2.1.Micro) get swap space
# and one worker per app, so the database and both apps fit in memory.
MEM_MB=$(awk '/^MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
WORKERS=3
if [ "$MEM_MB" -lt 2000 ]; then
  WORKERS=1
  if ! swapon --show=NAME --noheadings | grep -q .; then
    echo "--- Adding 2 GB of swap space (this server has ${MEM_MB} MB of memory)"
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
fi

echo "--- Installing Docker, Caddy and Git"
$APT update
$APT install ca-certificates curl git openssl caddy
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "--- Opening ports 80 and 443"
# Oracle's Ubuntu images block everything but SSH in iptables, as well as in the cloud firewall.
if iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
  for port in 443 80; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport "$port" -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then netfilter-persistent save; fi
fi
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp
  ufw allow 443/tcp
fi

echo "--- Working out the web addresses"
IP=$(curl -fsS --max-time 15 https://api.ipify.org || curl -fsS --max-time 15 https://ifconfig.me)
if [ -z "$ADMIN_DOMAIN" ]; then ADMIN_DOMAIN="admin.${IP//./-}.sslip.io"; fi
if [ -z "$MEMBERS_DOMAIN" ]; then MEMBERS_DOMAIN="members.${IP//./-}.sslip.io"; fi
echo "Server IP: $IP"
echo "Ecclesia Admin:   https://$ADMIN_DOMAIN"
echo "Ecclesia Connect: https://$MEMBERS_DOMAIN"

echo "--- Downloading Ecclesia"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

FIRST_INSTALL=no
if [ ! -f .env ]; then
  FIRST_INSTALL=yes
  echo "--- Writing settings (.env)"
  umask 077
  cat > .env <<EOF
SECRET_KEY=$(openssl rand -hex 32)
DEBUG=0
ALLOWED_HOSTS=$ADMIN_DOMAIN,$MEMBERS_DOMAIN,localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=https://$ADMIN_DOMAIN,https://$MEMBERS_DOMAIN
POSTGRES_DB=ecclesia
POSTGRES_USER=ecclesia
POSTGRES_PASSWORD=$(openssl rand -hex 24)
CHURCH_COUNTRY=$CHURCH_COUNTRY
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
ADMIN_EMAIL=$ADMIN_EMAIL
TIME_ZONE=Africa/Nairobi
SECURE_COOKIES=1
WEB_CONCURRENCY=$WORKERS
EOF
  if [ "$DEMO" = "yes" ]; then
    echo "ECCLESIA_DEMO_MODE=1" >> .env
  fi
  umask 022
fi

echo "--- Building and starting Ecclesia (this takes a few minutes the first time)"
docker compose up -d --build

echo "--- Waiting for Ecclesia to answer"
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8000/healthz/ >/dev/null 2>&1 && curl -fsS http://127.0.0.1:8001/healthz/ >/dev/null 2>&1; then
    break
  fi
  sleep 5
done
curl -fsS http://127.0.0.1:8000/healthz/ && echo

if [ "$FIRST_INSTALL" = "yes" ] && [ "$DEMO" != "yes" ]; then
  docker compose exec -T admin python manage.py setup_church --name "$CHURCH_NAME"
fi

echo "--- Turning on HTTPS"
cat > /etc/caddy/Caddyfile <<EOF
$ADMIN_DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:8000
}

$MEMBERS_DOMAIN {
	encode gzip
	reverse_proxy 127.0.0.1:8001
}

http://$IP {
	respond "Ecclesia is running.
Office app (Ecclesia Admin):    https://$ADMIN_DOMAIN
Members app (Ecclesia Connect): https://$MEMBERS_DOMAIN
" 200
}
EOF
systemctl enable caddy
systemctl restart caddy

echo "--- Scheduling nightly backups"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cat > /etc/cron.d/ecclesia <<EOF
# Nightly database backup, kept for 14 days.
30 2 * * * root cd $APP_DIR && docker compose exec -T db pg_dump -U ecclesia ecclesia | gzip > $BACKUP_DIR/ecclesia-\$(date +\%F).sql.gz && find $BACKUP_DIR -name '*.sql.gz' -mtime +14 -delete
EOF
if [ "$DEMO" = "yes" ]; then
  echo "0 3 * * * root cd $APP_DIR && docker compose exec -T admin python manage.py reset_demo > /dev/null" >> /etc/cron.d/ecclesia
fi

cat > /root/ecclesia-READY.txt <<EOF
Ecclesia is installed.

Ecclesia Admin (church office):  https://$ADMIN_DOMAIN
Ecclesia Connect (members):      https://$MEMBERS_DOMAIN
Administrator login:             $ADMIN_USERNAME (the password you chose in the install script)

In the apps, enter $ADMIN_DOMAIN (Windows app) or $MEMBERS_DOMAIN (Android app).
Settings: $APP_DIR/.env   Backups: $BACKUP_DIR   Log: /var/log/ecclesia-install.log
Update Ecclesia later with:  cd $APP_DIR && sudo git pull && sudo docker compose up -d --build
EOF
cat /root/ecclesia-READY.txt
echo "=== Ecclesia install finished $(date -u) ==="
