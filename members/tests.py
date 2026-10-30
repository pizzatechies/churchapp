from datetime import date

from django.core.files.base import ContentFile
from django.test import RequestFactory, override_settings
from django.urls import reverse

from core.forms import StaffAuthenticationForm
from core.media import ranged_file_response
from core.testing import ChurchTestCase

from . import services
from .models import Group, GroupMembership, Member, Sermon
from .services import MembershipError


def make_member(first="Wanjiru", last="Kamau", gender=Member.FEMALE, age=30, **kw):
    t = date.today()
    dob = date(t.year - age, 1, 1) if age is not None else None
    return Member.objects.create(first_name=first, last_name=last, gender=gender, date_of_birth=dob, **kw)


class MembershipRuleTests(ChurchTestCase):
    def setUp(self):
        self.women = Group.objects.create(name="Women's Fellowship", gender_restriction=Member.FEMALE, min_age=18)
        self.youth = Group.objects.create(name="Youth Fellowship", min_age=18, max_age=35)
        self.mary = make_member("Mary", "Achieng", Member.FEMALE, 40)
        self.john = make_member("John", "Otieno", Member.MALE, 25)

    def test_member_numbers_are_sequential(self):
        self.assertEqual(self.mary.member_number, "M00001")
        self.assertEqual(self.john.member_number, "M00002")

    def test_gender_restricted_group(self):
        services.induct(self.mary, self.women, self.users["Church Secretary"])
        with self.assertRaisesMessage(MembershipError, "women only"):
            services.induct(self.john, self.women)
        unstated = make_member("Sam", "Kim", Member.UNSPECIFIED, 30)
        with self.assertRaises(MembershipError):
            services.induct(unstated, self.women)
        self.assertEqual(self.women.gender_counts(), {"female": 1, "male": 0, "unspecified": 0, "total": 1})

    def test_age_limits(self):
        services.induct(self.john, self.youth)
        with self.assertRaisesMessage(MembershipError, "is 40"):
            services.induct(self.mary, self.youth)
        no_dob = make_member("Ann", "Juma", Member.FEMALE, None)
        services.induct(no_dob, self.youth)  # unknown age isn't blocked

    def test_inactive_people_cannot_be_inducted(self):
        self.mary.status = Member.TRANSFERRED
        self.mary.save()
        with self.assertRaisesMessage(MembershipError, "transferred out"):
            services.induct(self.mary, self.women)

    def test_request_approve_decline_and_rejoin(self):
        gm = services.request_to_join(self.mary, self.women)
        self.assertEqual(gm.status, GroupMembership.PENDING)
        with self.assertRaisesMessage(MembershipError, "already waiting"):
            services.request_to_join(self.mary, self.women)
        services.decline_request(gm, self.admin, "Please attend one meeting first")
        services.request_to_join(self.mary, self.women)
        gm = services.induct(self.mary, self.women, self.admin, "secretary")
        self.assertEqual((gm.status, gm.role), (GroupMembership.ACTIVE, "secretary"))
        services.remove(gm)
        services.induct(self.mary, self.women)  # can be re-inducted later

    def test_closed_groups_refuse_requests(self):
        self.women.open_to_requests = False
        self.women.save()
        with self.assertRaises(MembershipError):
            services.request_to_join(self.mary, self.women)

    def test_stats_by_gender_and_age(self):
        make_member("Peter", "Kariuki", Member.MALE, 70)
        stats = services.membership_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["by_gender"]["female"], 1)
        seniors = next(r for r in stats["age_rows"] if r["key"] == "seniors")
        self.assertEqual((seniors["male"], seniors["total"]), (1, 1))

    def test_leaders_listed_in_role_order(self):
        a = make_member("Ann", "One", Member.FEMALE, 30)
        b = make_member("Beth", "Two", Member.FEMALE, 30)
        services.induct(a, self.women, role="assistant")
        services.induct(b, self.women, role="leader")
        self.assertEqual([gm.member for gm in self.women.leaders()], [b, a])


