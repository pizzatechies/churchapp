import re
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog, Document
from core.permissions import has_cap
from core.testing import ChurchTestCase
from giving.models import Donor
from ledger.models import JournalEntry


class PermissionTests(ChurchTestCase):
    def assertStatus(self, user, url_name, status, *args):
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse(url_name, args=args)).status_code, status, f"{user} {url_name}")

    def test_anonymous_users_are_sent_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("login") + "?next=/")

    def test_offering_counter_is_limited_to_giving(self):
        self.assertStatus(self.counter, "dashboard", 200)
        self.assertStatus(self.counter, "giving:batch_list", 200)
        self.assertStatus(self.counter, "giving:donor_list", 200)
        self.assertStatus(self.counter, "reports:index", 403)
        self.assertStatus(self.counter, "ledger:entry_list", 403)
        self.assertStatus(self.counter, "payroll:run_list", 403)

    def test_viewer_sees_reports_but_not_confidential_data(self):
        self.assertStatus(self.viewer, "reports:balance_sheet", 200)
        self.assertStatus(self.viewer, "giving:donor_list", 403)
        self.assertStatus(self.viewer, "reports:donor_giving", 403)
        self.assertStatus(self.viewer, "payroll:employee_list", 403)
        self.assertStatus(self.viewer, "ledger:entry_create", 403)

    def test_bookkeeper_cannot_change_settings_or_payroll(self):
        self.assertStatus(self.bookkeeper, "ledger:entry_create", 200)
        self.assertStatus(self.bookkeeper, "settings", 403)
        self.assertStatus(self.bookkeeper, "payroll:run_list", 403)
        self.assertStatus(self.bookkeeper, "user_list", 403)

    def test_only_administrators_manage_users(self):
        self.assertStatus(self.treasurer, "user_list", 403)
        self.assertStatus(self.users["Administrator"], "user_list", 200)
        self.assertTrue(has_cap(self.admin, "manage_users"))

    def test_user_form_assigns_roles(self):
        self.client.force_login(self.users["Administrator"])
        self.client.post(reverse("user_create"), {
            "username": "newbie", "first_name": "New", "email": "n@example.com", "is_active": "on",
            "password": "a-long-enough-pass", "roles": ["Bookkeeper"],
        })
        user = User.objects.get(username="newbie")
        self.assertTrue(has_cap(user, "manage_ledger"))
        self.assertFalse(has_cap(user, "manage_settings"))


class AuditTests(ChurchTestCase):
    def test_changes_are_logged_with_user(self):
        self.client.force_login(self.bookkeeper)
        self.client.post(reverse("giving:donor_create"), {"donor_type": "individual", "first_name": "Ann", "last_name": "Lee", "is_active": "on"})
        donor = Donor.objects.get()
        self.client.post(reverse("giving:donor_edit", args=[donor.pk]), {"donor_type": "individual", "first_name": "Anne", "last_name": "Lee", "is_active": "on"})
        logs = AuditLog.objects.filter(model="Donor").order_by("id")
        self.assertEqual([l.action for l in logs], ["create", "update"])
        self.assertEqual(logs[1].user, self.bookkeeper)
        self.assertEqual(logs[1].changes["first_name"], ["Ann", "Anne"])


class SettingsAndBackupTests(ChurchTestCase):
    def test_close_books(self):
        self.client.force_login(self.treasurer)
        self.client.post(reverse("close_books"), {"lock_date": "2026-01-31"})
        from datetime import date

        from ledger.services import LedgerError

        with self.assertRaises(LedgerError):
            self.deposit(10, when=date(2026, 1, 15))

    def test_backup_download(self):
        self.deposit(100)
        self.client.force_login(self.users["Administrator"])
        response = self.client.post(reverse("backup"))
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn(b'"model": "ledger.journalentry"', response.content)


class DocumentTests(ChurchTestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)

    def test_upload_download_and_permissions(self):
        entry = self.deposit(100)
        with override_settings(MEDIA_ROOT=self.media):
            self.client.force_login(self.bookkeeper)
            from django.contrib.contenttypes.models import ContentType

            ct = ContentType.objects.get_for_model(JournalEntry)
            self.client.post(reverse("document_upload", args=[ct.pk, entry.pk]),
                             {"file": SimpleUploadedFile("receipt.pdf", b"%PDF-1.4 test"), "description": "Receipt"})
            doc = Document.objects.get()
            self.assertEqual(self.client.get(reverse("document_download", args=[doc.pk])).status_code, 200)
            self.client.force_login(self.counter)
            self.assertEqual(self.client.get(reverse("document_download", args=[doc.pk])).status_code, 403)


