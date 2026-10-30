# Ecclesia web app: quick start

This puts both Ecclesia web apps online for one church, on one server, in about 30 minutes:

- **Ecclesia Admin** (church office and finance), for example at `https://admin.yourchurch.org`
- **Ecclesia Connect** (members), for example at `https://members.yourchurch.org`

The Android, iPhone and Windows apps connect to these two addresses.

**Shortcut:** on a fresh Ubuntu 24.04 server, [`deploy/install.sh`](deploy/install.sh) does steps 2 to 4 for you, including HTTPS and nightly backups. For a free server, follow [deploy/ORACLE.md](deploy/ORACLE.md).

## 1. What you need

- A Linux server (VPS) with 2 GB RAM running Ubuntu 24.04, from any hosting provider.
- Two web addresses pointing at the server's IP address (DNS "A" records), such as `admin.yourchurch.org` and `members.yourchurch.org`.

## 2. Install Docker and Caddy on the server

Docker runs Ecclesia and its PostgreSQL database; Caddy provides HTTPS certificates automatically.

```bash
curl -fsSL https://get.docker.com | sudo sh
```

```bash
sudo apt-get install -y caddy unzip
```

On other Linux versions, install Caddy as described at https://caddyserver.com/docs/install.

## 3. Unpack Ecclesia and set it up

Copy the Ecclesia zip file to the server, then:

```bash
unzip Ecclesia-WebApp-1.0.zip -d ecclesia && cd ecclesia
```

```bash
cp .env.example .env
```

Edit `.env` (for example with `nano .env`) and set at least:

| Setting | What to put |
|---|---|
| `SECRET_KEY` | A long random value. Generate one with `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `POSTGRES_PASSWORD` | A strong database password |
| `ALLOWED_HOSTS` | Your two addresses, e.g. `admin.yourchurch.org,members.yourchurch.org` |
| `CSRF_TRUSTED_ORIGINS` | The same with `https://`, e.g. `https://admin.yourchurch.org,https://members.yourchurch.org` |
| `CHURCH_COUNTRY` | `KE` for Kenya (Kenya Shillings and Kenyan payroll), or your country code |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_EMAIL` | The first administrator login |

Start Ecclesia:

```bash
sudo docker compose up -d --build
```

The first start takes a few minutes. It creates the database, the chart of accounts, funds, roles and payroll items, and the administrator login.

## 4. Turn on HTTPS

Replace the contents of `/etc/caddy/Caddyfile` with your two addresses:

```
admin.yourchurch.org {
    reverse_proxy localhost:8000
}
members.yourchurch.org {
    reverse_proxy localhost:8001
}
```

```bash
sudo systemctl reload caddy
```

Open `https://admin.yourchurch.org` and sign in with the administrator login from `.env`.

## 5. First steps in Ecclesia Admin

1. **Church settings:** church name, address, currency, fiscal year and the bill approval limit.
2. **Settings → Users:** add logins for the treasurer, bookkeeper, secretary, pastors and media team, each with their role.
3. **Opening balances:** enter what each bank, M-Pesa and cash account holds today.
4. **Congregation → Members:** add members or import them from a spreadsheet, then induct them into groups and fellowships.
5. **A member's page → "Ecclesia Connect (members app)" card:** create a username and password so the member can sign in to Ecclesia Connect.

## 6. The phone and desktop apps

- **Android:** install `Ecclesia-Connect-1.0-android.apk` (or the Play Store version once published) and enter `members.yourchurch.org` when asked.
- **iPhone:** open `https://members.yourchurch.org` in Safari, tap Share, then *Add to Home Screen*.
- **Windows:** run `Ecclesia-Admin-1.0.0-win-x64.exe` and enter `admin.yourchurch.org` when asked.

The apps check that the address is the right Ecclesia app before connecting, and remember it afterwards.

## Updating, backups and help

- **Update to a new version:** unzip the new version over the old folder (keep your `.env`), then run `sudo docker compose up -d --build`.
- **Back up:** download a backup from *Settings → Backup* in Ecclesia Admin. For the whole database run `sudo docker compose exec db pg_dump -U ecclesia ecclesia > ecclesia-backup.sql`.
- **A demo server:** add `ECCLESIA_DEMO_MODE=1` to `.env` on a separate server to load the sample church with one-click demo logins. Never use demo mode for a real church.
- **More detail:** `README.md` covers configuration, cloud storage, roles, accounting and payroll.

Support: info@pizzatechnologies.co.ke · +254 747 354 677 (call or WhatsApp)