class AccountSeparationTests(ChurchTestCase):
    def test_member_login_is_refused_by_the_admin_app(self):
        member = make_member()
        services.set_portal_account(member, "wanjiru", "a-good-pass-123")
        form = StaffAuthenticationForm(data={"username": "wanjiru", "password": "a-good-pass-123"})
        self.assertFalse(form.is_valid())
        self.assertIn("members app", str(form.errors))
        staff_form = StaffAuthenticationForm(data={"username": "treasurer", "password": "test-pass-123"})
        self.assertTrue(staff_form.is_valid())

    def test_portal_usernames_are_unique(self):
        services.set_portal_account(make_member("A", "B"), "same", "pass-12345")
        with self.assertRaisesMessage(MembershipError, "taken"):
            services.set_portal_account(make_member("C", "D"), "SAME", "pass-12345")


class CongregationViewTests(ChurchTestCase):
    def test_secretary_registers_and_inducts(self):
        self.client.force_login(self.users["Church Secretary"])
        self.client.post(reverse("members:member_create"), {
            "first_name": "Akinyi", "last_name": "Odhiambo", "gender": "female", "status": "member", "country": "Kenya",
            "date_of_birth": "1995-04-01",
        })
        member = Member.objects.get()
        self.client.post(reverse("members:group_create"), {
            "name": "Women's Fellowship", "group_type": "fellowship", "gender_restriction": "female",
            "meeting_frequency": "monthly", "open_to_requests": "on", "is_active": "on",
        })
        group = Group.objects.get()
        self.client.post(reverse("members:group_detail", args=[group.pk]), {"members": [member.pk], "role": "member", "inducted_on": "2026-03-01"})
        self.assertTrue(GroupMembership.objects.filter(group=group, member=member, status="active").exists())

    def test_finance_staff_and_members_data_are_separate(self):
        self.client.force_login(self.bookkeeper)
        self.assertEqual(self.client.get(reverse("members:member_list")).status_code, 403)
        self.client.force_login(self.users["Church Secretary"])
        self.assertEqual(self.client.get(reverse("giving:donor_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:index")).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse("members:member_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("members:member_create")).status_code, 403)

    def test_media_team_only_handles_sermons(self):
        self.client.force_login(self.users["Media Team"])
        self.assertEqual(self.client.get(reverse("members:sermon_create")).status_code, 200)
        self.assertEqual(self.client.get(reverse("members:member_list")).status_code, 403)

    def test_member_csv_import(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.users["Church Secretary"])
        csv = b"First Name,Last Name,Gender,Phone,Date of birth\nGrace,Wambui,F,0711000001,1990-02-03\nKevin,Ouma,male,0711000002,\n"
        for _ in range(2):
            self.client.post(reverse("members:member_import"), {"file": SimpleUploadedFile("m.csv", csv, "text/csv")})
        self.assertEqual(Member.objects.count(), 2)
        self.assertEqual(Member.objects.get(first_name="Grace").gender, Member.FEMALE)


class SermonTests(ChurchTestCase):
    def test_embed_urls(self):
        s = Sermon(title="t", preacher="p")
        s.video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"
        self.assertEqual(s.embed_url, "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ")
        s.video_url = "https://youtu.be/dQw4w9WgXcQ"
        self.assertIn("dQw4w9WgXcQ", s.embed_url)
        s.video_url = "https://vimeo.com/123456"
        self.assertEqual(s.embed_url, "https://player.vimeo.com/video/123456")
        s.video_url = "https://facebook.com/live/xyz"
        self.assertIsNone(s.embed_url)

    def test_range_requests_for_audio(self):
        import tempfile

        with override_settings(MEDIA_ROOT=tempfile.mkdtemp()):
            s = Sermon(title="t", preacher="p", date=date(2026, 3, 1))
            s.audio_file.save("t.mp3", ContentFile(b"0123456789" * 10), save=False)
            s.save()
            request = RequestFactory().get("/", HTTP_RANGE="bytes=10-19")
            response = ranged_file_response(request, s.audio_file)
            self.assertEqual(response.status_code, 206)
            self.assertEqual(response["Content-Range"], "bytes 10-19/100")
            self.assertEqual(b"".join(response.streaming_content), b"0123456789")
            self.assertEqual(ranged_file_response(RequestFactory().get("/"), s.audio_file).status_code, 200)
