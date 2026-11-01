# Host Ecclesia free on Render

Render runs the two Ecclesia apps and their PostgreSQL database for free. There is no server to look after: you sign up, open one link, fill in an administrator login and click Deploy. It takes about 20 minutes.

**What "free" means here**
- The apps **sleep after 15 minutes without visitors** and take about a minute to wake up for the next person.
- Both apps share **750 free hours a month** on Render. Normal church use fits, because sleeping time doesn't count.
- The free database holds **1 GB**, which is years of records for most churches, but **Render deletes free databases 30 days after they are created** unless you upgrade them to a paid plan. Upgrade before day 30 to keep your records (see *Keeping your data after 30 days* below).
- Free Render servers **forget uploaded files when they restart**, so receipts and sermon uploads need free file storage (Part 2). You can start without it and add it later.

## Part 1 (optional): File storage for receipts and sermons

Skip this to start straight away. Sermons can still be added as YouTube links, and administrators see a warning until storage is connected.

Cloudflare R2 includes 10 GB free each month (Cloudflare asks for a card to turn R2 on):

1. Sign in at **https://dash.cloudflare.com** → **R2 Object Storage** → **Create bucket**. Name it, for example `ecclesia-files`.
2. **R2 → Manage API tokens → Create API token** with **Object Read & Write** permission for that bucket.
3. Write down the **Access Key ID**, the **Secret Access Key**, and the **S3 endpoint**, which looks like `https://<account id>.r2.cloudflarestorage.com`.

## Part 2: Deploy on Render (10 minutes, plus about 10 minutes of building)

1. Go to **https://render.com** and sign up. Signing in with GitHub or Google is quickest. Render may place a temporary US$1 hold on a card to verify you.
2. Open this link: **https://render.com/deploy?repo=https://github.com/pizzatechies/churchapp**
3. Give the Blueprint a name, for example `ecclesia`. Render shows what it will create: the database **ecclesia-db** and the two apps **ecclesia-admin** and **ecclesia-members**, all on the **Free** plan.
4. Fill in the values Render asks for:

   | Setting | What to put |
   |---|---|
   | `ADMIN_USERNAME` | The administrator's login name, e.g. `admin` |
   | `ADMIN_PASSWORD` | A long password for that login |
   | `ADMIN_EMAIL` | The administrator's email |
   | `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Your values from Part 1, or leave them empty (type `none` if Render insists on a value) |

5. Click **Deploy Blueprint** (or **Apply**). Render creates the database and builds both apps; the first build takes about 10 minutes.
6. When all three show **Available** or **Live**, click **ecclesia-admin**. Its address is at the top of the page, for example **https://ecclesia-admin.onrender.com**. If the name was taken, Render adds a few letters; use the address it shows.

## Part 3: Open Ecclesia

1. Open the **ecclesia-admin** address and sign in with the username and password from Part 2.
2. Follow *First steps in Ecclesia Admin* in [QUICKSTART.md](../QUICKSTART.md): church settings, users and roles, bank and M-Pesa accounts, members and groups.
3. Your members use the **ecclesia-members** address, for example **https://ecclesia-members.onrender.com**:
   - **Android:** enter it in Ecclesia Connect.
   - **iPhone:** open it in Safari, tap Share, then *Add to Home Screen*.
   - **Windows:** enter the **ecclesia-admin** address in Ecclesia Admin.

**After a quiet spell the first visit takes about a minute.** The phone and Windows apps (version 1.1 and later) show *Waking up your church's server* and wait for up to two minutes, so there's nothing to do but keep them open. In a browser, the page simply loads a little slower.

## Good to know

- **Adding file storage later:** create the bucket and token as in Part 1. Then in Render open **ecclesia-admin → Environment**, set the four values below, and click **Save, rebuild, and deploy**. Do the same on **ecclesia-members**. The red "uploads are only kept until this server restarts" bar disappears once it works.

  | Key | Value |
  |---|---|
  | `S3_BUCKET` | the bucket name, e.g. `ecclesia-files` |
  | `S3_ENDPOINT_URL` | the S3 endpoint, e.g. `https://<account id>.r2.cloudflarestorage.com` (without the bucket name on the end) |
  | `S3_ACCESS_KEY_ID` | the token's Access Key ID |
  | `S3_SECRET_ACCESS_KEY` | the token's Secret Access Key |

  On **ecclesia-admin**, also make sure `GUNICORN_TIMEOUT` is `600`, so long sermon uploads aren't cut off.
- **Live M-Pesa gifts (optional):** in Ecclesia Admin open **Bank accounts**, add your Paybill as a bank account in the chart of accounts if it isn't there, then choose **Link account → M-Pesa Paybill or Till**. Ecclesia shows two addresses to register with Safaricom (Daraja → C2B → Register URL). To register them from inside Ecclesia instead, add `MPESA_CONSUMER_KEY` and `MPESA_CONSUMER_SECRET` from your Daraja app to **ecclesia-admin → Environment**. A free Render app sleeps when idle; Safaricom's first notice wakes it, and anything missed can still be uploaded from the M-Pesa portal statement.
- **Backups:** download a full backup regularly from **Administration → Backup** in Ecclesia Admin. It includes the books, members, groups and sermons, and saves to your computer.
- **Your own web address:** in Render, open a service → **Settings → Custom Domains**. Add the new address to `ALLOWED_HOSTS` and, with `https://` in front, to `CSRF_TRUSTED_ORIGINS` in that service's **Environment**.
- **Always on, no sleeping:** paid Render plans keep the apps awake. Use the Blueprint file [`render-paid.yaml`](render-paid.yaml) for that.

## Keeping your data after 30 days

Render's free database stops working 30 days after it is created, and Render deletes it after a short grace period. Before day 30:

1. In Render, open **ecclesia-db**.
2. Choose **Upgrade** (or **Change instance type**) and pick the smallest paid plan, which costs a few US dollars a month. Nothing else changes: the apps keep their address and all records stay.

Download a backup from **Administration → Backup** first, as a precaution. The database's page in Render shows when it expires; put a reminder in your calendar for a few days before.

## If something doesn't work

| Problem | What to do |
|---|---|
| A build fails | Open the service → **Events** or **Logs** and send the last lines to your Ecclesia contact |
| The admin app shows an error about the database | In Render, check that **ecclesia-db** is **Available**, and that it hasn't passed its 30 days |
| Signing in fails | Check `ADMIN_USERNAME` and `ADMIN_PASSWORD` in **ecclesia-admin → Environment**. They create the login only if it doesn't exist yet |
| The page takes a long time | It was asleep: wait up to a minute |

Need help? info@pizzatechnologies.co.ke · +254 747 354 677 (call or WhatsApp)
