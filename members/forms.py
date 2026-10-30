from django import forms
from django.conf import settings

from core.forms import StyledForm, StyledModelForm
from core.utils import today

from .models import Group, GroupMembership, Member, Sermon


class MemberForm(StyledModelForm):
    class Meta:
        model = Member
        fields = [
            "title", "first_name", "middle_name", "last_name", "gender", "date_of_birth", "marital_status",
            "phone", "email", "residence", "town", "county", "postal_address", "country", "occupation", "national_id",
            "status", "date_joined", "baptized", "baptism_date", "emergency_contact_name", "emergency_contact_phone", "notes",
        ]

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get("date_of_birth")
        if dob and dob > today():
            raise forms.ValidationError("The date of birth is in the future.")
        return dob


class GroupForm(StyledModelForm):
    class Meta:
        model = Group
        fields = [
            "name", "group_type", "description", "gender_restriction", "min_age", "max_age",
            "meeting_day", "meeting_time", "meeting_frequency", "meeting_place", "open_to_requests", "is_active",
        ]
        widgets = {"meeting_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def clean(self):
        data = super().clean()
        if data.get("min_age") and data.get("max_age") and data["min_age"] > data["max_age"]:
            self.add_error("max_age", "The maximum age is below the minimum age.")
        return data


class MemberChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, m):
        return f"{m.last_name}, {m.first_name} ({m.member_number})"


class InductForm(StyledForm):
    """Induct one member into a group (from the member's page)."""

    group = forms.ModelChoiceField(queryset=Group.objects.filter(is_active=True))
    role = forms.ChoiceField(choices=GroupMembership.ROLE_CHOICES, initial=GroupMembership.MEMBER)
    inducted_on = forms.DateField(initial=today, label="Inducted on")


class BulkInductForm(StyledForm):
    """Induct several members into one group (from the group's page)."""

    members = forms.ModelMultipleChoiceField(queryset=Member.objects.none(), widget=forms.SelectMultiple(attrs={"size": 10}))
    role = forms.ChoiceField(choices=GroupMembership.ROLE_CHOICES, initial=GroupMembership.MEMBER)
    inducted_on = forms.DateField(initial=today, label="Inducted on")

    def __init__(self, *args, group=None, **kwargs):
        super().__init__(*args, **kwargs)
        current = group.memberships.filter(status=GroupMembership.ACTIVE).values("member") if group else []
        qs = Member.objects.filter(status__in=Member.CURRENT).exclude(pk__in=current)
        if group and group.gender_restriction != Group.ANYONE:
            qs = qs.filter(gender=group.gender_restriction)
        self.fields["members"].queryset = qs
        self.fields["members"].label_from_instance = lambda m: f"{m.last_name}, {m.first_name} · {m.get_gender_display()}{f' · {m.age}' if m.age is not None else ''}"
        self.fields["members"].help_text = "Hold Ctrl (or Cmd) to choose several. Only people eligible for this group are listed."


class PortalAccountForm(StyledForm):
    username = forms.CharField(max_length=150)
    password = forms.CharField(min_length=8, widget=forms.PasswordInput(render_value=False),
                               help_text="At least 8 characters. Share it privately; they can change it after signing in.")


class SermonForm(StyledModelForm):
    class Meta:
        model = Sermon
        fields = ["title", "preacher", "date", "series", "scripture", "summary", "video_url", "audio_file", "video_file",
                  "notes_file", "is_published"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 4})}

    def clean(self):
        data = super().clean()
        limit = settings.SERMON_MAX_UPLOAD_SIZE
        for name in ("audio_file", "video_file", "notes_file"):
            f = data.get(name)
            if f and hasattr(f, "size") and f.size > limit:
                self.add_error(name, f"Files must be smaller than {limit // (1024 * 1024)} MB. Use a video link for long videos.")
        return data


class MemberImportForm(StyledForm):
    file = forms.FileField(label="CSV file", help_text="UTF-8 CSV with a header row.")