class AppShellTests(ChurchTestCase):
    def test_health_check_is_public_and_names_the_app(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["app"], "Ecclesia Admin")
        self.assertEqual(response.json()["product"], "Ecclesia")

    def test_manifest_and_service_worker(self):
        manifest = self.client.get(reverse("manifest"))
        self.assertEqual(manifest["Content-Type"], "application/manifest+json")
        data = manifest.json()
        self.assertTrue(data["name"].startswith("Ecclesia Admin"))
        self.assertEqual({icon["purpose"] for icon in data["icons"]}, {"any", "maskable"})
        worker = self.client.get(reverse("service_worker"))
        self.assertEqual(worker["Content-Type"], "application/javascript")
        self.assertIn("no-cache", worker["Cache-Control"])
        body = worker.content.decode()
        self.assertIn('"/offline/"', body)
        self.assertIn("never cached", body)

    def test_offline_page(self):
        self.assertContains(self.client.get(reverse("offline")), "offline", status_code=200)

class SiteSmokeTest(TestCase):
    """Load the demo data and visit every reachable page as each role: nothing may error."""

    @classmethod
    def setUpTestData(cls):
        call_command("load_demo_data", password="smoke-test-pass", verbosity=0, stdout=open("/dev/null", "w"))

    def crawl(self, username, limit_per_pattern=2):
        self.client.force_login(User.objects.get(username=username))
        skip = re.compile(r"/(delete|void|post|reopen|submit|approve|reject|duplicate|status|add)/|export=csv|logout|django-admin|/documents/")
        queue, seen, counts = ["/"], set(), {}
        while queue:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            response = self.client.get(url)
            self.assertLess(response.status_code, 500, f"{username}: {url}")
            if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                continue
            for href in re.findall(r'href="(/[^"#]*)"', response.content.decode()):
                href = href.replace("&amp;", "&")
                if skip.search(href) or href.startswith("/static"):
                    continue
                pattern = re.sub(r"\d+", "N", href.split("?")[0])
                if href in seen or counts.get(pattern, 0) >= limit_per_pattern:
                    continue
                counts[pattern] = counts.get(pattern, 0) + 1
                queue.append(href)
        return seen

    def test_admin_can_reach_every_page(self):
        self.assertGreater(len(self.crawl("admin")), 80)

    def test_other_roles_never_hit_errors(self):
        for username in ("treasurer", "bookkeeper", "committee", "counter", "pastor", "secretary", "media"):
            self.crawl(username, limit_per_pattern=1)

    def test_members_app_pages(self):
        from members.models import Member

        member = Member.objects.exclude(user=None).first()
        with self.settings(ROOT_URLCONF="config.urls_portal", LOGIN_REDIRECT_URL="portal:home"):
            self.assertGreater(len(self.crawl(member.user.username)), 8)

    def test_demo_books_balance(self):
        from core.utils import today
        from reports.builders import balance_sheet, trial_balance

        self.assertEqual(balance_sheet(today(), "fund").warnings, [])
        tb = trial_balance(today()).rows[-1].cells
        self.assertEqual(tb[1], tb[2])


@override_settings(DEMO_MODE=True, DEMO_PASSWORD="demo-pass-123")
class DemoModeTests(ChurchTestCase):
    def test_login_page_offers_demo_logins(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'data-demo-login="treasurer"')
        self.assertContains(response, "demo-pass-123")

    def test_logins_cannot_be_changed(self):
        self.client.force_login(self.admin)
        response = self.client.post(reverse("password_change"), {
            "old_password": "test-pass-123", "new_password1": "Another-pass-456", "new_password2": "Another-pass-456",
        })
        self.assertEqual(response.status_code, 302)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("test-pass-123"))
        self.client.post(reverse("user_edit", args=[self.treasurer.pk]), {"username": "hacked"})
        self.treasurer.refresh_from_db()
        self.assertEqual(self.treasurer.username, "treasurer")
        self.assertContains(self.client.get(reverse("dashboard")), "demo church")

    def test_reset_requires_demo_mode(self):
        from django.core.management.base import CommandError

        with self.settings(DEMO_MODE=False), self.assertRaises(CommandError):
            call_command("reset_demo")
