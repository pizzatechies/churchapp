<p align="center">
  <img src="static/brand/ecclesia-logo.svg" alt="Ecclesia" width="96">
</p>

<h1 align="center">Ecclesia</h1>
<p align="center"><strong>Church management, membership &amp; finance — a product of Pizza Technologies</strong></p>

Ecclesia gives a church everything it needs to run its finances properly and keep its people connected. It comes as **two apps on one PostgreSQL database**:

| App | Who uses it | What it does |
|---|---|---|
| **Ecclesia Admin** | Pastors, treasurer, bookkeeper, church secretary, finance committee, offering counters, media team | Full double-entry fund accounting, giving, expenses, payroll, budgets, assets, reports, **plus** the membership register, groups & fellowships, inductions and sermon uploads |
| **Ecclesia Connect** | Church members | Fellowships, church groups, sermons and the member's own profile. **Nothing financial exists in this app** — the finance screens aren't hidden, they simply aren't part of it |

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
- Mobile-first with a bottom tab bar; works as a website on any phone.

### Finance (Admin app)
- **Double-entry fund accounting**: chart of accounts designed for churches, funds (General, Building, Missions, Benevolence, Youth...) with donor-restriction classes, and every journal entry balanced *within each fund*.
- **Giving**: offering/deposit batches with count-sheet control totals and two-counter sign-off, fast entry by envelope number, cash, cheque, card, bank transfer and **M-Pesa** (with transaction codes), donors, pledges and building campaigns, year-end contribution statements (print/PDF/CSV), donor CSV import.
- **Expenses**: bills, reimbursements and payment requests with receipts attached, an approval limit, **segregation of duties** (nobody approves their own request), partial payments split exactly across funds, voids, duplicates for recurring bills.
- **Payroll**: salaried and hourly staff, configurable earnings/deductions/employer contributions, progressive tax bands with relief, monthly caps and minimums, pre-tax deductions, pay slips with year-to-date figures, posting to the ledger and remittance tracking.
- **Banking**: bank/cash/M-Pesa/credit-card accounts, transfers, interfund transfers, other income, **bank reconciliation** with live difference checking.
- **Budgets**: monthly budget grid per fund, seeded from last year's actuals, with approval.
- **Fixed assets**: register, straight-line depreciation (including assets migrated with prior depreciation), disposal with automatic gain/loss.
- **Controls**: role-based access, period close (lock date), complete audit trail of every change, protected attachments, one-click JSON backup.
- **17 reports** with print/PDF and CSV export: statement of financial position, statement of activities (with prior-year comparison), functional expenses, fund activity, cash receipts & disbursements, budget vs actual, income & expenses by month, giving summary, giving by donor, lapsed donors, unpaid bills (aging), payments by payee, year-end tax-form payees, payroll summary, payroll liabilities, trial balance, general ledger.

<p align="center">
  <img src="docs/screenshots/membership-summary.png" alt="Membership summary by gender and age" width="49%">
  <img src="docs/screenshots/kenyan-payslip.png" alt="Kenyan pay slip" width="49%">
</p>

---

## Why Django + PostgreSQL

Money software has to be correct first. The backend is **Django (Python)** on **PostgreSQL**:

- **PostgreSQL** stores amounts as exact `numeric` values (no floating-point rounding), enforces constraints, and gives row-level locking so two people posting at once can't corrupt a batch.
- **Every request runs in a database transaction**, and every posting goes through one service that validates the double-entry rules — a failure part-way can never leave half-posted books.
- **Django** brings mature, secure foundations: authentication, CSRF/XSS/clickjacking protection, migrations and an admin, maintained since 2005 and used by organisations of every size.
- Two apps, one codebase: both apps share the same models and database but have **separate URL configurations, templates, logins and session cookies**, so the members app physically contains no financial code paths.

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

### Option B — managed cloud (Render)

`render.yaml` is a blueprint for [Render](https://render.com): a managed PostgreSQL database plus the two apps as separate services. Because separate services don't share a disk, set the `S3_*` variables so uploads go to an S3-compatible bucket (Cloudflare R2, AWS S3, DigitalOcean Spaces, Backblaze B2). Files stay private: the apps hand out signed links that expire after an hour.

The same Docker image runs on any container platform (Fly.io, Railway, Google Cloud Run, Azure, AWS): run it twice with `APP=admin` and `APP=members`, point both at the same `DATABASE_URL` and storage.

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

The suite runs against PostgreSQL and covers posting rules, fund balancing, period locks, voids, reconciliation, giving, expense approvals and payments, Kenyan payroll calculations, depreciation, report integrity, membership rules (gender and age), the members app (including that no financial pages exist there), permissions, the audit trail, and a crawl of every page as every role.

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
