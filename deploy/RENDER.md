# Host Ecclesia free on Render

Render runs the two Ecclesia apps for free, and Neon provides a free PostgreSQL database. There is no server to look after: you sign up for two websites, paste one connection string and click Deploy. It takes about 30 minutes.

**What "free" means here**
- The apps **sleep after 15 minutes without visitors** and take about a minute to wake up for the next person.
- Both apps share **750 free hours a month** on Render. Normal church use fits, because sleeping time doesn't count.
- The free database holds **1 GB**, which is years of records for most churches.
- Free Render servers **forget uploaded files when they restart**, so receipts and sermon uploads need free file storage (Part 2). You can start without it and add it later.

## Part 1: Create the database on Neon (5 minutes)

1. Go to **https://neon.tech** and click **Sign up**. Signing in with Google or GitHub is quickest. No card is needed.
2. Create a project:
   - **Project name:** `ecclesia`
   - **Region:** **AWS Europe Central 1 (Frankfurt)**, the same region as the apps
   - Leave the rest as it is and click **Create project**.
3. On the project's page, click **Connect**.
   - Turn **Connection pooling** **off**.
   - Copy the **connection string**. It starts with `postgresql://` and contains the database password, so keep it private.

## Part 2 (optional): File storage for receipts and sermons

Skip this to start straight away. Sermons can still be added as YouTube links, and administrators see a warning until storage is connected.

Cloudflare R2 includes 10 GB free each month (Cloudflare asks for a card to turn R2 on):

1. Sign in at **https://dash.cloudflare.com** → **R2 Object Storage** → **Create bucket**. Name it, for example `ecclesia-files`.
2. **R2 → Manage API tokens → Create API token** with **Object Read & Write** permission for that bucket.
3. Write down the **Access Key ID**, the **Secret Access Key**, and the **S3 endpoint**, which looks like `https://<account id>.r2.cloudflarestorage.com`.

## Part 3: Deploy on Render (10 minutes, plus about 10 minutes of building)

1. Go to **https://render.com** and sign up. Signing in with GitHub or Google is quickest. Render may place a temporary US$1 hold on a card to verify you.
2. Open this link: **https://render.com/deploy?repo=https://github.com/pizzatechies/churchapp**
3. Give the Blueprint a name, for example `ecclesia`. Render shows the two services it will create, **ecclesia-admin** and **ecclesia-members**, both on the **Free** plan.
4. Fill in the values Render asks for:

   | Setting | What to put |
   |---|---|
   | `DATABASE_URL` | The Neon connection string from Part 1 |
   | `ADMIN_USERNAME` | The administrator's login name, e.g. `admin` |
   | `ADMIN_PASSWORD` | A long password for that login |
   | `ADMIN_EMAIL` | The administrator's email |
   | `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Your values from Part 2, or leave them empty (type `none` if Render insists on a value) |

5. Click **Deploy Blueprint** (or **Apply**). Render builds both apps; the first build takes about 10 minutes.
6. When both services show **Live**, click **ecclesia-admin**. Its address is at the top of the page, for example **https://ecclesia-admin.onrender.com**. If the name was taken, Render adds a few letters; use the address it shows.

## Part 4: Open Ecclesia

1. Open the **ecclesia-admin** address and sign in with the username and password from Part 3.
2. Follow *First steps in Ecclesia Admin* in [QUICKSTART.md](../QUICKSTART.md): church settings, users and roles, bank and M-Pesa accounts, members and groups.
3. Your members use the **ecclesia-members** address, for example **https://ecclesia-members.onrender.com**:
   - **Android:** enter it in Ecclesia Connect.
   - **iPhone:** open it in Safari, tap Share, then *Add to Home Screen*.
   - **Windows:** enter the **ecclesia-admin** address in Ecclesia Admin.

**After a quiet spell the first visit takes about a minute.** The phone and Windows apps (version 1.1 and later) show *Waking up your church's server* and wait for up to two minutes, so there's nothing to do but keep them open. In a browser, the page simply loads a little slower.

## Good to know

- **Adding file storage later:** in Render, open **ecclesia-admin → Environment**, fill in the four `S3_` values and save. Then do the same on **ecclesia-members**.
- **Backups:** download a full backup regularly from **Administration → Backup** in Ecclesia Admin. Neon also keeps a short restore history.
- **Your own web address:** in Render, open a service → **Settings → Custom Domains**. Add the new address to `ALLOWED_HOSTS` and, with `https://` in front, to `CSRF_TRUSTED_ORIGINS` in that service's **Environment**.
- **Always on, no sleeping:** paid Render plans keep the apps awake. Use the Blueprint file [`render-paid.yaml`](render-paid.yaml) for that.

## If something doesn't work

| Problem | What to do |
|---|---|
| A build fails | Open the service → **Events** or **Logs** and send the last lines to your Ecclesia contact |
| The admin app shows an error about the database | Check `DATABASE_URL` in **ecclesia-admin → Environment**: it must be the full Neon string, with connection pooling off |
| Signing in fails | Check `ADMIN_USERNAME` and `ADMIN_PASSWORD` in **ecclesia-admin → Environment**. They create the login only if it doesn't exist yet |
| The page takes a long time | It was asleep: wait up to a minute |

Need help? info@pizzatechnologies.co.ke · +254 747 354 677 (call or WhatsApp)
