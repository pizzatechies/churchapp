"""The platform console, separate churches, passwords, forgot password and sign-in protection."""

import re
from datetime import timedelta

from django.contrib.auth.models import User
from django.core import mail
from django.db import connection
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from django_tenants.utils import schema_context, tenant_context

from core.models import AccountProfile
from core.testing import ChurchTestCase
from members.models import Member

from .models import Church, Plan

PLATFORM_PASSWORD = "platform-pass-123"


def make_super_admin(username="owner"):
    with schema_context("public"):
        return User.objects.create_superuser(username, f"{username}@pizzatechnologies.co.ke", PLATFORM_PASSWORD)


class PlatformConsoleTests(ChurchTestCase):
    def setUp(self):
        self.owner = make_super_admin()
        self.test_church = Church.objects.get(slug="test")

    def sign_in(self):
        response = self.client.post("/platform/login/", {"username": "owner", "password": PLATFORM_PASSWORD})
        self.assertRedirects(response, "/platform/", fetch_redirect_response=False)

    def test_only_platform_super_admins_sign_in(self):
        self.assertRedirects(self.client.get("/platform/"), "/platform/login/?next=/platform/", fetch_redirect_response=False)
        # A church administrator's login doesn't exist on the platform.
        response = self.client.post("/platform/login/", {"username": "root", "password": "test-pass-123"})
        self.assertContains(response, "Please enter a correct username and password")
        self.sign_in()
        page = self.client.get("/platform/")
        self.assertContains(page, "Test Church")
        self.assertContains(page, "Monthly recurring revenue")
        # Signing in to the platform doesn't sign anyone in to a church.
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_onboard_a_church_end_to_end(self):
        self.sign_in()
        harvest = Plan.objects.get(code="harvest")
        response = self.client.post("/platform/churches/new/", {
            "name": "Grace Chapel Nakuru", "slug": "", "plan": harvest.pk, "billing_cycle": "yearly", "country": "KE",
            "trial_days": 14, "admin_username": "pastor.john", "admin_email": "john@gracechapel.example", "admin_password": "",
            "contact_name": "John Mwangi", "contact_phone": "0712000000", "contact_email": "", "notes": "",
        })
        self.assertContains(response, "Grace Chapel Nakuru is ready")
        self.assertContains(response, "/church/grace-chapel-nakuru/")
        password = re.search(r'id="temp-pw" class="[^"]*" readonly value="([^"]+)"', response.content.decode()).group(1)
        connection.set_schema_to_public()
        church = Church.objects.get(slug="grace-chapel-nakuru")
        self.assertEqual((church.plan, church.billing_cycle, church.state[0]), (harvest, "yearly", "trial"))
        self.assertEqual(church.price, harvest.monthly_price * 10)

        # Each church has its own records: the new church starts empty, and can't see the test church's members.
        connection.set_tenant(self.test_church)
        Member.objects.create(first_name="Only", last_name="InTest", gender=Member.FEMALE)
        with tenant_context(church):
            self.assertEqual(Member.objects.count(), 0)
            admin = User.objects.get(username="pastor.john")
            self.assertTrue(admin.groups.filter(name="Administrator").exists())
            self.assertTrue(AccountProfile.objects.get(user=admin).must_change_password)
        connection.set_tenant(self.test_church)

        # The new administrator signs in at the church's address and must choose their own password first.
        base = "/church/grace-chapel-nakuru"
        response = self.client.post(f"{base}/accounts/login/", {"username": "pastor.john", "password": password})
        self.assertRedirects(response, f"{base}/", fetch_redirect_response=False)
        self.assertRedirects(self.client.get(f"{base}/"), f"{base}/accounts/password/", fetch_redirect_response=False)
        page = self.client.get(f"{base}/accounts/password/")
        self.assertContains(page, "Choose your own password")
        response = self.client.post(f"{base}/accounts/password/", {
            "old_password": password, "new_password1": "Sunrise-Hymns-7731", "new_password2": "Sunrise-Hymns-7731"})
        self.assertRedirects(response, f"{base}/accounts/profile/", fetch_redirect_response=False)
        dashboard = self.client.get(f"{base}/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, f'href="{base}/settings/subscription/"')
        self.assertNotContains(dashboard, "InTest")

        # Payments extend the paid-up date; suspension pauses the church; the console resets a forgotten password.
        self.client.post(f"/platform/churches/{church.pk}/payment/", {
            "paid_on": timezone.localdate().isoformat(), "amount": "200000", "months": 12, "method": "mpesa", "reference": "SKA12"})
        church.refresh_from_db()
        self.assertEqual(church.status, Church.ACTIVE)
        self.assertGreater(church.paid_until, timezone.localdate() + timedelta(days=360))
        self.client.post(f"/platform/churches/{church.pk}/status/", {"action": "suspend", "reason": "Overdue payment"})
        self.assertContains(self.client.get(f"{base}/accounts/login/"), "is paused", status_code=503)
        self.client.post(f"/platform/churches/{church.pk}/status/", {"action": "reactivate"})
        self.assertEqual(self.client.get(f"{base}/").status_code, 200)
        with tenant_context(church):
            admin_id = User.objects.get(username="pastor.john").pk
        connection.set_tenant(self.test_church)
        page = self.client.post(f"/platform/churches/{church.pk}/reset-admin/", {"user": admin_id})
        self.assertContains(page, "New temporary password for pastor.john")

    def test_church_addresses(self):
        self.assertContains(self.client.get("/church/no-such-church/"), "couldn't find a church", status_code=404)
        self.assertRedirects(self.client.get("/church/test"), "/church/test/", fetch_redirect_response=False)
        self.client.force_login(self.treasurer)
        # The default church answers at the plain address and at its own; links stay inside the address used.
        self.assertEqual(self.client.get("/ledger/banking/").status_code, 200)
        self.assertEqual(self.client.get("/healthz/").json()["church"], "LifeSource Church")

    def test_plan_limits(self):
        seed = Plan.objects.get(code="seed")
        seed.max_members, seed.max_staff = 1, 2
        seed.save()
        connection.set_schema_to_public()
        Church.objects.filter(pk=self.test_church.pk).update(plan=seed)
        connection.set_tenant(Church.objects.get(pk=self.test_church.pk))
        self.client.force_login(self.admin)
        Member.objects.create(first_name="A", last_name="One", gender=Member.FEMALE)
        response = self.client.post(reverse("members:member_create"), {"first_name": "B", "last_name": "Two", "gender": "male",
                                                                       "status": "member", "country": "Kenya"})
        self.assertContains(response, "Seed plan includes up to 1 members")
        self.assertEqual(Member.objects.count(), 1)
        response = self.client.post(reverse("user_create"), {"username": "extra", "password": "A-good-pass-2026",
                                                             "roles": ["Bookkeeper"], "is_active": "on"})
        self.assertContains(response, "staff logins")


@override_settings(EMAIL_CONFIGURED=True, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordTests(ChurchTestCase):
    def test_staff_forgot_password(self):
        self.treasurer.email = "treasurer@lifesource.example"
        self.treasurer.save()
        response = self.client.post(reverse("password_reset"), {"email": "TREASURER@lifesource.example"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].body
        link = re.search(r"https?://testserver(/accounts/password/reset/\S+/)", body).group(1)
        self.assertIn("LifeSource Church", mail.outbox[0].subject)
        form = self.client.get(link, follow=True)
        response = self.client.post(form.redirect_chain[-1][0], {"new_password1": "Fresh-Treasurer-26", "new_password2": "Fresh-Treasurer-26"})
        self.assertRedirects(response, reverse("password_reset_complete"))
        self.assertTrue(self.client.login(username="treasurer", password="Fresh-Treasurer-26"))

    def test_reset_never_reveals_whether_an_address_exists_and_members_use_their_own_app(self):
        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        member = Member.objects.create(first_name="Njeri", last_name="M", gender=Member.FEMALE, email="njeri@example.com")
        from members.services import set_portal_account

        set_portal_account(member, "njeri", "office-set-pass-1")
        # The staff app doesn't send member logins a reset link...
        self.client.post(reverse("password_reset"), {"email": "njeri@example.com"})
        self.assertEqual(len(mail.outbox), 0)
        # ...the members app does.
        with override_settings(ROOT_URLCONF="config.urls_portal"):
            self.client.post("/password/reset/", {"email": "njeri@example.com"})
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("/password/reset/", mail.outbox[0].body)

    @override_settings(EMAIL_CONFIGURED=False)
    def test_without_email_the_page_says_who_to_ask(self):
        self.assertContains(self.client.get(reverse("password_reset")), "Ask your church administrator")

    def test_passwords_set_by_an_administrator_must_be_changed(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("user_create"), {"username": "newbie", "password": "Admin-chose-2026", "roles": ["Bookkeeper"],
                                                  "is_active": "on"})
        newbie = User.objects.get(username="newbie")
        self.assertTrue(AccountProfile.objects.get(user=newbie).must_change_password)
        self.client.force_login(newbie)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("password_change"))
        self.client.post(reverse("password_change"), {"old_password": "Admin-chose-2026", "new_password1": "Mine-only-2026!",
                                                      "new_password2": "Mine-only-2026!"})
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_everyone_edits_their_own_profile(self):
        self.client.force_login(self.treasurer)
        self.client.post(reverse("profile"), {"first_name": "Esther", "last_name": "Wambui", "email": "esther@lifesource.example",
                                              "phone": "+254 700 111 222"})
        self.treasurer.refresh_from_db()
        self.assertEqual((self.treasurer.first_name, self.treasurer.email), ("Esther", "esther@lifesource.example"))
        self.assertEqual(AccountProfile.objects.get(user=self.treasurer).phone, "+254 700 111 222")

    @override_settings(LOGIN_MAX_FAILURES=3)
    def test_sign_in_pauses_after_repeated_wrong_passwords(self):
        for _ in range(3):
            self.client.post(reverse("login"), {"username": "treasurer", "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": "treasurer", "password": "test-pass-123"})
        self.assertContains(response, "sign-in is paused")
        self.assertNotIn("_auth_user_id", self.client.session)


class SuperAdminConsoleTests(ChurchTestCase):
    """The super admin is administrator of every church: enter it, manage its logins, find people, announce."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.owner = make_super_admin()
        self.church = Church.objects.get(slug="test")
        self.client.post("/platform/login/", {"username": "owner", "password": PLATFORM_PASSWORD})

    def test_enter_any_church_as_its_administrator(self):
        from core.limits import staff_count
        from core.models import AuditLog

        before = staff_count()
        response = self.client.post(f"/platform/churches/{self.church.pk}/enter/", {"reason": "Help with payroll"})
        link = response["Location"]
        self.assertTrue(link.startswith("/church/test/accounts/support/"))
        dashboard = self.client.get(link, follow=True)
        self.assertContains(dashboard, "Ecclesia support access")
        self.assertEqual(dashboard.context["user"].username, "support.owner")
        self.assertTrue(dashboard.context["user"].is_superuser)
        self.assertEqual(self.client.get("/church/test/settings/users/").status_code, 200)
        connection.set_tenant(self.church)
        log = AuditLog.objects.get(model="support access")
        self.assertEqual(log.changes, {"super_admin": "owner", "reason": "Help with payroll"})
        self.assertEqual(staff_count(), before)  # support logins never use up the plan's staff logins
        self.assertFalse(User.objects.get(username="support.owner").has_usable_password())
        # The link works once.
        self.client.logout()
        self.assertEqual(self.client.get(link).status_code, 403)
        # Leaving returns to the console, and the visit shows in the church's own Subscription page.
        self.client.post("/platform/login/", {"username": "owner", "password": PLATFORM_PASSWORD})
        self.client.get(self.client.post(f"/platform/churches/{self.church.pk}/enter/")["Location"])
        response = self.client.post("/church/test/accounts/support-leave/")
        self.assertRedirects(response, f"/platform/churches/{self.church.pk}/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/platform/support-log/"), "Help with payroll")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("subscription")), "Help with payroll")

    def test_only_super_admins_can_enter(self):
        self.client.post("/platform/logout/")
        response = self.client.post(f"/platform/churches/{self.church.pk}/enter/")
        self.assertTrue(response["Location"].startswith("/platform/login/"))
        self.assertEqual(self.client.get("/church/test/accounts/support/forged-token/").status_code, 403)

    def test_manage_any_churchs_logins(self):
        url = f"/platform/churches/{self.church.pk}/logins/"
        page = self.client.post(url, {"action": "add", "username": "new.clerk", "email": "clerk@example.com", "role": "Bookkeeper"})
        self.assertContains(page, "new.clerk was added")
        connection.set_tenant(self.church)
        clerk = User.objects.get(username="new.clerk")
        self.assertTrue(clerk.groups.filter(name="Bookkeeper").exists())
        self.assertTrue(AccountProfile.objects.get(user=clerk).must_change_password)
        self.client.post(url, {"action": "role", "user": clerk.pk, "role": "Treasurer"})
        self.client.post(url, {"action": "deactivate", "user": clerk.pk})
        clerk.refresh_from_db()
        self.assertEqual((list(clerk.groups.values_list("name", flat=True)), clerk.is_active), (["Treasurer"], False))
        page = self.client.post(url, {"action": "reset", "user": self.treasurer.pk})
        self.assertContains(page, "New temporary password for treasurer")
        self.assertContains(self.client.get(f"/platform/churches/{self.church.pk}/"), "new.clerk")

    def test_find_people_in_every_church(self):
        page = self.client.get("/platform/people/", {"q": "treasurer"})
        self.assertContains(page, "Test Church")
        self.assertContains(page, "treasurer@example.com")

    def test_announcements_reach_the_churches(self):
        self.client.post("/platform/announcements/", {"message": "Ecclesia will be updated on Saturday at 10pm.", "level": "warning",
                                                      "audience": "staff"})
        self.client.post("/platform/announcements/", {"message": "New: give by M-Pesa in the app", "level": "info", "audience": "members"})
        from django.core.cache import cache

        cache.clear()
        self.client.force_login(self.treasurer)
        page = self.client.get(reverse("dashboard"))
        self.assertContains(page, "Ecclesia will be updated on Saturday")
        self.assertNotContains(page, "give by M-Pesa")
