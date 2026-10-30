# Host Ecclesia free on Oracle Cloud

Oracle Cloud's "Always Free" plan includes a Linux server that is large enough for Ecclesia: both apps, the PostgreSQL database and the sermon files. The setup script in this folder, [`install.sh`](install.sh), installs everything by itself while the server starts. You only click through Oracle's website.

It takes about 30 minutes. You need an email address and a debit or credit card; Oracle uses the card to verify you and does not charge for Always Free resources.

## 1. Create an Oracle Cloud account

1. Go to https://www.oracle.com/cloud/free/ and choose **Start for free**.
2. Fill in your details and verify your card.
3. **Home region:** choose one close to your church, for example *South Africa Central (Johannesburg)*. Always Free servers can only be created in your home region, and it can't be changed later.

Wait for the email saying your account is ready (sometimes up to an hour).

## 2. Prepare the setup script

Open [`install.sh`](install.sh) in a text editor (Notepad is fine) and change the lines at the top:

| Line | What to put |
|---|---|
| `CHURCH_NAME` | Your church's name |
| `CHURCH_COUNTRY` | `KE` for Kenya, or your two-letter country code |
| `ADMIN_USERNAME` | The administrator's login name |
| `ADMIN_PASSWORD` | **Change this.** At least 8 characters: letters, numbers and `. _ ! @ % + = , : -` |
| `ADMIN_DOMAIN`, `MEMBERS_DOMAIN` | Leave empty to get free addresses. If you own a domain, put e.g. `admin.yourchurch.org` and `members.yourchurch.org`, and point both at the server's IP address once you know it |
| `DEMO` | `'yes'` only for a public demo server with the sample church |

Keep the single quotes around each value.

## 3. Create the server

In the Oracle Cloud console, open the menu (☰) → **Compute** → **Instances** → **Create instance**.

1. **Name:** `ecclesia`.
2. **Image and shape** → **Edit**:
   - **Change image** → **Ubuntu** → **Canonical Ubuntu 24.04** → Select.
   - **Change shape** → **Ampere** → **VM.Standard.A1.Flex**, with **2 OCPUs** and **12 GB memory** (it is labelled *Always Free-eligible*) → Select.
3. **Networking:** keep *Create new virtual cloud network* and *Create new public subnet*, and make sure **Assign a public IPv4 address** is on.
4. **Add SSH keys:** choose **Generate a key pair for me** and click **Save private key**. Keep this file safe: it is how you (or a technician) can log in to the server.
5. **Boot volume:** leave the default.
6. Open **Show advanced options** → **Management** → **Initialization script** → **Paste cloud-init script**, and paste the whole of your edited `install.sh`.
7. Click **Create**.

If Oracle says **"Out of capacity"**, try again later, choose another *availability domain* in the placement section, or use 1 OCPU and 6 GB memory.

## 4. Open the web ports

Oracle blocks web traffic until you allow it. The setup script opens the server's own firewall, but you also need to open Oracle's.

1. On the instance's page, under **Primary VNIC**, click the **Subnet** link.
2. Open **Security** (or **Security Lists**) → **Default Security List for ...** → **Add Ingress Rules**.
3. Add a rule: **Source CIDR** `0.0.0.0/0`, **IP Protocol** TCP, **Destination Port Range** `80`. Save.
4. Add a second rule the same way with port `443`.

## 5. Open Ecclesia

Wait 10 to 15 minutes after creating the server. Then copy the **Public IP address** from the instance's page and open `http://<that IP>/` in a browser. It shows your two addresses, which look like this for the IP 141.147.10.20:

- **Ecclesia Admin** (church office): `https://admin.141-147-10-20.sslip.io`
- **Ecclesia Connect** (members): `https://members.141-147-10-20.sslip.io`

Open the Admin address and sign in with the username and password from the script. Then follow *First steps in Ecclesia Admin* in [QUICKSTART.md](../QUICKSTART.md).

**The apps:** on Android, enter the members address in Ecclesia Connect. On Windows, enter the admin address in Ecclesia Admin. On iPhone, open the members address in Safari, tap Share, then *Add to Home Screen*.

## Good to know

- **Backups:** the server saves a copy of the database every night at 02:30 and keeps 14 days of them in `/opt/ecclesia-backups`. Also download a backup from *Settings → Backup* now and then and keep it somewhere else.
- **Updates:** log in to the server and run `cd /opt/ecclesia && sudo git pull && sudo docker compose up -d --build`.
- **Idle servers:** Oracle can stop Always Free servers it considers idle. If that happens, start it again from the console; Ecclesia starts by itself. Upgrading the account to *Pay As You Go* stops this, and Always Free resources stay free.
- **Free addresses:** the `sslip.io` addresses are a free public service that turns the server's IP into a web address. For a permanent setup, a domain of your own (for example a `.co.ke` or `.org`) looks more professional and doesn't change if the server's IP does.

## If something doesn't work

- **The page doesn't open after 20 minutes:** check both ingress rules in step 4.
- **See what the setup did:** log in with your SSH key (`ssh -i <your key file> ubuntu@<server IP>`), then run `sudo tail -50 /var/log/ecclesia-install.log`. A wrong password format, for example, is reported there.
- **Run the setup again** (it keeps an existing database and settings): `sudo bash /var/lib/cloud/instance/user-data.txt`

Need help? info@pizzatechnologies.co.ke · +254 747 354 677 (call or WhatsApp)
