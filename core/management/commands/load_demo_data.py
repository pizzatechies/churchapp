"""
Fill an empty database with a realistic sample church: a Nairobi congregation
with about two years of offerings (cash, M-Pesa, bank), bills, Kenyan payroll
with statutory deductions, transfers, a budget, fixed assets, reconciliations,
a membership register with groups and fellowships, and sermons.

Everything is created through the same services the app uses, so the books
balance exactly as they would in real use.
"""

import io
import random
import string
import wave
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group as AuthGroup
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.middleware import acting_as, audit_disabled
from core.models import ChurchProfile
from core.permissions import (
    ADMINISTRATOR,
    BOOKKEEPER,
    FINANCE_COMMITTEE,
    MEDIA_TEAM,
    OFFERING_COUNTER,
    SECRETARY,
    TREASURER,
    VIEWER,
)
from core.setup import setup_church
from core.utils import add_months, fiscal_months, fiscal_year_of, month_end, q2, today

D = Decimal

WOMEN = ["Wanjiru", "Achieng", "Njeri", "Wambui", "Akinyi", "Chebet", "Nyambura", "Atieno", "Mumbua", "Kendi", "Wairimu",
         "Nafula", "Jepkosgei", "Moraa", "Awino", "Muthoni", "Grace", "Mercy", "Faith", "Esther", "Ruth", "Joy", "Lucy",
         "Mary", "Ann", "Caroline", "Janet", "Purity", "Beatrice", "Rose", "Naomi", "Diana", "Sharon", "Lydia", "Eunice"]
MEN = ["Kamau", "Otieno", "Mwangi", "Kiprono", "Ochieng", "Mutua", "Kipchoge", "Omondi", "Njoroge", "Wekesa", "Kariuki",
       "Barasa", "Kibet", "Onyango", "Muriuki", "Juma", "Peter", "John", "James", "David", "Samuel", "Daniel", "Joseph",
       "Brian", "Kevin", "Dennis", "Collins", "Stephen", "Paul", "Moses", "Isaac", "Victor", "George", "Patrick", "Eric"]
SURNAMES = ["Kamau", "Otieno", "Mwangi", "Wanjiku", "Ochieng", "Mutua", "Kiprotich", "Omondi", "Njoroge", "Wekesa",
            "Kariuki", "Barasa", "Kibet", "Onyango", "Muriuki", "Achieng", "Ndungu", "Gitau", "Maina", "Kimani", "Odhiambo",
            "Cheruiyot", "Rotich", "Nyaga", "Mugo", "Wafula", "Simiyu", "Owino", "Kilonzo", "Musyoka", "Ruto", "Langat",
            "Kirui", "Macharia", "Githinji", "Nduta", "Okoth", "Juma", "Wanyama", "Makau"]
AREAS = [("Kilimani", "Nairobi"), ("Westlands", "Nairobi"), ("South B", "Nairobi"), ("Kasarani", "Nairobi"),
         ("Rongai", "Kajiado"), ("Lang'ata", "Nairobi"), ("Embakasi", "Nairobi"), ("Kileleshwa", "Nairobi")]
CELLS = {"Kilimani": "Kilimani Home Cell", "Westlands": "Westlands Home Cell", "South B": "South B Home Cell",
         "Kasarani": "Kasarani Home Cell", "Rongai": "Rongai Home Cell", "Lang'ata": "Lang'ata Home Cell",
         "Embakasi": "Embakasi Home Cell", "Kileleshwa": "Kilimani Home Cell"}
OCCUPATIONS = ["Teacher", "Nurse", "Accountant", "Engineer", "Business owner", "Civil servant", "Student", "Driver",
               "Farmer", "Doctor", "Lawyer", "IT consultant", "Banker", "Tailor", "Mechanic", "Retired", "Sales manager"]

STAFF_USERS = [
    ("admin", "Alex", "Mbugua", ADMINISTRATOR, True),
    ("treasurer", "Esther", "Wambui", TREASURER, False),
    ("bookkeeper", "Brian", "Kiprop", BOOKKEEPER, False),
    ("committee", "Grace", "Mwende", FINANCE_COMMITTEE, False),
    ("counter", "Collins", "Ouma", OFFERING_COUNTER, False),
    ("pastor", "Samuel", "Kiprono", VIEWER, False),
    ("secretary", "Mercy", "Wanjiru", SECRETARY, False),
    ("media", "Kevin", "Otieno", MEDIA_TEAM, False),
]


