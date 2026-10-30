"""Ecclesia Connect, the members app. Runs with the members URLconf, exactly as deployed."""

from datetime import date

from django.test import override_settings
from django.urls import reverse

from core.testing import ChurchTestCase
from members import services
from members.models import Group, GroupMembership, Member, Sermon


@override_settings(ROOT_URLCONF="config.urls_portal", LOGIN_REDIRECT_URL="portal:home")
class MembersAppTests(ChurchTestCase):
    def setUp(self):
        self.member = Member.objects.create(first_name="Njeri", last_name="Mwangi", gender=Member.FEMALE, date_of_birth=date(1994, 5, 1))
        self.user = services.set_portal_account(self.member, "njeri", "a-good-pass-123")
        self.women = Group.objects.create(name="Women's Fellowship", gender_restriction=Member.FEMALE, description="Prayer & study")
        self.men = Group.objects.create(name="Men's Fellowship", gender_restriction=Member.MALE)
        self.sermon = Sermon.objects.create(title="The Good Shepherd", preacher="Rev. Kiprono", scripture="John 10")
        self.draft = Sermon.objects.create(title="Unpublished", preacher="x", is_published=False)

    def test_login_flow(self):
        self.assertRedirects(self.client.get("/"), "/login/?next=/")
        response = self.client.post("/login/", {"username": "njeri", "password": "a-good-pass-123"})
        self.assertRedirects(response, "/")

    def test_staff_without_member_record_cannot_sign_in(self):
        response = self.client.post("/login/", {"username": "treasurer", "password": "test-pass-123"})
        self.assertContains(response, "linked to a current member record")

    def test_pages_render_and_show_nothing_financial(self):
        self.client.force_login(self.user)
        for url in ["/", "/groups/", f"/groups/{self.women.pk}/", "/sermons/", f"/sermons/{self.sermon.pk}/", "/profile/", "/profile/password/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            body = response.content.decode()
            for word in ("KSh", "Giving", "Payroll", "Budget", "Donor", "Expense"):
                self.assertNotIn(word, body, f"{word} on {url}")

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
