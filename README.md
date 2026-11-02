<p align="center">
  <img src="static/brand/ecclesia-logo.svg" alt="Ecclesia" width="96">
</p>

<h1 align="center">Ecclesia</h1>
<p align="center"><strong>Church management, membership &amp; finance — a product of Pizza Technologies</strong></p>

Ecclesia gives a church everything it needs to run its finances properly and keep its people connected. It comes as **two apps on one PostgreSQL database**:

| App | Who uses it | What it does |
|---|---|---|
| **Ecclesia Admin** | Pastors, treasurer, bookkeeper, church secretary, finance committee, offering counters, media team | Full double-entry fund accounting, giving, expenses, payroll, budgets, assets, reports, **plus** the membership register, groups & fellowships, inductions and sermon uploads |
| **Ecclesia Connect** | Church members | Fellowships, church groups, sermons, the member's own profile, **their own giving and statements**, and (when the church switches it on) **a summary of the church's finances for accountability**. No donor lists, payroll or data entry exist in this app |

It defaults to **Kenya** (Kenya Shillings, M-Pesa, PAYE/NSSF/SHIF/Housing Levy payroll, Africa/Nairobi time) and works for churches anywhere: pick a country on setup and change the currency, fiscal year, payroll rules and wording in *Church settings*.

<p align="center">
  <img src="docs/screenshots/admin-dashboard.png" alt="Ecclesia Admin dashboard" width="49%">
  <img src="docs/screenshots/members-app-home.png" alt="Ecclesia Connect home" width="49%">
</p>

---

## Contents

