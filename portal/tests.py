"""Ecclesia Connect, the members app. Runs with the members URLconf, exactly as deployed."""

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from core.models import AccountProfile, ChurchProfile
from core.testing import ChurchTestCase
from core.utils import today
from giving.models import Campaign, Contribution, ContributionBatch, Donor, Pledge
from giving.services import post_batch
from ledger.models import Account
from ledger.services import create_entry
from members import services
from members.models import Group, GroupMembership, Member, Sermon
from portal import finances

D = Decimal


@override_settings(ROOT_URLCONF="config.urls_portal", LOGIN_REDIRECT_URL="portal:home")
class MembersAppTests(ChurchTestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Njeri", last_name="Mwangi", gender=Member.FEMALE, date_of_birth=date(1994, 5, 1))
        self.user = services.set_portal_account(self.member, "njeri", "a-good-pass-123")
        AccountProfile.password_set_by_someone_else(self.user, False)  # as if Njeri already chose her own
        self.women = Group.objects.create(name="Women's Fellowship", gender_restriction=Member.FEMALE, description="Prayer & study")
        self.men = Group.objects.create(name="Men's Fellowship", gender_restriction=Member.MALE)
        self.sermon = Sermon.objects.create(title="The Good Shepherd", preacher="Rev. Kiprono", scripture="John 10")
        self.draft = Sermon.objects.create(title="Unpublished", preacher="x", is_published=False)

    def test_first_sign_in_with_an_office_set_password_asks_for_a_new_one(self):
        AccountProfile.password_set_by_someone_else(self.user)
        self.client.post("/login/", {"username": "njeri", "password": "a-good-pass-123"})
        self.assertRedirects(self.client.get("/"), "/profile/password/")
        self.assertContains(self.client.get("/profile/password/"), "Choose your own password")
        self.client.post("/profile/password/", {"old_password": "a-good-pass-123", "new_password1": "Morning-Psalms-4410",
                                                "new_password2": "Morning-Psalms-4410"})
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertFalse(AccountProfile.objects.get(user=self.user).must_change_password)

    def test_login_flow(self):
        self.assertRedirects(self.client.get("/"), "/login/?next=/")
        response = self.client.post("/login/", {"username": "njeri", "password": "a-good-pass-123"})
        self.assertRedirects(response, "/")

    def test_staff_without_member_record_cannot_sign_in(self):
        response = self.client.post("/login/", {"username": "treasurer", "password": "test-pass-123"})
        self.assertContains(response, "linked to a current member record")

    def test_pages_show_nothing_financial_when_giving_is_switched_off(self):
        profile = ChurchProfile.get()
        profile.members_see_own_giving = profile.members_see_finances = False
        profile.save()
        self.client.force_login(self.user)
        for url in ["/", "/groups/", f"/groups/{self.women.pk}/", "/sermons/", f"/sermons/{self.sermon.pk}/", "/profile/", "/profile/password/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            body = response.content.decode()
            for word in ("KSh", "Giving", "Payroll", "Budget", "Donor", "Expense"):
                self.assertNotIn(word, body, f"{word} on {url}")
        for url in ["/giving/", "/church-finances/", "/giving/statement/2026/"]:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_finance_urls_do_not_exist(self):
        self.client.force_login(self.user)
        for url in ["/reports/", "/ledger/journal/", "/giving/donors/", "/payroll/", "/expenses/", "/congregation/members/"]:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_request_to_join_respects_gender(self):
        self.client.force_login(self.user)
        self.client.post(reverse("portal:group_join", args=[self.women.pk]))
        self.assertEqual(GroupMembership.objects.get(group=self.women, member=self.member).status, GroupMembership.PENDING)
        self.client.post(reverse("portal:group_join", args=[self.men.pk]))
        self.assertFalse(GroupMembership.objects.filter(group=self.men).exists())
        self.client.post(reverse("portal:group_cancel", args=[self.women.pk]))
        self.assertFalse(GroupMembership.objects.filter(group=self.women).exists())

    def test_member_list_is_private_to_the_group(self):
        other = Member.objects.create(first_name="Faith", last_name="Chebet", gender=Member.FEMALE)
        services.induct(other, self.women)
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(f"/groups/{self.women.pk}/"), "Chebet")
        services.induct(self.member, self.women)
        self.assertContains(self.client.get(f"/groups/{self.women.pk}/"), "Chebet")

    def test_unpublished_sermons_are_hidden(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/sermons/{self.draft.pk}/").status_code, 404)
        self.assertNotContains(self.client.get("/sermons/"), "Unpublished")

    def test_profile_updates_contact_details_only(self):
        self.client.force_login(self.user)
        self.client.post("/profile/", {"phone": "+254 700 000 111", "email": "njeri@example.com", "gender": "male", "notes": "hack"})
        self.member.refresh_from_db()
        self.assertEqual(self.member.phone, "+254 700 000 111")
        self.assertEqual(self.member.gender, Member.FEMALE)
        self.assertEqual(self.member.notes, "")

    def test_mobile_app_skips_web_splash_and_offers_switch_church(self):
        self.client.force_login(self.user)
        browser = self.client.get("/profile/")
        self.assertContains(browser, 'id="splash"')
        self.assertNotContains(browser, "Switch church")
        app = self.client.get("/profile/", HTTP_USER_AGENT="Mozilla/5.0 (Linux; Android 15) EcclesiaApp/1.0 (Connect)")
        self.assertNotContains(app, 'id="splash"')
        self.assertContains(app, "Switch church")
        self.assertContains(self.client.get(reverse("portal:switch_church")), "index.html#change")

    @override_settings(APP_NAME="Ecclesia Connect")
    def test_health_check_identifies_the_members_app(self):
        response = self.client.get("/healthz/")
        self.assertEqual(response.json()["app"], "Ecclesia Connect")
        self.assertEqual(response.json()["product"], "Ecclesia")
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")

    def test_installable_without_signing_in(self):
        self.assertEqual(self.client.get("/manifest.webmanifest").status_code, 200)
        self.assertEqual(self.client.get("/sw.js").status_code, 200)
        self.assertEqual(self.client.get("/offline/").status_code, 200)


@override_settings(ROOT_URLCONF="config.urls_portal", LOGIN_REDIRECT_URL="portal:home")
class MembersGivingTests(ChurchTestCase):
    """A member's own giving and the church's summary for accountability."""

    def setUp(self):
        self.member = Member.objects.create(first_name="Njeri", last_name="Mwangi", gender=Member.FEMALE)
        self.user = services.set_portal_account(self.member, "njeri", "a-good-pass-123")
        AccountProfile.password_set_by_someone_else(self.user, False)  # as if Njeri already chose her own
        self.mine = Donor.objects.create(first_name="Njeri", last_name="Mwangi", envelope_number="201")
        self.other = Donor.objects.create(first_name="Zawadi", last_name="Otieno", envelope_number="202")
        self.day = today()
        self.profile = ChurchProfile.get()
        self.profile.members_see_own_giving = True
        self.profile.members_see_finances = True
        self.profile.member_finance_period = ChurchProfile.MEMBER_FINANCE_LIVE
        self.profile.treasurer_name = "Grace Achieng"
        self.profile.save()

    def batch(self, gifts, post=True, when=None):
        when = when or self.day
        batch = ContributionBatch.objects.create(date=when, description="Sunday", deposit_account=self.checking)
        for donor, amount in gifts:
            Contribution.objects.create(batch=batch, donor=donor, date=when, fund=self.gen, account=self.tithes,
                                        amount=D(amount), method=Contribution.MOBILE_MONEY, check_number="QAB12")
        if post:
            post_batch(batch, self.bookkeeper)
        return batch

    def spend(self, account, amount, when=None):
        create_entry(date=when or self.day, memo="Spending", user=self.treasurer, lines=[
            self.line(account, self.gen, debit=amount), self.line(self.checking, self.gen, credit=amount),
        ])

    def test_member_sees_only_their_own_posted_gifts(self):
        self.member.donor = self.mine
        self.member.save()
        self.batch([(self.mine, "1234.00"), (self.other, "98765.00")])
        self.batch([(self.mine, "5555.00")], post=False)  # not counted and posted yet
        self.client.force_login(self.user)
        page = self.client.get("/giving/")
        self.assertContains(page, "1,234.00")
        self.assertNotContains(page, "98,765.00")
        self.assertNotContains(page, "Otieno")
        self.assertNotContains(page, "5,555.00")
        statement = self.client.get(f"/giving/statement/{self.day.year}/")
        self.assertContains(statement, "Njeri Mwangi")
        self.assertContains(statement, "1,234.00")
        self.assertNotContains(statement, "98,765.00")
        self.assertNotContains(statement, "Otieno")

    def test_pledge_progress(self):
        self.member.donor = self.mine
        self.member.save()
        campaign = Campaign.objects.create(name="New sanctuary", fund=self.gen, start_date=self.day - timedelta(days=30), goal=D("1000000"))
        Pledge.objects.create(donor=self.mine, campaign=campaign, amount=D("10000"), pledge_date=self.day)
        self.batch([(self.mine, "2500.00")])
        self.client.force_login(self.user)
        page = self.client.get("/giving/")
        self.assertContains(page, "New sanctuary")
        self.assertContains(page, "7,500.00 to go")

    def test_unlinked_member_is_told_to_ask_the_office(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/giving/"), "giving record isn't linked yet")
        self.assertEqual(self.client.get(f"/giving/statement/{self.day.year}/").status_code, 404)

    def test_church_summary_shows_totals_but_no_names_or_salaries(self):
        self.batch([(self.other, "50000.00")])
        self.spend(Account.objects.get(number="5000"), 20000)  # Pastoral Salaries
        self.spend(Account.objects.get(number="5010"), 5000)
        self.spend(self.utilities, 3000)
        self.client.force_login(self.user)
        page = self.client.get("/church-finances/")
        self.assertContains(page, "50,000.00")  # income
        self.assertContains(page, "28,000.00")  # spending
        self.assertContains(page, "22,000.00")  # surplus
        self.assertContains(page, "Staff &amp; personnel")
        self.assertContains(page, "25,000.00")  # all staff costs as one figure
        self.assertNotContains(page, "Pastoral Salaries")
        self.assertNotContains(page, "20,000.00")
        self.assertNotContains(page, "Otieno")
        self.assertContains(page, "Grace Achieng")
        self.assertContains(page, "nobody can approve spending they asked for themselves")

    def test_summary_only_includes_closed_periods_when_asked(self):
        self.profile.member_finance_period = ChurchProfile.MEMBER_FINANCE_CLOSED
        self.profile.save()
        self.client.force_login(self.user)
        self.assertContains(self.client.get("/church-finances/"), "closed the books for the first time")
        self.deposit(700, when=self.day)
        self.deposit(1100, when=self.day + timedelta(days=1))
        self.profile.refresh_from_db()
        self.profile.lock_date = self.day
        self.profile.save()
        page = self.client.get("/church-finances/")
        self.assertContains(page, "700.00")
        self.assertNotContains(page, "1,800.00")

    def test_default_cut_off_is_the_end_of_last_month(self):
        self.profile.member_finance_period = ChurchProfile.MEMBER_FINANCE_MONTH
        with mock.patch("portal.finances.today", return_value=date(2026, 3, 15)):
            self.assertEqual(finances.cutoff_date(self.profile), date(2026, 2, 28))
        self.profile.member_finance_period = ChurchProfile.MEMBER_FINANCE_CLOSED
        self.profile.lock_date = date(2026, 1, 31)
        with mock.patch("portal.finances.today", return_value=date(2026, 3, 15)):
            self.assertEqual(finances.cutoff_date(self.profile), date(2026, 1, 31))

    def test_each_part_has_its_own_switch(self):
        self.client.force_login(self.user)
        self.profile.members_see_finances = False
        self.profile.save()
        self.assertRedirects(self.client.get("/church-finances/"), "/giving/")
        self.assertNotContains(self.client.get("/giving/"), "Church finances")
        self.profile.members_see_finances = True
        self.profile.members_see_own_giving = False
        self.profile.save()
        self.assertRedirects(self.client.get("/giving/"), "/church-finances/")
        self.assertContains(self.client.get("/"), "Giving")
