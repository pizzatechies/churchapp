"""
Congregation records: members, groups & fellowships, and sermons.

Nothing in this app is financial. It is shared by the admin app (where staff
manage it) and the members app, Ecclesia Connect (where members see their own
groups, browse fellowships and listen to sermons).
"""

import re
from datetime import date

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.urls import reverse

from core.utils import today


class Member(models.Model):
    FEMALE = "female"
    MALE = "male"
    UNSPECIFIED = "unspecified"
    GENDER_CHOICES = [(FEMALE, "Female"), (MALE, "Male"), (UNSPECIFIED, "Prefer not to say")]

    TITLE_CHOICES = [(t, t) for t in [
        "Mr", "Mrs", "Ms", "Miss", "Dr", "Prof", "Rev", "Pastor", "Bishop", "Apostle", "Evangelist",
        "Elder", "Deacon", "Deaconess",
    ]]
    MARITAL_CHOICES = [
        ("single", "Single"), ("married", "Married"), ("widowed", "Widowed"),
        ("divorced", "Divorced"), ("separated", "Separated"),
    ]

    VISITOR = "visitor"
    ATTENDER = "attender"
    MEMBER = "member"
    INACTIVE = "inactive"
    TRANSFERRED = "transferred"
    DECEASED = "deceased"
    STATUS_CHOICES = [
        (VISITOR, "Visitor"), (ATTENDER, "Regular attender"), (MEMBER, "Full member"),
        (INACTIVE, "Inactive"), (TRANSFERRED, "Transferred out"), (DECEASED, "Deceased"),
    ]
    CURRENT = {VISITOR, ATTENDER, MEMBER}

    AGE_GROUPS = [
        ("children", "Children (0–12)", 0, 12),
        ("teens", "Teens (13–17)", 13, 17),
        ("youth", "Youth (18–35)", 18, 35),
        ("adults", "Adults (36–59)", 36, 59),
        ("seniors", "Seniors (60+)", 60, 200),
    ]

    member_number = models.CharField(max_length=20, unique=True, editable=False)
    title = models.CharField(max_length=20, choices=TITLE_CHOICES, blank=True)
    first_name = models.CharField(max_length=80)
    middle_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80)
    gender = models.CharField(max_length=12, choices=GENDER_CHOICES)
    date_of_birth = models.DateField(null=True, blank=True)
    marital_status = models.CharField(max_length=12, choices=MARITAL_CHOICES, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    residence = models.CharField("Estate / area of residence", max_length=120, blank=True)
    town = models.CharField("Town / city", max_length=80, blank=True)
    county = models.CharField("County / region", max_length=80, blank=True)
    postal_address = models.CharField("Postal address", max_length=120, blank=True)
    country = models.CharField(max_length=80, blank=True, default="Kenya")
    occupation = models.CharField(max_length=120, blank=True)
    national_id = models.CharField("National ID / passport no.", max_length=40, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=MEMBER, db_index=True)
    date_joined = models.DateField("Joined the church", null=True, blank=True)
    baptized = models.BooleanField(default=False)
    baptism_date = models.DateField(null=True, blank=True)
    emergency_contact_name = models.CharField(max_length=120, blank=True)
    emergency_contact_phone = models.CharField(max_length=40, blank=True)
    notes = models.TextField("Pastoral / office notes", blank=True, help_text="Only visible to church staff, never in the members app.")
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="member_profile",
        help_text="Login for the members app.",
    )
    donor = models.OneToOneField(
        "giving.Donor", null=True, blank=True, on_delete=models.SET_NULL, related_name="member",
        help_text="Their giving record (visible to finance staff only).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["last_name", "first_name"]
        indexes = [models.Index(fields=["gender", "status"])]

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        if not self.member_number:
            self.member_number = next_member_number()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("members:member_detail", args=[self.pk])

    @property
    def full_name(self):
        return " ".join(p for p in [self.first_name, self.middle_name, self.last_name] if p)

    @property
    def display_name(self):
        return f"{self.title} {self.full_name}".strip()

    @property
    def initials(self):
        return (self.first_name[:1] + self.last_name[:1]).upper()

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        t = today()
        return t.year - self.date_of_birth.year - ((t.month, t.day) < (self.date_of_birth.month, self.date_of_birth.day))

    @property
    def age_group(self):
        age = self.age
        if age is None:
            return None
        for key, label, low, high in self.AGE_GROUPS:
            if low <= age <= high:
                return key
        return None

    @property
    def age_group_label(self):
        return dict((k, label) for k, label, *_ in self.AGE_GROUPS).get(self.age_group, "Age not recorded")

    @property
    def is_current(self):
        return self.status in self.CURRENT

    def active_memberships(self):
        return self.group_memberships.filter(status=GroupMembership.ACTIVE).select_related("group")

    @classmethod
    def birth_range_for(cls, age_group):
        """(earliest, latest) date of birth for an age group, for filtering."""
        for key, _, low, high in cls.AGE_GROUPS:
            if key == age_group:
                t = today()
                latest = date(t.year - low, t.month, min(t.day, 28))
                earliest = date(t.year - high - 1, t.month, min(t.day, 28))
                return earliest, latest
        return None


def next_member_number():
    numbers = Member.objects.values_list("member_number", flat=True)
    highest = max((int(m.group(1)) for n in numbers if (m := re.search(r"(\d+)$", n or ""))), default=0)
    return f"M{highest + 1:05d}"


class Group(models.Model):
    FELLOWSHIP = "fellowship"
    MINISTRY = "ministry"
    CELL = "cell"
    WORSHIP = "worship"
    CLASS = "class"
    COMMITTEE = "committee"
    TYPE_CHOICES = [
        (FELLOWSHIP, "Fellowship"),
        (MINISTRY, "Ministry / department"),
        (CELL, "Home cell / small group"),
        (WORSHIP, "Choir / worship team"),
        (CLASS, "Class / discipleship"),
        (COMMITTEE, "Committee / board"),
    ]
    TYPE_ICONS = {
        FELLOWSHIP: "bi-people-fill", MINISTRY: "bi-heart-pulse", CELL: "bi-house-heart", WORSHIP: "bi-music-note-beamed",
        CLASS: "bi-book", COMMITTEE: "bi-briefcase",
    }
    ANYONE = "any"
    GENDER_RESTRICTION_CHOICES = [(ANYONE, "Everyone"), (Member.FEMALE, "Women only"), (Member.MALE, "Men only")]
    DAY_CHOICES = [
        ("", "—"), ("monday", "Monday"), ("tuesday", "Tuesday"), ("wednesday", "Wednesday"), ("thursday", "Thursday"),
        ("friday", "Friday"), ("saturday", "Saturday"), ("sunday", "Sunday"), ("varies", "Varies"),
    ]
    FREQUENCY_CHOICES = [
        ("weekly", "Weekly"), ("fortnightly", "Every two weeks"), ("monthly", "Monthly"), ("announced", "As announced"),
    ]

    name = models.CharField(max_length=120, unique=True)
    group_type = models.CharField("Type", max_length=12, choices=TYPE_CHOICES, default=FELLOWSHIP)
    description = models.TextField(blank=True)
    gender_restriction = models.CharField(
        "Open to", max_length=12, choices=GENDER_RESTRICTION_CHOICES, default=ANYONE,
        help_text="e.g. Women's Fellowship: women only. Enforced when members are inducted.",
    )
    min_age = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Optional, e.g. 18 for Youth.")
    max_age = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Optional, e.g. 35 for Youth.")
    meeting_day = models.CharField(max_length=10, choices=DAY_CHOICES, blank=True)
    meeting_time = models.TimeField(null=True, blank=True)
    meeting_frequency = models.CharField(max_length=12, choices=FREQUENCY_CHOICES, default="weekly")
    meeting_place = models.CharField(max_length=150, blank=True)
    open_to_requests = models.BooleanField(
        "Members can ask to join", default=True,
        help_text="Shows a “Request to join” button in the members app. A leader or the church office approves requests.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["group_type", "name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("members:group_detail", args=[self.pk])

    @property
    def icon(self):
        return self.TYPE_ICONS.get(self.group_type, "bi-people")

    @property
    def meeting_summary(self):
        parts = []
        if self.meeting_frequency and self.meeting_frequency != "announced":
            parts.append(self.get_meeting_frequency_display())
        if self.meeting_day:
            parts.append(("on " if parts else "") + self.get_meeting_day_display() + ("s" if self.meeting_frequency == "weekly" and self.meeting_day != "varies" else ""))
        if self.meeting_time:
            parts.append(f"at {self.meeting_time:%I:%M %p}".replace(" 0", " "))
        if self.meeting_frequency == "announced" and not parts:
            parts.append("As announced")
        return " ".join(parts)

    @property
    def audience(self):
        bits = []
        if self.gender_restriction != self.ANYONE:
            bits.append(self.get_gender_restriction_display())
        if self.min_age and self.max_age:
            bits.append(f"ages {self.min_age}–{self.max_age}")
        elif self.min_age:
            bits.append(f"ages {self.min_age}+")
        elif self.max_age:
            bits.append(f"up to age {self.max_age}")
        return ", ".join(bits) or "Everyone"

    def eligibility(self, member):
        """(allowed, reason) for adding this member to the group."""
        if not member.is_current:
            return False, f"{member.full_name} is marked {member.get_status_display().lower()}."
        if self.gender_restriction != self.ANYONE and member.gender != self.gender_restriction:
            return False, f"{self.name} is for {self.get_gender_restriction_display().lower()}."
        age = member.age
        too_young = age is not None and self.min_age is not None and age < self.min_age
        too_old = age is not None and self.max_age is not None and age > self.max_age
        if too_young or too_old:
            return False, f"{self.name} is for {self.audience.lower()} ({member.first_name} is {age})."
        return True, ""

    def active(self):
        return self.memberships.filter(status=GroupMembership.ACTIVE).select_related("member")

    def leaders(self):
        return self.active().exclude(role=GroupMembership.MEMBER).order_by(GroupMembership.role_order())

    def gender_counts(self):
        rows = self.active().values("member__gender").annotate(n=Count("id"))
        counts = {Member.FEMALE: 0, Member.MALE: 0, Member.UNSPECIFIED: 0}
        for r in rows:
            counts[r["member__gender"]] = r["n"]
        counts["total"] = sum(counts.values())
        return counts

    @classmethod
    def with_counts(cls):
        active = Q(memberships__status=GroupMembership.ACTIVE)
        return cls.objects.annotate(
            total=Count("memberships", filter=active),
            women=Count("memberships", filter=active & Q(memberships__member__gender=Member.FEMALE)),
            men=Count("memberships", filter=active & Q(memberships__member__gender=Member.MALE)),
            pending=Count("memberships", filter=Q(memberships__status=GroupMembership.PENDING)),
        )


class GroupMembership(models.Model):
    PENDING = "pending"
    ACTIVE = "active"
    LEFT = "left"
    DECLINED = "declined"
    STATUS_CHOICES = [(PENDING, "Requested"), (ACTIVE, "Active"), (LEFT, "Left"), (DECLINED, "Request declined")]

    MEMBER = "member"
    ROLE_CHOICES = [
        ("leader", "Leader / chairperson"),
        ("assistant", "Assistant leader"),
        ("secretary", "Secretary"),
        ("treasurer", "Treasurer"),
        ("patron", "Patron / overseer"),
        (MEMBER, "Member"),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="memberships")
    member = models.ForeignKey(Member, on_delete=models.CASCADE, related_name="group_memberships")
    role = models.CharField(max_length=12, choices=ROLE_CHOICES, default=MEMBER)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ACTIVE, db_index=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    inducted_on = models.DateField(null=True, blank=True)
    inducted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    left_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = [("group", "member")]
        ordering = ["group__name", "member__last_name"]

    def __str__(self):
        return f"{self.member} in {self.group}"

    @classmethod
    def role_order(cls):
        """Order expression: leader first, then assistant, secretary, treasurer, patron, member."""
        return Case(*[When(role=code, then=Value(i)) for i, (code, _) in enumerate(cls.ROLE_CHOICES)],
                    output_field=IntegerField())


def sermon_audio_path(instance, filename):
    return f"sermons/audio/{instance.date:%Y}/{filename}"


def sermon_video_path(instance, filename):
    return f"sermons/video/{instance.date:%Y}/{filename}"


def sermon_notes_path(instance, filename):
    return f"sermons/notes/{instance.date:%Y}/{filename}"


AUDIO_TYPES = ["mp3", "m4a", "aac", "wav", "ogg", "oga", "opus"]
VIDEO_TYPES = ["mp4", "webm", "mov", "m4v"]
NOTES_TYPES = ["pdf", "doc", "docx", "ppt", "pptx", "txt", "odt"]


class Sermon(models.Model):
    title = models.CharField(max_length=200)
    preacher = models.CharField(max_length=120)
    date = models.DateField(default=today)
    series = models.CharField(max_length=120, blank=True)
    scripture = models.CharField("Scripture reading", max_length=200, blank=True, help_text="e.g. John 15:1–17")
    summary = models.TextField(blank=True)
    video_url = models.URLField(
        "Video link", blank=True,
        help_text="YouTube, Vimeo or Facebook link. Recommended for video: it streams better than uploading large files.",
    )
    audio_file = models.FileField(upload_to=sermon_audio_path, blank=True,
                                  validators=[FileExtensionValidator(AUDIO_TYPES)], help_text="MP3 or M4A recommended.")
    video_file = models.FileField(upload_to=sermon_video_path, blank=True,
                                  validators=[FileExtensionValidator(VIDEO_TYPES)], help_text="MP4 recommended.")
    notes_file = models.FileField("Sermon notes / slides", upload_to=sermon_notes_path, blank=True,
                                  validators=[FileExtensionValidator(NOTES_TYPES)])
    is_published = models.BooleanField("Published to members", default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("members:sermon_edit", args=[self.pk])

    @property
    def embed_url(self):
        """An embeddable player URL for YouTube or Vimeo links (others open in a new tab)."""
        url = self.video_url or ""
        m = re.search(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|shorts/|embed/)|youtu\.be/)([\w-]{11})", url)
        if m:
            return f"https://www.youtube-nocookie.com/embed/{m.group(1)}"
        m = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
        if m:
            return f"https://player.vimeo.com/video/{m.group(1)}"
        return None

    @property
    def has_media(self):
        return bool(self.video_url or self.audio_file or self.video_file)