- [Features](#features)
- [Why Django + PostgreSQL](#why-django--postgresql)
- [Try it locally](#try-it-locally)
- [Deploying](#deploying)
- [Phone and desktop apps](#phone-and-desktop-apps)
- [Website and public demo](#website-and-public-demo)
- [Configuration](#configuration)
- [Roles and permissions](#roles-and-permissions)
- [How the accounting works](#how-the-accounting-works)
- [Payroll: Kenya and other countries](#payroll-kenya-and-other-countries)
- [Backups](#backups)
- [Development](#development)

---

## Features

### Congregation (Admin app)
- **Membership register**: member numbers, titles, gender, date of birth, marital status, contacts, residence/estate, county, occupation, ID, baptism, membership status (visitor → attender → member, inactive, transferred, deceased), emergency contact and private office notes. CSV import and export.
- **Gender-sensitive by design**: gender is recorded with a *Prefer not to say* option; groups can be **Women only**, **Men only** or open to everyone, with optional age limits (e.g. Youth 18–35), and these rules are enforced at induction. Membership statistics break down every age group and every group by gender. Avatars and charts never use stereotyped gender colours.
- **Groups & fellowships**: fellowships, ministries/departments, home cells, choirs & worship teams, classes and committees with meeting day/time/place, leaders (chair, assistant, secretary, treasurer, patron).
- **Induction**: induct one member from their profile or many at once from the group page; the system lists only eligible people and explains any refusal. Members' **requests to join** from the members app arrive in a queue for approval.
- **Sermons**: upload audio, video and notes/slides, or link YouTube/Vimeo/Facebook; publish to the members app. Media streams with seeking support (HTTP range requests).
- **Members app logins**: create a member's login from their profile; staff logins and member logins are kept apart.

### Ecclesia Connect (Members app)
- Home: your groups and meeting times, suggested fellowships you're eligible for, latest sermons.
- Browse all groups, see leaders and meeting details, **request to join** (gender/age rules respected), withdraw a request.
- Fellow-member lists are visible only to people in that group.
- Sermons: search, filter by series, listen/watch in the app, download notes.
- My profile: update contact details and password (name, gender and office notes are managed by the church office).
- **My giving**: the member's own gifts (once the offering is posted), giving by fund and month, pledge progress, last year's total, and a printable yearly giving statement. Members see only their own records; the church office links each member to their giving record (one by one or in bulk, with matches by email and phone suggested).
- **Church finances** (for financial accountability): income by category, spending by area, monthly income against spending, progress against the approved budget, fund balances, campaign progress and the controls that protect the money (approval limits, two-person approvals, bank reconciliations, closed periods). Totals only: it never shows who gave what, and all staff costs appear as one "Staff & personnel" figure so nobody's pay can be worked out.
- Both are switched on or off in **Church settings → Members app**, where the church also chooses how current the figures are: up to the end of last month (default), up to the date the books are closed through, or up to today.
- Mobile-first with a bottom tab bar; works as a website on any phone.

### Finance (Admin app)
- **Double-entry fund accounting**: chart of accounts designed for churches, funds (General, Building, Missions, Benevolence, Youth...) with donor-restriction classes, and every journal entry balanced *within each fund*.
- **Giving**: offering/deposit batches with count-sheet control totals and two-counter sign-off, fast entry by envelope number, cash, cheque, card, bank transfer and **M-Pesa** (with transaction codes), donors, pledges and building campaigns, year-end contribution statements (print/PDF/CSV), donor CSV import.
- **Expenses**: bills, reimbursements and payment requests with receipts attached, an approval limit, **segregation of duties** (nobody approves their own request), partial payments split exactly across funds, voids, duplicates for recurring bills.
- **Payroll**: salaried and hourly staff, configurable earnings/deductions/employer contributions, progressive tax bands with relief, monthly caps and minimums, pre-tax deductions, pay slips with year-to-date figures, posting to the ledger and remittance tracking.
- **Banking**: bank/cash/M-Pesa/credit-card accounts, transfers, interfund transfers, other income, **bank reconciliation** with live difference checking.
- **Linked bank accounts (bank feeds)**: link any bank or cash account from *Bank accounts → Link account*, in one of two ways:
  - **Statement upload, any bank**: CSV or OFX from Equity, KCB, Co-op, NCBA, Absa, Stanbic, the M-Pesa business portal and others. The header row and columns are found automatically, and re-uploading or overlapping statements never duplicates a line.
  - **Live M-Pesa Paybill or Till**: Safaricom's Daraja C2B API sends each payment the moment it arrives. Gifts go into the day's open offering batch, matched to the giver by the envelope number they type as the account number (or their phone), and to a fund by a code such as `BLD`. The batch is still checked and posted by the finance team.

    **Setting up live M-Pesa** (*Bank accounts → Add M-Pesa account*, then *Link account*). The link page is a four-step checklist:
    1. *Linked*: payments are recorded in the M-Pesa account. Keep the Paybill as its own account rather than the bank current account, so the bank statement still matches; a live link on a bank account can be moved in one click while it has no payments.
    2. *Payment address works*: Ecclesia calls its own confirmation address over the internet, as Safaricom will.
    3. *Registered with Safaricom*: enter the consumer key and secret of the church's app on developer.safaricom.co.ke (used once, never stored), for the live Paybill or the sandbox. Or register the two addresses on the Daraja portal and click *Mark as registered*. **Nothing arrives until this step is done.** For a Till (Buy Goods), use the store/head-office number Safaricom gave you.
    4. *Payments arriving*: shows the last payment; in the sandbox, *Simulate* asks Safaricom for a test payment.

    On Render's free plan the admin app sleeps after 15 minutes and Safaricom gives up on a sleeping server, so live payments are only reliable on an always-on plan. Upload the M-Pesa portal statement to catch anything missed; nothing is counted twice.
  
  Every line is matched automatically to entries already in the books when there's exactly one candidate. The rest wait in a review list where you match, record (gift, other income, or spending such as bank charges, with a suggested category) or ignore them. Reconciliation can then tick everything the bank feed confirms in one click, and each uploaded statement's closing balance is compared with the books. Linking is read-only: Ecclesia never holds online-banking passwords and can't move money.
- **Budgets**: monthly budget grid per fund, seeded from last year's actuals, with approval.
- **Fixed assets**: register, straight-line depreciation (including assets migrated with prior depreciation), disposal with automatic gain/loss.
- **Controls**: role-based access, period close (lock date), complete audit trail of every change, protected attachments, one-click JSON backup.
- **17 reports** with print/PDF and CSV export: statement of financial position, statement of activities (with prior-year comparison), functional expenses, fund activity, cash receipts & disbursements, budget vs actual, income & expenses by month, giving summary, giving by donor, lapsed donors, unpaid bills (aging), payments by payee, year-end tax-form payees, payroll summary, payroll liabilities, trial balance, general ledger.

<p align="center">
  <img src="docs/screenshots/membership-summary.png" alt="Membership summary by gender and age" width="49%">
  <img src="docs/screenshots/kenyan-payslip.png" alt="Kenyan pay slip" width="49%">
</p>

---

## Many churches on one server: the platform console

One Ecclesia server hosts many churches. **Each church has its own PostgreSQL schema**, so one church's members, gifts and books can never appear in another's, and each church has its own logins.

| Address | Who | What |
|---|---|---|
| `<admin app>/platform/` | Pizza Technologies' super admins | Onboard churches, plans, payments, usage, suspend/reactivate |
| `<admin app>/church/<name>/` | That church's staff | Ecclesia Admin for that church |
| `<members app>/church/<name>/` | That church's members | Ecclesia Connect for that church |
| `<admin app>/` and `<members app>/` | The church marked "served at the main addresses" | Keeps apps and bookmarks from before multi-church working |

**Onboarding a church** (Platform console → *Onboard a church*): name, web address name, country, plan (Seed KSh 10,000 · Harvest KSh 20,000 · Kingdom KSh 30,000 a month; yearly = 10 months' price), trial length, contact, and the first administrator's username and email. Ecclesia creates the church's schema with the default chart of accounts for its country, creates the administrator, and shows a **temporary password once**. The administrator must choose their own password at first sign-in.

**Monitoring:** the console lists every church with its plan, status (trial, active, overdue, suspended), paid-up date, members and staff against the plan's limits, storage, and last activity; plus monthly recurring revenue and money collected. It shows **counts only, never names or amounts from a church's books**. Record payments (M-Pesa code, months paid) on a church's page to extend its paid-up date; churches see a reminder a week before and when overdue, and their administrators see their plan, usage and payments under *Administration → Subscription*.

**Plan limits** are enforced where records are added: members (Seed 300, Harvest 1,000) and staff logins (Seed 5, Harvest 15); Kingdom is unlimited and can add the church's own web addresses. Edit prices and limits under *Plans*.

**The first super admin** is created on start from `PLATFORM_ADMIN_USERNAME` / `PLATFORM_ADMIN_PASSWORD` / `PLATFORM_ADMIN_EMAIL` (or, if those aren't set, the `ADMIN_*` values). Add more under *Team*.

**Upgrading a single-church server:** on the first start of this version, the existing church is moved, in one transaction, into its own schema (`/church/<name>/`) and marked as served at the main addresses, so nothing changes for its staff, members or apps.

## Passwords, profiles and "Forgot password"

- **Everyone has their own password**: platform super admins, each church's administrators and staff, and members.
- **Where are the passwords?** They are never stored. Django keeps only a salted one-way hash (PBKDF2), so nobody, including administrators and Pizza Technologies, can read anyone's password. People can only *set* a new one:

  | Who | Sets or resets it where |
  |---|---|
  | Anyone, for themselves | *My profile → Change password* (staff), *Me → Change password* (members), *My account* (platform) |
  | Anyone who forgot it | *Forgot password?* on the sign-in page: a one-day link to the email on their login |
  | A church's staff | Their administrator: *Users & roles → the person → new password* |
  | A church's members | The church office: *Members → the member → Members app login* |
  | A church's administrator | The platform console: *the church → Administrators → New password* |

- A password chosen by someone else is **temporary**: the person must choose their own at first sign-in.
- **Profiles:** staff edit their name, email and phone under *My profile*; members edit their contact details under *Me*.
- **Sign-in protection:** after 5 wrong passwords for a login, sign-in pauses for 15 minutes (`LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`). Reset requests are limited per address and never reveal whether an email has a login.
- **Email for "Forgot password"** needs an SMTP service. Set `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` (for Gmail: `smtp.gmail.com`, port 587, and an app password from your Google account). Until then the page tells people to ask their administrator.

## Why Django + PostgreSQL

Money software has to be correct first. The backend is **Django (Python)** on **PostgreSQL**:

- **PostgreSQL** stores amounts as exact `numeric` values (no floating-point rounding), enforces constraints, and gives row-level locking so two people posting at once can't corrupt a batch.
- **Every request runs in a database transaction**, and every posting goes through one service that validates the double-entry rules — a failure part-way can never leave half-posted books.
- **Django** brings mature, secure foundations: authentication, CSRF/XSS/clickjacking protection, migrations and an admin, maintained since 2005 and used by organisations of every size.
- Two apps, one codebase: both apps share the same models and database but have **separate URL configurations, templates, logins and session cookies**, so the members app physically contains no finance-office code paths: its only money pages are a member's own giving and the church's summary totals.

---

## Try it locally

You need **Python 3.12+** and **PostgreSQL 14+**.

```bash
createuser --createdb church --pwprompt   # password: church
createdb --owner church church_finance
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
python manage.py migrate
```

Load a sample Nairobi church (about two years of data: offerings, bills, payroll, 215 members, 19 groups, sermons):

```bash
python manage.py load_demo_data
```

Or start clean with your own church and an administrator login:

```bash
python manage.py setup_church --country KE --name "Your Church" --admin-username admin --admin-password "a-long-password"
```

Run the two apps (in two terminals):

```bash
python manage.py runserver 8000
```

```bash
DJANGO_SETTINGS_MODULE=config.settings_portal python manage.py runserver 8001
```

- **Ecclesia Admin**: http://localhost:8000 — demo logins `admin`, `treasurer`, `bookkeeper`, `committee`, `counter`, `pastor`, `secretary`, `media` (password `ChurchDemo-2026`).
- **Ecclesia Connect**: http://localhost:8001 — the demo prints ten member logins (same password).

By default the app connects to `postgres://church:church@localhost:5432/church_finance`; set `DATABASE_URL` to use another database.

---

## Deploying

For a step-by-step setup on one server, with HTTPS and the first steps in the app, follow [QUICKSTART.md](QUICKSTART.md).

### Option A — one server with Docker Compose (recommended)

A small VPS (2 GB RAM) runs everything: PostgreSQL, the admin app and the members app.

```bash
cp .env.example .env    # set SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, ADMIN_* ...
```

```bash
docker compose up -d --build
```

The admin app listens on port **8000** and the members app on **8001**. Put a reverse proxy with HTTPS in front, for example with Caddy:

```
admin.yourchurch.org {
    reverse_proxy localhost:8000
}
members.yourchurch.org {
    reverse_proxy localhost:8001
}
```

The admin container applies database migrations and creates the default accounts, funds, roles and payroll items on every start (it only fills in what is missing). Uploaded receipts and sermons live in the shared `media` volume.

### Free hosting on Oracle Cloud

Oracle Cloud's Always Free plan includes a server large enough for Ecclesia. [deploy/ORACLE.md](deploy/ORACLE.md) walks through it: paste [`deploy/install.sh`](deploy/install.sh) in while creating the server and it installs both apps, the database, HTTPS (with free addresses if you have no domain) and nightly backups.

### Option B — managed cloud (Render), free

[`render.yaml`](render.yaml) is a Render Blueprint for the free plan: both apps as free web services with Render's free PostgreSQL database. Render deletes free databases after 30 days unless they are upgraded, so upgrade it before then. [deploy/RENDER.md](deploy/RENDER.md) walks through it. Free services sleep after 15 minutes without visitors and forget local files when they restart, so set the `S3_*` variables to keep uploads in an S3-compatible bucket (Cloudflare R2, AWS S3, DigitalOcean Spaces, Backblaze B2). Until then, administrators see a warning. Files stay private: the apps hand out signed links that expire after an hour. For always-on paid plans with Render's own database, use [`deploy/render-paid.yaml`](deploy/render-paid.yaml).

The same Docker image runs on any container platform (Fly.io, Railway, Google Cloud Run, Azure, AWS): run it twice with `APP=admin` and `APP=members`, point both at the same `DATABASE_URL` and storage.

---

## Phone and desktop apps

| | Android | iOS | Windows | macOS | Linux | Any browser |
|---|---|---|---|---|---|---|
| **Ecclesia Connect** (members) | ✓ app | ✓ app | | | | ✓ installable web app |
| **Ecclesia Admin** (management & finance) | | | ✓ app | ✓ app | ✓ app | ✓ installable web app |

The native apps live in [`apps/`](apps/README.md). On first launch they ask for the church's address, check that it really is the right Ecclesia app, and remember it; after that they open straight into the church. GitHub Actions builds the Windows, macOS and Linux installers, the Android APK/Play Store bundle and an iOS build — see [apps/README.md](apps/README.md) for building, signing and publishing to Google Play and the App Store.

Both web apps are also Progressive Web Apps: open either address in Chrome, Edge or Safari and choose *Install app* / *Add to Home Screen*.

---

## Website and public demo

[`website/`](website/README.md) is the Ecclesia marketing website: features, an interactive tour of both apps built from real screens of the sample church, app downloads, pricing (Seed KSh 10,000, Harvest KSh 20,000 and Kingdom KSh 30,000 a month, with yearly billing) and a "Get started" form that sends enquiries by WhatsApp or email. It is a static site; set prices, contacts and links in `website/js/config.js`. It is live at https://pizzatechies.github.io/churchapp/website/, and the **Website** GitHub Actions workflow keeps the `gh-pages` branch up to date for GitHub Pages.

To let people try Ecclesia themselves, run a separate server with `ECCLESIA_DEMO_MODE=1`. It loads the sample church on first start, adds one-click demo logins and a banner to both apps, and blocks password and login changes. `python manage.py reset_demo` restores the sample church (run it nightly); it refuses to run unless demo mode is on, so it can never wipe a real church.

---

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | — (required in production) | Django secret key; the same value for both apps |
| `DEBUG` | on only when no `SECRET_KEY` is set | Never enable in production |
| `DATABASE_URL` | `postgres://church:church@localhost:5432/church_finance` | PostgreSQL connection |
| `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` | localhost | Your domains |
| `TIME_ZONE` | `Africa/Nairobi` | Local time zone |
| `CHURCH_COUNTRY` | `KE` | Country preset applied on first setup (Docker) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | — | First administrator, created on start if missing (Docker) |
| `MAX_UPLOAD_MB` / `SERMON_MAX_UPLOAD_MB` | 15 / 300 | Upload limits |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | — | Optional object storage for uploads |
| `MPESA_CONSUMER_KEY`, `MPESA_CONSUMER_SECRET` | — | Optional: lets *Link account* register a Paybill/Till's payment address with Safaricom (Daraja). Receiving payments needs no keys |
| `MPESA_ENVIRONMENT` | `production` | `sandbox` to test against Safaricom's sandbox |
| `MPESA_ALLOWED_IPS` | — | Optional comma-separated list: only accept M-Pesa payment notices from these addresses |
| `PLATFORM_ADMIN_USERNAME` / `_PASSWORD` / `_EMAIL` | the `ADMIN_*` values | First platform super admin, created on start if missing |
| `ECCLESIA_DEFAULT_CHURCH` | — | On a brand-new server, create the first church with this web address name (uses `ADMIN_*`, `CHURCH_NAME`, `CHURCH_COUNTRY`) |
| `ADMIN_APP_URL` / `MEMBERS_APP_URL` | worked out from the address | The apps' addresses, for links in the platform console |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | — | SMTP for "Forgot password" emails |
| `LOGIN_MAX_FAILURES` / `LOGIN_LOCKOUT_MINUTES` | 5 / 15 | Sign-in protection |
| `ALWAYS_ON` | off | Set to 1 once the admin app runs on an always-on plan (Render's free plan sleeps) |
| `SESSION_HOURS` | 12 | How long people stay signed in |
| `DB_SSL_REQUIRE` | off | Require SSL to the database |

Everything about the church itself — name, address, KRA PIN/tax ID, country, currency, fiscal year start, approval limit, statement wording, closing date — is set in **Church settings** inside the admin app.

---

## Roles and permissions

Give each person one or more roles under *Users & roles*. Members don't need a role: they get a members-app login from their member record.

| Role | Can do |
|---|---|
| **Administrator** | Everything, including users, settings, backups and closing the books |
| **Treasurer** | All finances: giving, expenses, payroll, budgets, approvals, settings |
| **Bookkeeper** | Day-to-day entry: giving, expenses, payments, journal entries, reconciliations |
| **Finance Committee** | Reports, expense approvals, budgets |
| **Offering Counter** | Count and record offerings, maintain donor records; no reports |
| **Pastor** | Financial reports and dashboard, members directory, sermons; no individual giving or payroll |
| **Church Secretary** | Membership register, groups & fellowships, inductions, sermons; no finances |
| **Media Team** | Upload and publish sermons only |

Individual giving and payroll are confidential and visible only to the roles that need them. A member-only login is refused by the admin app, and a staff login without a member record is refused by the members app.

---

## How the accounting works

- **Double entry, per fund.** Every transaction is a journal entry whose debits equal its credits *within every fund*, so each fund always has its own balanced balance sheet. Money moves between funds only through an interfund transfer.
- **Sub-ledgers post automatically.** Offering batches, approved expenses, payments, payroll runs, depreciation and asset disposals each create their journal entry and link back to it.
- **Nothing is deleted.** Posted entries are voided (kept for the audit trail, excluded from balances). Offering batches can be reopened for correction, which voids their deposit entry.
- **Period close.** Setting *Books closed through* locks every earlier date against new entries, edits and voids.
- **Net assets** are reported by donor-restriction class (without / with donor restrictions), following nonprofit reporting practice.

<p align="center"><img src="docs/screenshots/balance-sheet.png" alt="Statement of financial position" width="70%"></p>

---

## Payroll: Kenya and other countries

The Kenya preset (default) sets up:

| Item | Rule |
|---|---|
| PAYE | Monthly bands 10% to 24,000 · 25% to 32,333 · 30% to 500,000 · 32.5% to 800,000 · 35% above; less personal relief of KSh 2,400 |
| NSSF | 6% employee + 6% employer, capped at KSh 4,320 each per month |
| SHIF | 2.75% of gross pay, minimum KSh 300 |
| Affordable Housing Levy | 1.5% employee + 1.5% employer |
| SACCO / welfare | Fixed amount per person |

NSSF, SHIF and the Housing Levy are deducted before PAYE is calculated. Bands, caps, minimums and relief are monthly figures and are pro-rated automatically for weekly, fortnightly and twice-monthly pay.

These are the rates in force when this version was written. **Tax law changes: check them against KRA, NSSF and SHA guidance and update them under *Pay & deduction types*** — no code changes are needed. Other countries get a generic preset (or a US preset with `--country US`) that you adapt the same way.

---

## Backups

- **Database**: schedule `pg_dump` (for Docker Compose: `docker compose exec db pg_dump -U ecclesia ecclesia > backup.sql`). Most managed PostgreSQL services do daily backups for you.
- **Uploads**: back up the `media` volume or your storage bucket.
- **In-app**: administrators can download a complete JSON export from *Backup*.

---

## Development

```bash
python manage.py test
```

The suite runs against PostgreSQL and covers posting rules, fund balancing, period locks, voids, reconciliation, giving, expense approvals and payments, Kenyan payroll calculations, depreciation, report integrity, membership rules (gender and age), the members app (including that members see only their own giving, that the church summary shows no names or individual salaries, and that no finance-office pages exist there), permissions, the audit trail, and a crawl of every page as every role.

```
config/        settings, URLs and WSGI for both apps (settings_portal / urls_portal = members app)
core/          church settings, roles & permissions, audit trail, attachments, dashboard, setup & demo commands
ledger/        chart of accounts, funds, journal entries, reconciliation, budgets
giving/        donors, offering batches, pledges, statements
expenses/      vendors, bills, approvals, payments
payroll/       staff, pay & deduction types, payroll runs, pay slips
fixedassets/   asset register and depreciation
reports/       financial and giving reports
members/       membership register, groups & fellowships, inductions, sermons (admin side)
portal/        Ecclesia Connect, the members app
```

Licensed under the MIT License. © Pizza Technologies.
