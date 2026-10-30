"""
Fill an empty database with realistic sample data: about two years of Sunday
offerings, bills, payroll, transfers, budgets, fixed assets and bank
reconciliations. Everything is created through the same posting services the
app uses, so the books balance exactly as they would in real use.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.middleware import acting_as, audit_disabled
from core.models import ChurchProfile
from core.permissions import (
    ADMINISTRATOR,
    BOOKKEEPER,
    FINANCE_COMMITTEE,
    OFFERING_COUNTER,
    TREASURER,
    VIEWER,
)
from core.setup import setup_church
from core.utils import add_months, fiscal_months, fiscal_year_of, month_end, q2, today

D = Decimal

FIRST_NAMES = [
    "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", "David", "Elizabeth", "William",
    "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Daniel", "Grace",
    "Matthew", "Ruth", "Anthony", "Esther", "Mark", "Naomi", "Paul", "Lydia", "Andrew", "Hannah", "Joshua", "Rebecca",
    "Kenneth", "Deborah", "Kevin", "Rachel", "Brian", "Martha", "Samuel", "Priscilla", "Peter", "Joy", "Moses", "Faith",
    "Emmanuel", "Mercy", "Isaac", "Abigail", "Chanda", "Mwila", "Bwalya", "Mutale", "Kofi", "Ama", "Tunde", "Ngozi",
    "Luis", "Maria", "Carlos", "Ana", "Wei", "Mei", "Hyun", "Ji-woo",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Thompson", "White", "Harris", "Clark",
    "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Green", "Baker", "Adams", "Nelson",
    "Hill", "Campbell", "Mitchell", "Roberts", "Phiri", "Banda", "Mwanza", "Tembo", "Mensah", "Okafor", "Adeyemi",
    "Nguyen", "Kim", "Chen", "Lopez", "Gonzalez", "Perez", "Hughes", "Price", "Bennett", "Wood", "Barnes", "Ross",
]
STREETS = ["Oak St", "Maple Ave", "Cedar Ln", "Church Rd", "Hillcrest Dr", "Park Ave", "River Rd", "Elm St", "Grace Way", "Sunset Blvd"]

USERS = [
    ("admin", "Alex", "Admin", ADMINISTRATOR, True),
    ("treasurer", "Tina", "Okafor", TREASURER, False),
    ("bookkeeper", "Ben", "Carter", BOOKKEEPER, False),
    ("committee", "Grace", "Mwanza", FINANCE_COMMITTEE, False),
    ("counter", "Carl", "Nguyen", OFFERING_COUNTER, False),
    ("pastor", "Paul", "Adeyemi", VIEWER, False),
]


class Command(BaseCommand):
    help = "Load about two years of realistic sample data into an empty database (for demos and evaluation)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="ChurchDemo-2026", help="Password for the demo user accounts")
        parser.add_argument("--force", action="store_true", help="Load even if transactions already exist")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **opts):
        from ledger.models import JournalEntry

        if JournalEntry.objects.exists() and not opts["force"]:
            raise CommandError("The database already has transactions. Use a fresh database (or --force) to load demo data.")
        self.rng = random.Random(opts["seed"])
        self.today = today()
        self.start = date(self.today.year - 1, 1, 1)
        with audit_disabled():
            setup_church()
            self.users = self._users(opts["password"])
            with acting_as(self.users["bookkeeper"]), transaction.atomic():
                self._run()
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write("Sign in with any of these usernames (password: %s):" % opts["password"])
        for username, first, last, role, _ in USERS:
            self.stdout.write(f"  {username:<11} {role}")

    # ------------------------------------------------------------------ helpers

    def _users(self, password):
        users = {}
        for username, first, last, role, superuser in USERS:
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": first, "last_name": last, "email": f"{username}@lifesource.example",
                "is_staff": superuser, "is_superuser": superuser,
            })
            if created:
                user.set_password(password)
                user.save()
            user.groups.add(Group.objects.get(name=role))
            users[username] = user
        return users

    def acct(self, number):
        from ledger.models import Account

        return Account.objects.get(number=number)

    def fund(self, code):
        from ledger.models import Fund

        return Fund.objects.get(code=code)

    def money(self, low, high, step=1):
        return D(self.rng.randrange(int(low / step), int(high / step) + 1) * step).quantize(D("0.01"))

    def sundays(self):
        d = self.start + timedelta(days=(6 - self.start.weekday()) % 7)
        while d <= self.today:
            yield d
            d += timedelta(days=7)

    def month_starts(self):
        d = self.start
        while d <= self.today:
            yield d
            d = add_months(d, 1)

    # --------------------------------------------------------------------- run

    def _run(self):
        profile = ChurchProfile.get()
        profile.name = "LifeSource Church"
        profile.address = "1200 Grace Avenue\nSpringfield, IL 62701"
        profile.phone = "(217) 555-0142"
        profile.email = "office@lifesource.example"
        profile.website = "lifesource.example"
        profile.tax_id = "37-1234567"
        profile.treasurer_name = "Tina Okafor"
        profile.save()

        self._opening_balances()
        self._fixed_assets()
        donors = self._donors()
        self._campaign(donors)
        self._giving(donors)
        vendors = self._vendors()
        self._employees()
        self._monthly_activity(vendors)
        self._depreciation()
        self._budget()
        self._reconciliations()
        self._recent_workflow(vendors)
        profile.lock_date = date(self.today.year - 1, 12, 31)
        profile.save()

    def _opening_balances(self):
        from ledger.services import record_opening_balances

        gen, bld, mis, ben, yth = (self.fund(c) for c in ["GEN", "BLD", "MIS", "BEN", "YTH"])
        opening = self.start - timedelta(days=1)
        self.opening_date = opening
        months_built = (opening.year - 2008) * 12 + (opening.month - 6) + 1
        self.building_prior = q2(D("1150000") / 480 * months_built)
        months_sound = (opening.year - 2022) * 12 + (opening.month - 9) + 1
        self.sound_prior = q2(D("42000") / 60 * months_sound)
        record_opening_balances(date=opening, user=self.users["treasurer"], rows=[
            (self.acct("1010"), gen, D("42850.00")),
            (self.acct("1010"), ben, D("2150.00")),
            (self.acct("1020"), bld, D("118400.00")),
            (self.acct("1020"), mis, D("6300.00")),
            (self.acct("1020"), yth, D("3900.00")),
            (self.acct("1050"), gen, D("300.00")),
            (self.acct("1500"), gen, D("250000.00")),
            (self.acct("1510"), gen, D("1150000.00")),
            (self.acct("1530"), gen, D("42000.00")),
            (self.acct("1590"), gen, -(self.building_prior + self.sound_prior)),
            (self.acct("2500"), gen, D("412000.00")),
        ])

    def _fixed_assets(self):
        from fixedassets.models import FixedAsset

        gen = self.fund("GEN")
        common = {"accumulated_account": self.acct("1590"), "expense_account": self.acct("8100"), "fund": gen}
        FixedAsset.objects.create(name="Church property (land)", category="land", acquisition_date=date(2007, 3, 1),
                                  in_service_date=date(2007, 3, 1), cost=D("250000"), useful_life_months=0,
                                  asset_account=self.acct("1500"), location="1200 Grace Avenue", **common)
        FixedAsset.objects.create(name="Sanctuary & education building", category="building", acquisition_date=date(2008, 6, 1),
                                  in_service_date=date(2008, 6, 1), cost=D("1150000"), useful_life_months=480,
                                  prior_depreciation=self.building_prior, prior_depreciation_through=self.opening_date,
                                  asset_account=self.acct("1510"), location="Main campus", tag_number="B-001", **common)
        FixedAsset.objects.create(name="Sanctuary sound & projection system", category="av", acquisition_date=date(2022, 9, 15),
                                  in_service_date=date(2022, 9, 15), cost=D("42000"), useful_life_months=60,
                                  prior_depreciation=self.sound_prior, prior_depreciation_through=self.opening_date,
                                  asset_account=self.acct("1530"), location="Sanctuary", tag_number="AV-014", **common)

    def _donors(self):
        from giving.models import Donor

        donors = []
        used = set()
        envelope = 101
        for i in range(96):
            while True:
                first, last = self.rng.choice(FIRST_NAMES), self.rng.choice(LAST_NAMES)
                if (first, last) not in used:
                    used.add((first, last))
                    break
            household = self.rng.random() < 0.45
            spouse = self.rng.choice(FIRST_NAMES)
            d = Donor.objects.create(
                donor_type=Donor.HOUSEHOLD if household else Donor.INDIVIDUAL,
                first_name=f"{first} & {spouse}" if household else first, last_name=last,
                envelope_number=str(envelope) if self.rng.random() < 0.8 else None,
                email=f"{first.lower()}.{last.lower()}@example.com".replace(" ", ""),
                phone=f"(217) 555-{self.rng.randint(1000, 9999)}",
                address_line1=f"{self.rng.randint(100, 9999)} {self.rng.choice(STREETS)}",
                city="Springfield", state="IL", postal_code=f"627{self.rng.randint(10, 99)}",
                is_member=self.rng.random() < 0.75,
                member_since=date(self.rng.randint(2005, 2024), self.rng.randint(1, 12), 1),
            )
            envelope += 1
            pattern = self.rng.choices(["weekly", "biweekly", "monthly", "occasional"], weights=[45, 15, 25, 15])[0]
            base = {"weekly": (25, 180), "biweekly": (50, 300), "monthly": (100, 900), "occasional": (20, 150)}[pattern]
            d.pattern = pattern
            d.amount = self.money(*base, step=5)
            d.online = self.rng.random() < 0.3
            d.method = self.rng.choices(["check", "cash", "card"], weights=[60, 25, 15])[0]
            d.building_share = self.rng.choice([0, 0, 0, D("0.1"), D("0.15"), D("0.25")])
            d.lapse_after = self.today - timedelta(days=self.rng.randint(120, 300)) if self.rng.random() < 0.07 else None
            d.joined = self.start + timedelta(days=self.rng.randint(150, 500)) if self.rng.random() < 0.08 else None
            donors.append(d)
        for name in ["Springfield Community Foundation", "Grace Hardware & Supply", "Faith Lutheran Church (partner)"]:
            d = Donor.objects.create(donor_type=Donor.ORGANIZATION, organization_name=name, city="Springfield", state="IL")
            d.pattern = "org"
            donors.append(d)
        return donors

    def _campaign(self, donors):
        from giving.models import Campaign, Pledge

        start = add_months(self.today.replace(day=1), -10)
        self.campaign = Campaign.objects.create(
            name="Building Expansion Campaign", fund=self.fund("BLD"), start_date=start, end_date=add_months(start, 24) - timedelta(days=1),
            goal=D("250000"), description="New children's wing and accessible restrooms.",
        )
        pledgers = [d for d in donors if getattr(d, "pattern", "") in ("weekly", "monthly", "biweekly")]
        for d in self.rng.sample(pledgers, 28):
            amount = self.money(600, 9000, step=100)
            Pledge.objects.create(donor=d, campaign=self.campaign, amount=amount, pledge_date=start + timedelta(days=self.rng.randint(0, 40)),
                                  frequency=self.rng.choice(["monthly", "weekly", "quarterly", "once"]))
            d.pledge_monthly = q2(amount / 24)
        Campaign.objects.create(name="Christmas Missions Offering", fund=self.fund("MIS"), start_date=date(self.today.year - 1, 11, 15),
                                end_date=date(self.today.year - 1, 12, 31), goal=D("15000"), is_active=False,
                                description="Year-end offering for mission partners.")

    def _giving(self, donors):
        from giving.models import Contribution, ContributionBatch
        from giving.services import post_batch

        checking = self.acct("1010")
        gen, bld, mis, ben = (self.fund(c) for c in ["GEN", "BLD", "MIS", "BEN"])
        tithes, offerings, special = self.acct("4000"), self.acct("4010"), self.acct("4060")
        building, missions, benevolence = self.acct("4030"), self.acct("4040"), self.acct("4050")
        check_no = 1000
        sundays = list(self.sundays())
        for n, sunday in enumerate(sundays):
            is_last = n == len(sundays) - 1
            batch = ContributionBatch.objects.create(
                date=sunday, description="Sunday morning offering", deposit_account=checking,
                counted_by=self.rng.choice(["J. Smith & M. Lee", "R. Banda & K. Hughes", "D. Kim & S. Price"]),
                created_by=self.users["counter"],
            )
            gifts = []
            special_sunday = sunday.month == 12 and sunday.day > 17 or (sunday.month in (3, 4) and self.rng.random() < 0.25)
            for d in donors:
                if d.pattern == "org" or d.online:
                    continue
                if d.lapse_after and sunday > d.lapse_after:
                    continue
                if d.joined and sunday < d.joined:
                    continue
                give = (
                    (d.pattern == "weekly" and self.rng.random() < 0.82)
                    or (d.pattern == "biweekly" and n % 2 == d.pk % 2 and self.rng.random() < 0.9)
                    or (d.pattern == "monthly" and sunday.day <= 7 and self.rng.random() < 0.92)
                    or (d.pattern == "occasional" and self.rng.random() < 0.18)
                )
                if not give:
                    continue
                amount = q2(d.amount * D(str(self.rng.choice([1, 1, 1, 1, 0.8, 1.2, 1.5]))))
                check_no += 1
                method = d.method
                ref = str(check_no) if method == "check" else ""
                gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=gen, account=tithes, amount=amount, method=method, check_number=ref))
                if getattr(d, "pledge_monthly", None) and sunday >= self.campaign.start_date and sunday.day <= 7:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=bld, account=building, amount=d.pledge_monthly, method=method, check_number=ref))
                elif d.building_share and self.rng.random() < 0.3:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=bld, account=building, amount=q2(amount * d.building_share), method=method, check_number=ref))
                if self.rng.random() < 0.06:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=mis, account=missions, amount=self.money(20, 200, 5), method=method, check_number=ref))
                if special_sunday and self.rng.random() < 0.5:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=mis if sunday.month == 12 else gen, account=special,
                                              amount=self.money(25, 400, 5), method=method, check_number=ref, memo="Special offering"))
            gifts.append(Contribution(batch=batch, date=sunday, fund=gen, account=offerings, amount=self.money(180, 650), method="cash", memo="Loose offering"))
            if sunday.day <= 7:
                gifts.append(Contribution(batch=batch, date=sunday, fund=ben, account=benevolence, amount=self.money(150, 600), method="cash", memo="Communion benevolence offering"))
            Contribution.objects.bulk_create(gifts)
            batch.control_total = sum(g.amount for g in gifts)
            batch.save()
            if not is_last:
                post_batch(batch, self.users["bookkeeper"])

        online_donors = [d for d in donors if getattr(d, "online", False)]
        orgs = [d for d in donors if d.pattern == "org"]
        for month in self.month_starts():
            end = min(month_end(month), self.today)
            if end < month_end(month):
                continue
            batch = ContributionBatch.objects.create(date=end, description=f"Online giving – {month:%B %Y}", deposit_account=checking,
                                                     counted_by="Online giving report", created_by=self.users["bookkeeper"])
            gifts = []
            for d in online_donors:
                if (d.lapse_after and end > d.lapse_after) or (d.joined and end < d.joined):
                    continue
                times = {"weekly": 4, "biweekly": 2, "monthly": 1, "occasional": self.rng.choice([0, 0, 1])}[d.pattern]
                for i in range(times):
                    gifts.append(Contribution(batch=batch, donor=d, date=month + timedelta(days=min(27, 7 * i + self.rng.randint(0, 5))),
                                              fund=gen, account=tithes, amount=d.amount, method="online"))
            if month.month in (6, 12):
                for org in orgs:
                    gifts.append(Contribution(batch=batch, donor=org, date=end, fund=self.rng.choice([bld, mis, gen]),
                                              account=self.acct("4020"), amount=self.money(500, 5000, 50), method="bank_transfer"))
            if gifts:
                Contribution.objects.bulk_create(gifts)
                post_batch(batch, self.users["bookkeeper"])
            else:
                batch.delete()

    def _vendors(self):
        from expenses.models import Vendor

        rows = [
            ("Springfield Power & Light", "6010", False), ("City Water Department", "6010", False),
            ("Ameren Gas", "6010", False), ("Brotherhood Mutual Insurance", "6040", False),
            ("First National Bank – Mortgage", "6000", False), ("Comcast Business", "8020", False),
            ("Planning Center (software)", "8030", False), ("Office Depot", "8000", False),
            ("CleanPro Janitorial Supply", "6030", False), ("Lifeway Christian Resources", "7010", False),
            ("Mike's HVAC & Plumbing", "6020", True), ("Global Mission Partners", "7100", False),
            ("Hope Food Pantry", "7110", False), ("District Conference Office", "8080", False),
            ("Smith & Associates CPA", "8050", True), ("Rev. Daniel Hughes (guest speaker)", "5050", True),
            ("Camp Wildwood", "7020", False), ("Internal Revenue Service", None, False),
            ("Church Pension & Benefits Board", None, False), ("Costco", "7050", False), ("Ultimate Security Systems", "6050", False),
            ("Springfield Ford", None, False),
        ]
        vendors = {}
        for name, account, is1099 in rows:
            vendors[name] = Vendor.objects.create(name=name, default_account=self.acct(account) if account else None, is_1099=is1099,
                                                  tax_id=f"{self.rng.randint(10, 99)}-{self.rng.randint(1000000, 9999999)}" if is1099 else "")
        return vendors

    def _employees(self):
        from payroll.models import Employee, EmployeePayrollItem, PayrollItem

        gen = self.fund("GEN")
        items = {i.name: i for i in PayrollItem.objects.all()}
        staff = [
            ("Daniel", "Okoro", "Senior Pastor", "clergy", "salary", D("64000"), D("0"), D("0"), D("30000"), "5000",
             {"Income Tax Withholding": 12, "Retirement – Employee": 6}),
            ("Sarah", "Mitchell", "Youth & Family Pastor", "clergy", "salary", D("41000"), D("0"), D("0"), D("16000"), "5000",
             {"Income Tax Withholding": 10, "Retirement – Employee": 5}),
            ("Linda", "Chen", "Church Administrator", "staff", "salary", D("39500"), D("0"), D("0"), D("0"), "5010",
             {"Income Tax Withholding": 10, "Social Security – Employee": D("7.65"), "Social Security – Employer": D("7.65"),
              "Retirement – Employee": 4, "Retirement – Employer Match": 3, "Health Insurance – Employee Share": 85}),
            ("Marcus", "Bennett", "Worship Director (part-time)", "staff", "hourly", D("0"), D("24.50"), D("40"), D("0"), "5010",
             {"Income Tax Withholding": 8, "Social Security – Employee": D("7.65"), "Social Security – Employer": D("7.65")}),
            ("Joseph", "Banda", "Custodian (part-time)", "staff", "hourly", D("0"), D("17.00"), D("52"), D("0"), "5010",
             {"Income Tax Withholding": 6, "Social Security – Employee": D("7.65"), "Social Security – Employer": D("7.65")}),
        ]
        for first, last, title, etype, ptype, salary, rate, hours, housing, account, deductions in staff:
            e = Employee.objects.create(
                first_name=first, last_name=last, title=title, employee_type=etype, pay_type=ptype, pay_frequency="semimonthly",
                annual_salary=salary, hourly_rate=rate, default_hours=hours, annual_housing_allowance=housing,
                wage_account=self.acct(account), fund=gen, hire_date=date(self.rng.randint(2012, 2022), self.rng.randint(1, 12), 1),
                email=f"{first.lower()}@lifesource.example", tax_id_last4=str(self.rng.randint(1000, 9999)),
            )
            for name, rate_ in deductions.items():
                EmployeePayrollItem.objects.create(employee=e, item=items[name], amount=D(str(rate_)))

    def _pay(self, vendor, when, lines, description, reference="", pay=True, method="check"):
        """Create, submit, approve (as treasurer) and optionally pay an expense."""
        from expenses import services as ex
        from expenses.models import Expense, ExpenseLine

        expense = Expense.objects.create(vendor=vendor, date=when, due_date=when + timedelta(days=21), description=description,
                                         reference=reference, requested_by=self.users["bookkeeper"])
        for account, fund, amount, desc in lines:
            ExpenseLine.objects.create(expense=expense, account=account, fund=fund, amount=q2(amount), description=desc)
        ex.submit_expense(expense, self.users["bookkeeper"])
        expense.refresh_from_db()
        if expense.status == Expense.PENDING:
            ex.approve_expense(expense, self.users["treasurer"], "Within budget")
            expense.refresh_from_db()
        if pay:
            self.check_no += 1
            pay_date = min(when + timedelta(days=self.rng.randint(3, 12)), self.today)
            ex.record_payment(expense, self.users["bookkeeper"], date=pay_date, amount=expense.total, pay_from=self.acct("1010"),
                              method=method, reference=str(self.check_no) if method == "check" else "ACH")
        return expense

    def _monthly_activity(self, v):
        from ledger.services import (
            record_bank_transfer,
            record_fund_transfer,
            record_income,
        )
        from payroll.services import create_run, post_run

        gen, bld, mis, ben, yth = (self.fund(c) for c in ["GEN", "BLD", "MIS", "BEN", "YTH"])
        A = self.acct
        self.check_no = 4000
        mortgage_balance = D("412000")
        for month in self.month_starts():
            m_end = month_end(month)
            complete = m_end < self.today
            # Payroll on the 15th and last day of the month
            for start_day, pay_day in [(month, month.replace(day=15)), (month.replace(day=16), m_end)]:
                if pay_day > self.today:
                    continue
                run = create_run(period_start=start_day, period_end=pay_day, pay_date=pay_day, bank_account=A("1010"), user=self.users["treasurer"])
                post_run(run, self.users["treasurer"])

            def on(day):
                return month.replace(day=min(day, m_end.day))

            bills = [
                (5, "Springfield Power & Light", [(A("6010"), gen, self.money(780, 1450), "Electricity")], "Electric service"),
                (8, "City Water Department", [(A("6010"), gen, self.money(95, 210), "Water & sewer")], "Water service"),
                (10, "Ameren Gas", [(A("6010"), gen, self.money(90, 980) if month.month in (11, 12, 1, 2, 3) else self.money(60, 140), "Gas")], "Natural gas"),
                (3, "Comcast Business", [(A("8020"), gen, D("189.99"), "Internet & phones")], "Internet & phone"),
                (2, "Planning Center (software)", [(A("8030"), gen, D("214.00"), "Church management software")], "Software subscription"),
                (12, "CleanPro Janitorial Supply", [(A("6030"), gen, self.money(120, 380), "Cleaning supplies")], "Janitorial supplies"),
                (15, "Global Mission Partners", [(A("7100"), mis, D("1500.00"), "Monthly missionary support")], "Missionary support"),
                (20, "District Conference Office", [(A("8080"), gen, D("650.00"), "Monthly apportionment")], "Denominational dues"),
                (22, "Ultimate Security Systems", [(A("6050"), gen, D("89.00"), "Alarm monitoring")], "Alarm monitoring"),
            ]
            interest = q2(mortgage_balance * D("0.045") / 12)
            principal = D("3100.00") - interest
            mortgage_balance -= principal
            bills.append((1, "First National Bank – Mortgage", [(A("6000"), gen, interest, "Interest"), (A("2500"), gen, principal, "Principal")], "Mortgage payment"))
            if month.month % 3 == 1:
                bills.append((6, "Brotherhood Mutual Insurance", [(A("6040"), gen, D("3240.00"), "Quarterly property & liability premium")], "Insurance premium"))
            if self.rng.random() < 0.7:
                bills.append((14, "Office Depot", [(A("8000"), gen, self.money(60, 320), "Office supplies"), (A("8010"), gen, self.money(40, 180), "Bulletins & printing")], "Office supplies"))
            if self.rng.random() < 0.6:
                bills.append((18, "Lifeway Christian Resources", [(A("7010"), gen, self.money(150, 620), "Curriculum"), (A("7030"), gen, self.money(80, 300), "Small group books")], "Curriculum"))
            if self.rng.random() < 0.45:
                fund = bld if self.rng.random() < 0.5 else gen
                bills.append((17, "Mike's HVAC & Plumbing", [(A("6020"), fund, self.money(250, 2800, 5), "Repairs")], "Building repairs"))
            if self.rng.random() < 0.65:
                bills.append((24, "Hope Food Pantry", [(A("7110"), ben, self.money(200, 900, 5), "Family assistance")], "Benevolence assistance"))
            if month.month in (2, 5, 8, 11):
                bills.append((26, "Rev. Daniel Hughes (guest speaker)", [(A("5050"), gen, D("400.00"), "Guest preaching honorarium")], "Guest speaker"))
            if month.month == 7:
                bills.append((9, "Camp Wildwood", [(A("7020"), yth, D("4200.00"), "Summer youth camp")], "Youth camp"))
            if month.month == 12:
                bills.append((11, "Costco", [(A("7050"), gen, D("865.40"), "Christmas fellowship dinner")], "Christmas dinner"))
            if month.month == 3:
                bills.append((28, "Smith & Associates CPA", [(A("8050"), gen, D("2400.00"), "Annual financial review")], "Annual review"))

            for day, vendor, lines, desc in bills:
                when = on(day)
                if when > self.today:
                    continue
                pay = complete or (self.today - when).days > 10
                self._pay(v[vendor], when, lines, desc, reference=f"INV-{when:%y%m}{day:02d}", pay=pay,
                          method="bank_transfer" if vendor.startswith(("First National", "Planning", "Comcast")) else "check")

            if complete:
                # Remit last month's payroll withholdings and taxes
                self._remit_payroll(v, m_end)
                record_income(date=on(9), deposit_account=A("1010"), income_account=A("4200"), fund=gen, amount=D("450.00"),
                              user=self.users["bookkeeper"], memo="Facility rental – Springfield Korean Fellowship")
                record_income(date=m_end, deposit_account=A("1020"), income_account=A("4300"), fund=bld,
                              amount=self.money(160, 260), user=self.users["bookkeeper"], memo="Savings interest")
                bld_cash = A("1010").balance(end=m_end, fund=bld)
                if bld_cash > 500:
                    record_bank_transfer(date=m_end, from_account=A("1010"), to_account=A("1020"), amount=bld_cash, fund=bld,
                                         user=self.users["treasurer"], memo="Move building fund gifts to reserve savings")
                if month.month in (3, 6, 9, 12):
                    record_fund_transfer(date=m_end, from_fund=gen, to_fund=mis, amount=D("2500.00"), cash_account=A("1010"),
                                         user=self.users["treasurer"], memo="Board-approved quarterly missions transfer")
                if month.month == 1:
                    record_fund_transfer(date=on(31), from_fund=gen, to_fund=yth, amount=D("3000.00"), cash_account=A("1010"),
                                         user=self.users["treasurer"], memo="Board designation for youth ministry")
        # A church van bought this year
        van_day = date(self.today.year, 4, 18) if self.today >= date(self.today.year, 5, 1) else self.today - timedelta(days=30)
        self._pay(v["Springfield Ford"], van_day, [(A("1540"), gen, D("36500.00"), "15-passenger van")], "Church van purchase", pay=True, method="bank_transfer")
        from fixedassets.models import FixedAsset

        FixedAsset.objects.create(name="15-passenger church van", category="vehicle", acquisition_date=van_day, in_service_date=van_day,
                                  cost=D("36500.00"), salvage_value=D("6500.00"), useful_life_months=60, asset_account=A("1540"),
                                  accumulated_account=A("1590"), expense_account=A("8100"), fund=gen, tag_number="V-003",
                                  serial_number="1FBAX2CM5KKB12345", location="Church parking lot")

    def _remit_payroll(self, v, as_of):
        lines_irs, lines_pension = [], []
        gen = self.fund("GEN")
        for number in ("2100", "2110"):
            bal = self.acct(number).balance(end=as_of)
            if bal > 0:
                lines_irs.append((self.acct(number), gen, bal, "Remit payroll withholding"))
        for number in ("2120", "2130"):
            bal = self.acct(number).balance(end=as_of)
            if bal > 0:
                lines_pension.append((self.acct(number), gen, bal, "Remit retirement and health contributions"))
        when = as_of + timedelta(days=1)
        if lines_irs and when <= self.today:
            self._pay(v["Internal Revenue Service"], when, lines_irs, f"Payroll taxes for {as_of:%B %Y}", method="bank_transfer")
        if lines_pension and when <= self.today:
            self._pay(v["Church Pension & Benefits Board"], when, lines_pension, f"Retirement contributions for {as_of:%B %Y}", method="bank_transfer")

    def _depreciation(self):
        from fixedassets.services import run_depreciation

        last_month_end = self.today.replace(day=1) - timedelta(days=1)
        # Annual run for last year, then monthly this year
        run_depreciation(date(self.today.year - 1, 12, 31), self.users["treasurer"])
        d = date(self.today.year, 1, 31)
        while d <= last_month_end:
            run_depreciation(d, self.users["treasurer"])
            d = month_end(d + timedelta(days=1))

    def _budget(self):
        from django.utils import timezone

        from ledger import services
        from ledger.models import Account, Budget, BudgetLine

        fy = fiscal_year_of(self.today)
        gen = self.fund("GEN")
        budget = Budget.objects.create(fiscal_year=fy, fund=gen, status=Budget.APPROVED, approved_by=self.users["committee"],
                                       approved_at=timezone.now(), notes="Approved by the finance committee and congregation.")
        prior_months = fiscal_months(fy - 1)
        accounts = {a.pk: a for a in Account.objects.filter(type__in=[Account.INCOME, Account.EXPENSE])}
        totals = {}
        for i, first, last in prior_months:
            for account_id, amount in services.account_balances(start=first, end=last, funds=[gen]).items():
                if account_id in accounts:
                    totals.setdefault(account_id, [D("0")] * 12)[i] += amount
        for account_id, months in totals.items():
            account = accounts[account_id]
            factor = D("1.04") if account.type == Account.INCOME else D("1.03")
            annual = q2(sum(months) * factor / 50) * 50
            if annual <= 0:
                continue
            if account.number in ("6010",):
                shaped = [q2(m * factor) for m in months]
            else:
                shaped = [q2(annual / 12)] * 12
                shaped[-1] += annual - sum(shaped)
            BudgetLine.objects.create(budget=budget, account=account, months=[str(x) for x in shaped])

    def _reconciliations(self):
        from ledger import services

        through = add_months(self.today.replace(day=1), -1) - timedelta(days=1)  # end of the month before last
        for number in ("1010", "1020"):
            account = self.acct(number)
            d = month_end(self.start)
            while d <= through:
                balance = account.balance(end=d)
                rec = services.start_reconciliation(account=account, statement_date=d, statement_balance=balance, user=self.users["bookkeeper"])
                ids = services.reconciliation_candidates(rec).values_list("pk", flat=True)
                services.set_cleared(rec, ids)
                services.complete_reconciliation(rec, self.users["bookkeeper"])
                d = month_end(d + timedelta(days=1))

    def _recent_workflow(self, v):
        """A few documents in mid-workflow so every screen has something to show."""
        from expenses import services as ex
        from expenses.models import Expense, ExpenseLine

        gen, yth = self.fund("GEN"), self.fund("YTH")
        A = self.acct
        pending = Expense.objects.create(vendor=v["Mike's HVAC & Plumbing"], date=self.today - timedelta(days=3), due_date=self.today + timedelta(days=27),
                                         description="Replace fellowship hall water heater", reference="Q-2231", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=pending, account=A("6020"), fund=self.fund("BLD"), amount=D("2875.00"), description="Water heater & install")
        ex.submit_expense(pending, self.users["bookkeeper"])
        reimb = Expense.objects.create(vendor=v["Costco"], expense_type=Expense.REIMBURSEMENT, date=self.today - timedelta(days=2),
                                       description="Youth lock-in snacks (reimburse S. Mitchell)", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=reimb, account=A("7020"), fund=yth, amount=D("612.48"), description="Food & drinks")
        ex.submit_expense(reimb, self.users["bookkeeper"])
        draft = Expense.objects.create(vendor=v["Office Depot"], date=self.today, description="Printer toner", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=draft, account=A("8000"), fund=gen, amount=D("146.20"))
        draft.recalculate_total()
        draft.save()
        rejected = Expense.objects.create(vendor=v["Costco"], date=self.today - timedelta(days=9), description="New lobby furniture",
                                          requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=rejected, account=A("6020"), fund=gen, amount=D("1980.00"))
        ex.submit_expense(rejected, self.users["bookkeeper"])
        ex.reject_expense(rejected, self.users["treasurer"], "Not in this year's budget — please bring to the November committee meeting.")
