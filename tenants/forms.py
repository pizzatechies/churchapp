import re

from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify

from core.forms import StyledForm, StyledModelForm
from core.models import COUNTRY_CHOICES

from .models import RESERVED_SLUGS, Church, Domain, Payment, Plan, slug_validator


class ChurchCreateForm(StyledForm):
    name = forms.CharField(max_length=150, label="Church name")
    slug = forms.CharField(max_length=42, label="Web address name", required=False,
                           help_text="Lowercase letters, numbers and hyphens. Leave blank to make one from the name.")
    plan = forms.ModelChoiceField(queryset=Plan.objects.filter(is_active=True), empty_label=None)
    billing_cycle = forms.ChoiceField(choices=Church.CYCLE_CHOICES, initial=Church.MONTHLY)
    country = forms.ChoiceField(choices=COUNTRY_CHOICES, initial="KE")
    trial_days = forms.IntegerField(min_value=0, max_value=90, initial=14, label="Free trial (days)",
                                    help_text="0 for no trial: record their first payment straight after.")
    contact_name = forms.CharField(max_length=120, required=False, label="Main contact")
    contact_phone = forms.CharField(max_length=40, required=False, label="Contact phone")
    contact_email = forms.EmailField(required=False, label="Contact email")
    admin_username = forms.CharField(max_length=150, initial="admin", label="First administrator's username")
    admin_email = forms.EmailField(required=False, label="Administrator's email",
                                   help_text="Lets them reset a forgotten password by email.")
    admin_password = forms.CharField(
        required=False, label="Temporary password", widget=forms.PasswordInput(render_value=True),
        help_text="Leave blank to generate one. Either way they choose their own password at first sign-in.",
    )
    is_default = forms.BooleanField(required=False, label="Also serve this church at the apps' main addresses")
    notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_slug(self):
        slug = (self.cleaned_data.get("slug") or "").strip().lower() or slugify(self.data.get("name", "")).replace("-church", "")
        slug = slug[:40].strip("-")
        slug_validator(slug)
        if slug in RESERVED_SLUGS:
            raise forms.ValidationError("That name is reserved. Choose another.")
        if Church.objects.filter(slug=slug).exists():
            raise forms.ValidationError("Another church already uses this web address name.")
        return slug

    def clean_admin_username(self):
        username = self.cleaned_data["admin_username"].strip()
        if not re.match(r"^[\w.@+-]+$", username):
            raise forms.ValidationError("Use letters, numbers and . @ + - _ only.")
        return username

    def clean_admin_password(self):
        password = self.cleaned_data.get("admin_password")
        if password:
            from django.contrib.auth.password_validation import validate_password

            validate_password(password)
        return password


class ChurchEditForm(StyledModelForm):
    class Meta:
        model = Church
        fields = ["name", "plan", "billing_cycle", "country", "trial_ends", "paid_until", "contact_name", "contact_phone",
                  "contact_email", "is_default", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class PaymentForm(StyledModelForm):
    class Meta:
        model = Payment
        fields = ["paid_on", "amount", "months", "method", "reference", "notes"]

    def __init__(self, *args, church=None, **kwargs):
        super().__init__(*args, **kwargs)
        if church and not self.is_bound:
            self.initial.update({"amount": church.price, "months": 12 if church.billing_cycle == Church.YEARLY else 1,
                                 "paid_on": timezone.localdate()})


class DomainForm(StyledModelForm):
    class Meta:
        model = Domain
        fields = ["domain"]
        help_texts = {"domain": "e.g. members.yourchurch.org. Point its DNS at this server first."}

    def clean_domain(self):
        return self.cleaned_data["domain"].strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")


class PlanForm(StyledModelForm):
    class Meta:
        model = Plan
        fields = ["name", "tagline", "monthly_price", "yearly_months", "max_members", "max_staff", "storage_gb", "custom_domains",
                  "support", "is_active"]


PlanFormSet = forms.modelformset_factory(Plan, form=PlanForm, extra=0)


class TeamMemberForm(StyledForm):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("That username is taken.")
        return username


class AccountForm(StyledModelForm):
    phone = forms.CharField(max_length=40, required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]


class AddLoginForm(StyledForm):
    username = forms.CharField(max_length=150)
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    role = forms.ChoiceField(choices=[])

    def __init__(self, *args, **kwargs):
        from core.permissions import ROLES

        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(r, r) for r in ROLES]

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not re.match(r"^[\w.@+-]+$", username) or username.startswith("support."):
            raise forms.ValidationError("Use letters, numbers and . @ + - _ only.")
        return username


class AnnouncementForm(StyledModelForm):
    class Meta:
        from .models import Announcement

        model = Announcement
        fields = ["message", "level", "audience", "churches", "ends_at"]
        widgets = {"churches": forms.CheckboxSelectMultiple, "ends_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}