class Command(BaseCommand):
    help = "Load about two years of realistic sample data (a Nairobi church) into an empty database."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="ChurchDemo-2026", help="Password for every demo login")
        parser.add_argument("--force", action="store_true", help="Load even if transactions already exist")
        parser.add_argument("--seed", type=int, default=2026)

    def handle(self, *args, **opts):
        from ledger.models import JournalEntry

        if JournalEntry.objects.exists() and not opts["force"]:
            raise CommandError("The database already has transactions. Use a fresh database (or --force) to load demo data.")
        self.rng = random.Random(opts["seed"])
        self.password = opts["password"]
        self.today = today()
        self.start = date(self.today.year - 1, 1, 1)
        with audit_disabled():
            setup_church(country="KE")
            self.users = self._users()
            with acting_as(self.users["bookkeeper"]), transaction.atomic():
                self._run()
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write(f"Admin app logins (password: {self.password}):")
        for username, _, _, role, _ in STAFF_USERS:
            self.stdout.write(f"  {username:<11} {role}")
        self.stdout.write(f"Members app logins (same password): {', '.join(self.portal_usernames)}")

    # ------------------------------------------------------------------ helpers

    def _users(self):
        users = {}
        for username, first, last, role, superuser in STAFF_USERS:
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": first, "last_name": last, "email": f"{username}@lifesource.example",
                "is_staff": superuser, "is_superuser": superuser,
            })
            if created:
                user.set_password(self.password)
                user.save()
            user.groups.add(AuthGroup.objects.get(name=role))
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

    def mpesa_code(self):
        return "".join(self.rng.choices(string.ascii_uppercase + string.digits, k=10))

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
        profile.address = "Ngong Road, opposite Prestige Plaza\nP.O. Box 12345-00100\nNairobi, Kenya"
        profile.phone = "+254 712 345 678"
        profile.email = "office@lifesource.example"
        profile.website = "lifesource.example"
        profile.tax_id = "P051234567X"
        profile.treasurer_name = "Esther Wambui"
        profile.expense_approval_threshold = D("50000")
        profile.save()

        checking, savings = self.acct("1010"), self.acct("1020")
        checking.name, checking.bank_name, checking.bank_account_last4 = "Equity Bank – Current Account", "Equity Bank", "4471"
        savings.name, savings.bank_name, savings.bank_account_last4 = "KCB – Building Fund Savings", "KCB Bank", "9032"
        checking.save()
        savings.save()

        self._opening_balances()
        self._fixed_assets()
        members = self._members()
        self._groups(members)
        self._portal_logins(members)
        donors = self._donors(members)
        self._campaign(donors)
        self._giving(donors)
        vendors = self._vendors()
        self._employees()
        self._monthly_activity(vendors)
        self._depreciation()
        self._budget()
        self._reconciliations()
        self._recent_workflow(vendors)
        self._sermons()
        profile.lock_date = date(self.today.year - 1, 12, 31)
        profile.save()

    # ---------------------------------------------------------------- accounts

    def _opening_balances(self):
        from ledger.services import record_opening_balances

        gen, bld, mis, ben, yth = (self.fund(c) for c in ["GEN", "BLD", "MIS", "BEN", "YTH"])
        opening = self.start - timedelta(days=1)
        self.opening_date = opening
        months_built = (opening.year - 2008) * 12 + (opening.month - 6) + 1
        self.building_prior = q2(D("115000000") / 480 * months_built)
        months_sound = (opening.year - 2022) * 12 + (opening.month - 9) + 1
        self.sound_prior = q2(D("4200000") / 60 * months_sound)
        record_opening_balances(date=opening, user=self.users["treasurer"], rows=[
            (self.acct("1010"), gen, D("4285000")),
            (self.acct("1010"), ben, D("215000")),
            (self.acct("1020"), bld, D("11840000")),
            (self.acct("1020"), mis, D("630000")),
            (self.acct("1020"), yth, D("390000")),
            (self.acct("1050"), gen, D("30000")),
            (self.acct("1500"), gen, D("45000000")),
            (self.acct("1510"), gen, D("115000000")),
            (self.acct("1530"), gen, D("4200000")),
            (self.acct("1590"), gen, -(self.building_prior + self.sound_prior)),
            (self.acct("2500"), gen, D("41200000")),
        ])

    def _fixed_assets(self):
        from fixedassets.models import FixedAsset

        gen = self.fund("GEN")
        common = {"accumulated_account": self.acct("1590"), "expense_account": self.acct("8100"), "fund": gen}
        FixedAsset.objects.create(name="Church land, Ngong Road (2 acres)", category="land", acquisition_date=date(2007, 3, 1),
                                  in_service_date=date(2007, 3, 1), cost=D("45000000"), useful_life_months=0,
                                  asset_account=self.acct("1500"), location="Ngong Road, Nairobi", tag_number="LR 209/1234", **common)
        FixedAsset.objects.create(name="Sanctuary & education block", category="building", acquisition_date=date(2008, 6, 1),
                                  in_service_date=date(2008, 6, 1), cost=D("115000000"), useful_life_months=480,
                                  prior_depreciation=self.building_prior, prior_depreciation_through=self.opening_date,
                                  asset_account=self.acct("1510"), location="Main campus", tag_number="B-001", **common)
        FixedAsset.objects.create(name="Sanctuary sound & projection system", category="av", acquisition_date=date(2022, 9, 15),
                                  in_service_date=date(2022, 9, 15), cost=D("4200000"), useful_life_months=60,
                                  prior_depreciation=self.sound_prior, prior_depreciation_through=self.opening_date,
                                  asset_account=self.acct("1530"), location="Sanctuary", tag_number="AV-014", **common)

    # ----------------------------------------------------------------- members

    def _birth_date(self, low, high):
        age = self.rng.randint(low, high)
        return date(self.today.year - age, self.rng.randint(1, 12), self.rng.randint(1, 28))

    def _members(self):
        from members.models import Member

        members = []
        used = set()
        for i in range(230):
            female = self.rng.random() < 0.57
            while True:
                first = self.rng.choice(WOMEN if female else MEN)
                last = self.rng.choice(SURNAMES)
                if (first, last) not in used and first != last:
                    used.add((first, last))
                    break
            band = self.rng.choices(["child", "teen", "youth", "adult", "senior"], weights=[10, 9, 33, 38, 10])[0]
            dob = self._birth_date(*{"child": (6, 12), "teen": (13, 17), "youth": (18, 35), "adult": (36, 59), "senior": (60, 82)}[band])
            area, town = self.rng.choice(AREAS)
            adult = band in ("youth", "adult", "senior")
            married = adult and self.rng.random() < (0.25 if band == "youth" else 0.7)
            status = self.rng.choices([Member.MEMBER, Member.ATTENDER, Member.VISITOR, Member.INACTIVE, Member.TRANSFERRED],
                                      weights=[72, 14, 6, 6, 2])[0]
            title = ""
            if adult:
                title = self.rng.choice(["Mrs", "Ms"] if married and female else ["Ms", "Miss"] if female else ["Mr"])
                if self.rng.random() < 0.05:
                    title = "Dr"
            m = Member.objects.create(
                title=title, first_name=first, last_name=last, gender=Member.FEMALE if female else Member.MALE,
                date_of_birth=dob if self.rng.random() < 0.93 else None,
                marital_status=("married" if married else "single") if adult else "",
                phone=f"+254 7{self.rng.randint(10, 99)} {self.rng.randint(100, 999)} {self.rng.randint(100, 999)}" if adult else "",
                email=f"{first.lower()}.{last.lower()}@example.co.ke" if adult and self.rng.random() < 0.7 else "",
                residence=area, town=town, county=town, country="Kenya",
                occupation=self.rng.choice(OCCUPATIONS) if adult else "Student",
                status=status, date_joined=date(self.rng.randint(2008, self.today.year), self.rng.randint(1, 12), 1),
                baptized=adult and self.rng.random() < 0.8,
            )
            m.adult = adult
            m.band = band
            members.append(m)
        # A few gender-unspecified records, and one with no recorded gender preference
        for m in self.rng.sample([m for m in members if m.adult], 3):
            m.gender = Member.UNSPECIFIED
            m.save(update_fields=["gender"])
        return members

    def _portal_logins(self, members):
        """Members-app logins for ten members who belong to a few groups."""
        from members.models import GroupMembership, Member

        self.portal_usernames = []
        active = GroupMembership.objects.filter(status=GroupMembership.ACTIVE)
        candidates = [m for m in members if m.adult and m.status == Member.MEMBER and active.filter(member=m).count() >= 2]
        for m in candidates[:10]:
            username = f"{m.first_name}.{m.last_name}".lower().replace("'", "")
            m.user = User.objects.create_user(username, m.email, self.password, first_name=m.first_name, last_name=m.last_name)
            m.save(update_fields=["user"])
            self.portal_usernames.append(username)

    def _groups(self, members):
        from members import services
        from members.models import Group, GroupMembership, Member

        G = Group
        specs = [
            ("Women's Fellowship", G.FELLOWSHIP, Member.FEMALE, 18, None, "saturday", time(14, 0), "monthly", "Main hall",
             "Women encouraging one another in faith, family and work. Bible study, prayer and outreach."),
            ("Men's Fellowship", G.FELLOWSHIP, Member.MALE, 18, None, "saturday", time(7, 0), "monthly", "Fellowship hall",
             "Men's breakfast, Bible study and mentorship. Iron sharpens iron."),
            ("Youth Fellowship", G.FELLOWSHIP, G.ANYONE, 18, 35, "friday", time(18, 0), "weekly", "Youth centre",
             "Young adults growing in faith together: worship, Bible study, careers and service."),
            ("Teens Ministry", G.MINISTRY, G.ANYONE, 13, 17, "sunday", time(9, 0), "weekly", "Room 4",
             "Teens' church during the main service."),
            ("Couples Fellowship", G.FELLOWSHIP, G.ANYONE, 18, None, "sunday", time(15, 0), "monthly", "Main hall",
             "Building strong, Christ-centred marriages."),
            ("Praise & Worship Team", G.WORSHIP, G.ANYONE, 15, None, "thursday", time(18, 0), "weekly", "Sanctuary",
             "Singers and instrumentalists leading Sunday worship."),
            ("Church Choir", G.WORSHIP, G.ANYONE, 12, None, "saturday", time(10, 0), "weekly", "Sanctuary", ""),
            ("Ushering & Hospitality", G.MINISTRY, G.ANYONE, 16, None, "sunday", time(7, 30), "weekly", "Main entrance",
             "Welcoming everyone who walks through our doors."),
            ("Sunday School Teachers", G.MINISTRY, G.ANYONE, 18, None, "sunday", time(8, 30), "weekly", "Children's wing", ""),
            ("Media & Tech Team", G.MINISTRY, G.ANYONE, 15, None, "sunday", time(7, 30), "weekly", "Media booth",
             "Sound, projection, livestream and photography."),
            ("New Members' Class", G.CLASS, G.ANYONE, 13, None, "sunday", time(13, 0), "weekly", "Room 2",
             "Six-week class for people who want to become members."),
            ("Church Council", G.COMMITTEE, G.ANYONE, 21, None, "varies", None, "monthly", "Board room", ""),
        ]
        for cell in sorted(set(CELLS.values())):
            specs.append((cell, G.CELL, G.ANYONE, None, None, "wednesday", time(19, 0), "weekly", "Hosted in members' homes",
                          "Mid-week prayer, Bible study and care for one another in the neighbourhood."))
        groups = {}
        for name, kind, gender, lo, hi, day, at, freq, place, desc in specs:
            groups[name] = G.objects.create(
                name=name, group_type=kind, gender_restriction=gender, min_age=lo, max_age=hi, meeting_day=day,
                meeting_time=at, meeting_frequency=freq, meeting_place=place, description=desc,
                open_to_requests=kind != G.COMMITTEE,
            )
        secretary = self.users["secretary"]
        current = [m for m in members if m.is_current]

        def induct(member, group_name, chance, role="member"):
            if self.rng.random() >= chance:
                return
            group = groups[group_name]
            if group.eligibility(member)[0]:
                when = max(member.date_joined or self.start, date(2015, 1, 1)) + timedelta(days=self.rng.randint(20, 400))
                try:
                    services.induct(member, group, secretary, role, min(when, self.today))
                except services.MembershipError:
                    pass

        for m in current:
            induct(m, "Women's Fellowship", 0.6)
            induct(m, "Men's Fellowship", 0.5)
            induct(m, "Youth Fellowship", 0.6)
            induct(m, "Teens Ministry", 0.8)
            if m.marital_status == "married":
                induct(m, "Couples Fellowship", 0.4)
            if m.adult:
                induct(m, CELLS[m.residence], 0.65)
            induct(m, "Church Choir", 0.07)
            induct(m, "Praise & Worship Team", 0.05)
            induct(m, "Ushering & Hospitality", 0.07)
            induct(m, "Sunday School Teachers", 0.05)
            induct(m, "Media & Tech Team", 0.03)
        council = [m for m in current if m.adult and m.band in ("adult", "senior")]
        for m in self.rng.sample(council, 9):
            induct(m, "Church Council", 1.0)
        # Leaders: everyone gets a chair and secretary chosen from their members
        for group in groups.values():
            active = list(group.memberships.filter(status=GroupMembership.ACTIVE))
            self.rng.shuffle(active)
            for gm, role in zip(active, ["leader", "assistant", "secretary"]):
                gm.role = role
                gm.save(update_fields=["role"])
        # Requests waiting for approval, made from the members app
        for m in self.rng.sample([m for m in current if m.adult], 12):
            options = [CELLS[m.residence], "Church Choir", "Ushering & Hospitality", "Media & Tech Team", "Couples Fellowship"]
            self.rng.shuffle(options)
            for name in options:
                g = groups[name]
                if not g.memberships.filter(member=m).exists() and g.eligibility(m)[0]:
                    services.request_to_join(m, g)
                    break

    # ------------------------------------------------------------------ giving

    def _donors(self, members):
        from giving.models import Donor

        donors = []
        envelope = 101
        givers = [m for m in members if m.adult and m.status != "transferred"]
        for m in givers:
            if self.rng.random() > 0.72:
                continue
            d = Donor.objects.create(
                first_name=m.first_name, last_name=m.last_name, envelope_number=str(envelope) if self.rng.random() < 0.6 else None,
                email=m.email, phone=m.phone, address_line1=m.postal_address or "P.O. Box 12345", city=m.town, state=m.county,
                postal_code="00100", country="Kenya", is_member=m.status == "member", member_since=m.date_joined,
            )
            envelope += 1
            m.donor = d
            m.save(update_fields=["donor"])
            pattern = self.rng.choices(["weekly", "biweekly", "monthly", "occasional"], weights=[40, 15, 30, 15])[0]
            d.pattern = pattern
            d.amount = self.money(*{"weekly": (300, 6000), "biweekly": (500, 8000), "monthly": (2000, 40000), "occasional": (200, 3000)}[pattern], step=100)
            d.method = self.rng.choices(["mobile_money", "cash", "bank_transfer", "check", "card"], weights=[55, 25, 10, 5, 5])[0]
            d.building_share = self.rng.choice([0, 0, 0, D("0.1"), D("0.15"), D("0.25")])
            d.lapse_after = self.today - timedelta(days=self.rng.randint(120, 300)) if self.rng.random() < 0.07 else None
            d.joined = self.start + timedelta(days=self.rng.randint(150, 500)) if self.rng.random() < 0.08 else None
            donors.append(d)
        for name in ["Hope Foundation Kenya", "Baraka Hardware Ltd", "St. Andrew's Partner Church"]:
            d = Donor.objects.create(donor_type=Donor.ORGANIZATION, organization_name=name, city="Nairobi", country="Kenya")
            d.pattern = "org"
            donors.append(d)
        return donors

    def _campaign(self, donors):
        from giving.models import Campaign, Pledge

        start = add_months(self.today.replace(day=1), -10)
        self.campaign = Campaign.objects.create(
            name="Children's Wing Building Campaign", fund=self.fund("BLD"), start_date=start,
            end_date=add_months(start, 24) - timedelta(days=1), goal=D("25000000"),
            description="A new children's wing with classrooms and accessible washrooms.",
        )
        pledgers = [d for d in donors if getattr(d, "pattern", "") in ("weekly", "monthly", "biweekly")]
        for d in self.rng.sample(pledgers, min(30, len(pledgers))):
            amount = self.money(50000, 900000, step=5000)
            Pledge.objects.create(donor=d, campaign=self.campaign, amount=amount, pledge_date=start + timedelta(days=self.rng.randint(0, 40)),
                                  frequency=self.rng.choice(["monthly", "weekly", "quarterly", "once"]))
            d.pledge_monthly = q2(amount / 24)
        Campaign.objects.create(name="Christmas Missions Offering", fund=self.fund("MIS"), start_date=date(self.today.year - 1, 11, 15),
                                end_date=date(self.today.year - 1, 12, 31), goal=D("1500000"), is_active=False,
                                description="Year-end offering for our mission partners in Turkana.")

    def _giving(self, donors):
        from giving.models import Contribution, ContributionBatch
        from giving.services import post_batch

        checking = self.acct("1010")
        gen, bld, mis, ben = (self.fund(c) for c in ["GEN", "BLD", "MIS", "BEN"])
        tithes, offerings, special = self.acct("4000"), self.acct("4010"), self.acct("4060")
        building, missions, benevolence = self.acct("4030"), self.acct("4040"), self.acct("4050")
        cheque_no = 100000
        sundays = list(self.sundays())
        for n, sunday in enumerate(sundays):
            is_last = n == len(sundays) - 1
            batch = ContributionBatch.objects.create(
                date=sunday, description="Sunday services offering (cash, M-Pesa & cheques)", deposit_account=checking,
                counted_by=self.rng.choice(["J. Kamau & M. Otieno", "R. Achieng & K. Mutua", "D. Njoroge & S. Chebet"]),
                created_by=self.users["counter"],
            )
            gifts = []
            special_sunday = (sunday.month == 12 and sunday.day > 17) or (sunday.month in (3, 4) and self.rng.random() < 0.25)
            for d in donors:
                if d.pattern == "org" or (d.lapse_after and sunday > d.lapse_after) or (d.joined and sunday < d.joined):
                    continue
                give = (
                    (d.pattern == "weekly" and self.rng.random() < 0.8)
                    or (d.pattern == "biweekly" and n % 2 == d.pk % 2 and self.rng.random() < 0.9)
                    or (d.pattern == "monthly" and sunday.day <= 7 and self.rng.random() < 0.92)
                    or (d.pattern == "occasional" and self.rng.random() < 0.18)
                )
                if not give:
                    continue
                amount = q2(d.amount * D(str(self.rng.choice([1, 1, 1, 1, 0.8, 1.2, 1.5]))))
                method = d.method
                if method == "mobile_money":
                    ref = self.mpesa_code()
                elif method == "check":
                    cheque_no += 1
                    ref = str(cheque_no)
                else:
                    ref = ""
                gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=gen, account=tithes, amount=amount, method=method, check_number=ref))
                if getattr(d, "pledge_monthly", None) and sunday >= self.campaign.start_date and sunday.day <= 7:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=bld, account=building, amount=d.pledge_monthly, method=method, check_number=ref))
                elif d.building_share and self.rng.random() < 0.3:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=bld, account=building, amount=q2(amount * d.building_share), method=method, check_number=ref))
                if self.rng.random() < 0.06:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=mis, account=missions, amount=self.money(200, 5000, 100), method=method, check_number=ref))
                if special_sunday and self.rng.random() < 0.5:
                    gifts.append(Contribution(batch=batch, donor=d, date=sunday, fund=mis if sunday.month == 12 else gen, account=special,
                                              amount=self.money(500, 10000, 100), method=method, check_number=ref, memo="Special offering"))
            gifts.append(Contribution(batch=batch, date=sunday, fund=gen, account=offerings, amount=self.money(18000, 65000, 50), method="cash", memo="Loose offering (basket)"))
            if sunday.day <= 7:
                gifts.append(Contribution(batch=batch, date=sunday, fund=ben, account=benevolence, amount=self.money(15000, 60000, 50), method="cash", memo="Holy Communion benevolence offering"))
            Contribution.objects.bulk_create(gifts)
            batch.control_total = sum(g.amount for g in gifts)
            batch.save()
            if not is_last:
                post_batch(batch, self.users["bookkeeper"])

        orgs = [d for d in donors if d.pattern == "org"]
        for month in self.month_starts():
            end = month_end(month)
            if end >= self.today or month.month not in (6, 12):
                continue
            batch = ContributionBatch.objects.create(date=end, description=f"Partner gifts by bank transfer – {month:%B %Y}",
                                                     deposit_account=checking, created_by=self.users["bookkeeper"])
            Contribution.objects.bulk_create([
                Contribution(batch=batch, donor=org, date=end, fund=self.rng.choice([bld, mis, gen]), account=self.acct("4020"),
                             amount=self.money(50000, 500000, 5000), method="bank_transfer") for org in orgs
            ])
            post_batch(batch, self.users["bookkeeper"])

    # ---------------------------------------------------------------- spending

    def _vendors(self):
        from expenses.models import Vendor

        rows = [
            ("Kenya Power (KPLC)", "6010", False), ("Nairobi City Water & Sewerage", "6010", False),
            ("Safaricom Business", "8020", False), ("Pan-Africa Insurance Brokers", "6040", False),
            ("Equity Bank – Building Loan", "6000", False), ("Google Workspace & Zoom", "8030", False),
            ("Text Book Centre", "8000", False), ("Usafi Cleaning Supplies", "6030", False),
            ("Keswick Books & Gifts", "7010", False), ("Mwangi Plumbing & Electrical", "6020", True),
            ("Turkana Outreach Mission", "7100", False), ("Mathare Children's Home", "7110", False),
            ("Regional Diocese Office", "8080", False), ("Kamau & Associates CPA", "8050", True),
            ("Rev. Peter Kariuki (guest speaker)", "5050", True), ("Brackenhurst Conference Centre", "7020", False),
            ("Naivas Supermarket", "7050", False), ("SecureGuard Kenya Ltd", "6050", False),
            ("Kenya Revenue Authority (PAYE & Housing Levy)", None, False), ("NSSF", None, False),
            ("Social Health Authority (SHIF)", None, False), ("LifeSource Staff SACCO", None, False),
            ("CMC Motors", None, False),
        ]
        vendors = {}
        for name, account, tax_form in rows:
            vendors[name] = Vendor.objects.create(name=name, default_account=self.acct(account) if account else None, is_1099=tax_form,
                                                  tax_id=f"P05{self.rng.randint(1000000, 9999999)}{self.rng.choice('ABCDEFGHJKLMNPQRTUVWXYZ')}" if tax_form else "")
        return vendors

    def _employees(self):
        from payroll.models import Employee, EmployeePayrollItem, PayrollItem

        gen = self.fund("GEN")
        statutory = ["NSSF – Employee", "SHIF", "Housing Levy – Employee", "PAYE", "NSSF – Employer", "Housing Levy – Employer"]
        items = {i.name: i for i in PayrollItem.objects.all()}
        staff = [
            ("Samuel", "Kiprono", "Senior Pastor", "clergy", "salary", D("1680000"), D("0"), D("0"), D("480000"), "5000", {"SACCO / Welfare Deduction": 10000}),
            ("Grace", "Achieng", "Associate & Youth Pastor", "clergy", "salary", D("1020000"), D("0"), D("0"), D("300000"), "5000", {"SACCO / Welfare Deduction": 5000}),
            ("Mercy", "Wanjiru", "Church Administrator", "staff", "salary", D("780000"), D("0"), D("0"), D("0"), "5010", {"SACCO / Welfare Deduction": 4000}),
            ("Brian", "Otieno", "Worship Director (part-time)", "staff", "salary", D("420000"), D("0"), D("0"), D("0"), "5010", {}),
            ("John", "Mutua", "Caretaker", "staff", "salary", D("336000"), D("0"), D("0"), D("0"), "5010", {}),
            ("Rose", "Nyambura", "Cleaner (casual)", "staff", "hourly", D("0"), D("250"), D("104"), D("0"), "5010", {}),
        ]
        for first, last, title, etype, ptype, salary, rate, hours, housing, account, extra in staff:
            e = Employee.objects.create(
                first_name=first, last_name=last, title=title, employee_type=etype, pay_type=ptype, pay_frequency="monthly",
                annual_salary=salary, hourly_rate=rate, default_hours=hours, annual_housing_allowance=housing,
                wage_account=self.acct(account), fund=gen, hire_date=date(self.rng.randint(2012, 2022), self.rng.randint(1, 12), 1),
                email=f"{first.lower()}@lifesource.example", tax_id_last4=str(self.rng.randint(1000, 9999)),
            )
            for name in statutory:
                EmployeePayrollItem.objects.create(employee=e, item=items[name], amount=items[name].default_amount)
            for name, amount in extra.items():
                EmployeePayrollItem.objects.create(employee=e, item=items[name], amount=D(str(amount)))

    def _pay(self, vendor, when, lines, description, reference="", pay=True, method="bank_transfer"):
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
            self.cheque_no += 1
            pay_date = min(when + timedelta(days=self.rng.randint(3, 12)), self.today)
            ref = str(self.cheque_no) if method == "check" else (self.mpesa_code() if method == "mobile_money" else f"EFT{self.rng.randint(100000, 999999)}")
            ex.record_payment(expense, self.users["bookkeeper"], date=pay_date, amount=expense.total, pay_from=self.acct("1010"),
                              method=method, reference=ref)
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
        self.cheque_no = 500000
        loan = D("41200000")
        for month in self.month_starts():
            m_end = month_end(month)
            complete = m_end < self.today
            pay_day = month.replace(day=min(28, m_end.day))
            if pay_day <= self.today:
                run = create_run(period_start=month, period_end=m_end, pay_date=pay_day, bank_account=A("1010"), user=self.users["treasurer"],
                                 memo=f"{month:%B %Y} salaries")
                post_run(run, self.users["treasurer"])

            def on(day):
                return month.replace(day=min(day, m_end.day))

            bills = [
                (5, "Kenya Power (KPLC)", [(A("6010"), gen, self.money(18000, 38000, 10), "Electricity")], "Electricity", "mobile_money"),
                (8, "Nairobi City Water & Sewerage", [(A("6010"), gen, self.money(4000, 9500, 10), "Water")], "Water", "mobile_money"),
                (3, "Safaricom Business", [(A("8020"), gen, D("12999.00"), "Fibre internet & phones")], "Internet & phones", "mobile_money"),
                (2, "Google Workspace & Zoom", [(A("8030"), gen, D("9450.00"), "Email & online meetings")], "Software subscriptions", "card"),
                (12, "Usafi Cleaning Supplies", [(A("6030"), gen, self.money(6000, 15000, 50), "Cleaning supplies")], "Cleaning supplies", "mobile_money"),
                (15, "Turkana Outreach Mission", [(A("7100"), mis, D("80000.00"), "Monthly mission support")], "Mission support", "bank_transfer"),
                (20, "Regional Diocese Office", [(A("8080"), gen, D("60000.00"), "Monthly diocesan levy")], "Diocesan levy", "bank_transfer"),
                (22, "SecureGuard Kenya Ltd", [(A("6050"), gen, D("45000.00"), "Guards & alarm response")], "Security", "bank_transfer"),
            ]
            interest = q2(loan * D("0.13") / 12)
            principal = D("600000.00") - interest
            loan -= principal
            bills.append((1, "Equity Bank – Building Loan", [(A("6000"), gen, interest, "Interest"), (A("2500"), gen, principal, "Principal")], "Building loan repayment", "bank_transfer"))
            if month.month % 3 == 1:
                bills.append((6, "Pan-Africa Insurance Brokers", [(A("6040"), gen, D("185000.00"), "Quarterly property & liability cover")], "Insurance premium", "bank_transfer"))
            if self.rng.random() < 0.7:
                bills.append((14, "Text Book Centre", [(A("8000"), gen, self.money(4000, 18000, 50), "Stationery"), (A("8010"), gen, self.money(3000, 12000, 50), "Bulletins & printing")], "Office supplies", "mobile_money"))
            if self.rng.random() < 0.6:
                bills.append((18, "Keswick Books & Gifts", [(A("7010"), gen, self.money(8000, 25000, 50), "Sunday school curriculum"), (A("7030"), gen, self.money(4000, 15000, 50), "Bible study guides")], "Curriculum", "mobile_money"))
            if self.rng.random() < 0.45:
                fund = bld if self.rng.random() < 0.5 else gen
                bills.append((17, "Mwangi Plumbing & Electrical", [(A("6020"), fund, self.money(15000, 180000, 500), "Repairs")], "Building repairs", "check"))
            if self.rng.random() < 0.65:
                bills.append((24, "Mathare Children's Home", [(A("7110"), ben, self.money(20000, 80000, 500), "Food & school fees support")], "Benevolence support", "bank_transfer"))
            if month.month in (2, 5, 8, 11):
                bills.append((26, "Rev. Peter Kariuki (guest speaker)", [(A("5050"), gen, D("15000.00"), "Guest preaching honorarium")], "Guest speaker", "mobile_money"))
            if month.month == 8:
                bills.append((9, "Brackenhurst Conference Centre", [(A("7020"), yth, D("380000.00"), "Youth camp (August holidays)")], "Youth camp", "bank_transfer"))
            if month.month == 12:
                bills.append((11, "Naivas Supermarket", [(A("7050"), gen, D("95400.00"), "Christmas fellowship lunch")], "Christmas lunch", "card"))
            if month.month == 3:
                bills.append((28, "Kamau & Associates CPA", [(A("8050"), gen, D("180000.00"), "Annual audit")], "Annual audit", "bank_transfer"))

            for day, vendor, lines, desc, method in bills:
                when = on(day)
                if when > self.today:
                    continue
                pay = complete or (self.today - when).days > 10
                self._pay(v[vendor], when, lines, desc, reference=f"INV-{when:%y%m}{day:02d}", pay=pay, method=method)

            if complete:
                self._remit_statutory(v, m_end)
                record_income(date=on(9), deposit_account=A("1010"), income_account=A("4200"), fund=gen, amount=D("45000.00"),
                              user=self.users["bookkeeper"], memo="Hall hire – weddings & events")
                record_income(date=m_end, deposit_account=A("1020"), income_account=A("4300"), fund=bld,
                              amount=self.money(60000, 95000, 10), user=self.users["bookkeeper"], memo="Interest on fixed deposit")
                bld_cash = A("1010").balance(end=m_end, fund=bld)
                if bld_cash > 50000:
                    record_bank_transfer(date=m_end, from_account=A("1010"), to_account=A("1020"), amount=bld_cash, fund=bld,
                                         user=self.users["treasurer"], memo="Move building fund gifts to KCB savings")
                if month.month in (3, 6, 9, 12):
                    record_fund_transfer(date=m_end, from_fund=gen, to_fund=mis, amount=D("250000.00"), cash_account=A("1010"),
                                         user=self.users["treasurer"], memo="Council-approved quarterly missions allocation")
                if month.month == 1:
                    record_fund_transfer(date=on(31), from_fund=gen, to_fund=yth, amount=D("300000.00"), cash_account=A("1010"),
                                         user=self.users["treasurer"], memo="Council designation for youth ministry")
        # A church van bought this year
        van_day = date(self.today.year, 4, 18) if self.today >= date(self.today.year, 5, 1) else self.today - timedelta(days=30)
        self._pay(v["CMC Motors"], van_day, [(A("1540"), gen, D("4850000.00"), "Toyota Hiace 14-seater")], "Church van purchase")
        from fixedassets.models import FixedAsset

        FixedAsset.objects.create(name="Toyota Hiace church van (KDQ 482M)", category="vehicle", acquisition_date=van_day, in_service_date=van_day,
                                  cost=D("4850000.00"), salvage_value=D("950000.00"), useful_life_months=60, asset_account=A("1540"),
                                  accumulated_account=A("1590"), expense_account=A("8100"), fund=gen, tag_number="V-003",
                                  serial_number="KDH223-8004512", location="Church compound")

    def _remit_statutory(self, v, as_of):
        """Pay last month's PAYE, Housing Levy, NSSF, SHIF and SACCO deductions by the 9th."""
        gen = self.fund("GEN")
        when = as_of + timedelta(days=9)
        if when > self.today:
            return
        plan = [
            ("Kenya Revenue Authority (PAYE & Housing Levy)", ["2110", "2130"]),
            ("NSSF", ["2100"]),
            ("Social Health Authority (SHIF)", ["2120"]),
            ("LifeSource Staff SACCO", ["2140"]),
        ]
        for vendor, numbers in plan:
            lines = []
            for number in numbers:
                bal = self.acct(number).balance(end=as_of)
                if bal > 0:
                    lines.append((self.acct(number), gen, bal, f"{self.acct(number).name} – {as_of:%B %Y}"))
            if lines:
                self._pay(v[vendor], when, lines, f"Statutory remittance for {as_of:%B %Y}")

    def _depreciation(self):
        from fixedassets.services import run_depreciation

        last_month_end = self.today.replace(day=1) - timedelta(days=1)
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
                                       approved_at=timezone.now(), notes="Approved by the church council and AGM.")
        accounts = {a.pk: a for a in Account.objects.filter(type__in=[Account.INCOME, Account.EXPENSE])}
        totals = {}
        for i, first, last in fiscal_months(fy - 1):
            for account_id, amount in services.account_balances(start=first, end=last, funds=[gen]).items():
                if account_id in accounts:
                    totals.setdefault(account_id, [D("0")] * 12)[i] += amount
        for account_id, months in totals.items():
            account = accounts[account_id]
            factor = D("1.05") if account.type == Account.INCOME else D("1.04")
            annual = q2(sum(months) * factor / 1000) * 1000
            if annual <= 0:
                continue
            shaped = [q2(annual / 12)] * 12
            shaped[-1] += annual - sum(shaped)
            BudgetLine.objects.create(budget=budget, account=account, months=[str(x) for x in shaped])

    def _reconciliations(self):
        from ledger import services

        through = add_months(self.today.replace(day=1), -1) - timedelta(days=1)
        for number in ("1010", "1020"):
            account = self.acct(number)
            d = month_end(self.start)
            while d <= through:
                rec = services.start_reconciliation(account=account, statement_date=d, statement_balance=account.balance(end=d),
                                                    user=self.users["bookkeeper"])
                services.set_cleared(rec, services.reconciliation_candidates(rec).values_list("pk", flat=True))
                services.complete_reconciliation(rec, self.users["bookkeeper"])
                d = month_end(d + timedelta(days=1))

    def _recent_workflow(self, v):
        from expenses import services as ex
        from expenses.models import Expense, ExpenseLine

        gen, yth, bld = self.fund("GEN"), self.fund("YTH"), self.fund("BLD")
        A = self.acct
        pending = Expense.objects.create(vendor=v["Mwangi Plumbing & Electrical"], date=self.today - timedelta(days=3), due_date=self.today + timedelta(days=27),
                                         description="Replace fellowship hall water tank & pump", reference="Q-2231", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=pending, account=A("6020"), fund=bld, amount=D("168500.00"), description="10,000 L tank, pump & installation")
        ex.submit_expense(pending, self.users["bookkeeper"])
        reimb = Expense.objects.create(vendor=v["Naivas Supermarket"], expense_type=Expense.REIMBURSEMENT, date=self.today - timedelta(days=2),
                                       description="Youth overnight prayer snacks (reimburse Pst. Grace)", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=reimb, account=A("7020"), fund=yth, amount=D("61240.00"), description="Food & drinks")
        ex.submit_expense(reimb, self.users["bookkeeper"])
        draft = Expense.objects.create(vendor=v["Text Book Centre"], date=self.today, description="Printer toner", requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=draft, account=A("8000"), fund=gen, amount=D("14620.00"))
        draft.recalculate_total()
        draft.save()
        rejected = Expense.objects.create(vendor=v["Naivas Supermarket"], date=self.today - timedelta(days=9), description="New sofas for the pastor's lounge",
                                          requested_by=self.users["bookkeeper"])
        ExpenseLine.objects.create(expense=rejected, account=A("6020"), fund=gen, amount=D("198000.00"))
        ex.submit_expense(rejected, self.users["bookkeeper"])
        ex.reject_expense(rejected, self.users["treasurer"], "Not in this year's budget — please bring it to the November council meeting.")

    # ----------------------------------------------------------------- sermons

    def _silent_audio(self, seconds=3):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\x00\x00" * 8000 * seconds)
        return buf.getvalue()

    def _sermons(self):
        from members.models import Sermon

        plan = [
            ("Rooted and Built Up in Him", "Colossians 2:6–7", "Rooted in Christ"),
            ("The Supremacy of Christ", "Colossians 1:15–20", "Rooted in Christ"),
            ("Set Your Minds on Things Above", "Colossians 3:1–4", "Rooted in Christ"),
            ("Clothed with Compassion", "Colossians 3:12–17", "Rooted in Christ"),
            ("Faith That Works", "James 2:14–26", "Faith That Works"),
            ("Taming the Tongue", "James 3:1–12", "Faith That Works"),
            ("Wisdom from Above", "James 3:13–18", "Faith That Works"),
            ("The Prayer of Faith", "James 5:13–18", "Faith That Works"),
            ("The Good Shepherd", "John 10:1–18", ""),
            ("Do Not Grow Weary", "Galatians 6:7–10", ""),
        ]
        preachers = ["Rev. Samuel Kiprono", "Pst. Grace Achieng", "Rev. Samuel Kiprono", "Rev. Peter Kariuki"]
        sunday = self.today - timedelta(days=(self.today.weekday() + 1) % 7)
        for i, (title, scripture, series) in enumerate(plan):
            s = Sermon(
                title=title, scripture=scripture, series=series, preacher=preachers[i % len(preachers)],
                date=sunday - timedelta(days=7 * i), created_by=self.users["media"],
                summary=(f"A message from {scripture}. We looked at what the passage meant for its first hearers, "
                         "how it points us to Jesus, and three practical steps for this week."),
            )
            if i < 3:
                s.audio_file.save(f"{title.lower().replace(' ', '-')}.wav", ContentFile(self._silent_audio()), save=False)
                notes = f"{title}\n{scripture}\n\n1. Read the passage together\n2. Discuss: what does this teach us about God?\n3. Pray for one another\n"
                s.notes_file.save(f"{title.lower().replace(' ', '-')}-notes.txt", ContentFile(notes.encode()), save=False)
            s.save()
