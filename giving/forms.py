import json

from django import forms

from core.forms import StyledForm, StyledModelForm
from core.utils import today
from ledger.models import Account, Fund

from .models import Campaign, Contribution, ContributionBatch, Donor, Pledge


class DonorSelect(forms.Select):
    """Select that carries each donor's envelope number for quick lookup."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.envelopes = {}

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        key = getattr(value, "value", value)
        if key in self.envelopes:
            option["attrs"]["data-envelope"] = self.envelopes[key]
        return option


class DonorChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        env = f" (#{obj.envelope_number})" if obj.envelope_number else ""
        if obj.donor_type == Donor.ORGANIZATION or not obj.last_name:
            return f"{obj.display_name}{env}"
        return f"{obj.last_name}, {obj.first_name}".strip(", ") + env


class DonorForm(StyledModelForm):
    class Meta:
        model = Donor
        fields = [
            "donor_type", "first_name", "last_name", "organization_name", "envelope_number", "email", "phone",
            "address_line1", "address_line2", "city", "state", "postal_code", "country",
            "is_member", "member_since", "notes", "is_active",
        ]

    def clean(self):
        data = super().clean()
        if data.get("donor_type") == Donor.ORGANIZATION:
            if not data.get("organization_name"):
                self.add_error("organization_name", "Enter the organization's name.")
        elif not (data.get("first_name") or data.get("last_name")):
            self.add_error("last_name", "Enter a name.")
        return data


class BatchForm(StyledModelForm):
    class Meta:
        model = ContributionBatch
        fields = ["date", "description", "deposit_account", "control_total", "counted_by", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit_account"].queryset = Account.deposit_accounts()
        if not self.instance.pk:
            self.fields["date"].initial = today()
            self.fields["description"].initial = "Sunday offering" if today().weekday() == 6 else ""
            self.fields["deposit_account"].initial = Account.deposit_accounts().filter(subtype="bank").first()


class ContributionForm(StyledModelForm):
    donor = DonorChoiceField(queryset=Donor.objects.none(), required=False, widget=DonorSelect,
                             empty_label="Anonymous / loose offering")

    class Meta:
        model = Contribution
        fields = ["donor", "fund", "account", "amount", "method", "check_number", "date", "memo", "is_deductible"]

    def __init__(self, *args, batch=None, **kwargs):
        super().__init__(*args, **kwargs)
        donors = Donor.objects.filter(is_active=True)
        if self.instance.pk and self.instance.donor_id:
            donors = Donor.objects.filter(pk=self.instance.donor_id) | donors
        self.fields["donor"].queryset = donors
        self.fields["donor"].widget.envelopes = dict(donors.exclude(envelope_number=None).values_list("pk", "envelope_number"))
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)
        self.fields["account"].queryset = Account.objects.filter(type=Account.INCOME, is_active=True)
        self.fields["date"].required = False
        self.fields["date"].help_text = "Defaults to the batch date."
        defaults = {str(f.pk): f.default_income_account_id for f in Fund.objects.filter(default_income_account__isnull=False)}
        self.fields["fund"].widget.attrs["data-fund-defaults"] = json.dumps(defaults)
        self.fields["fund"].widget.attrs["data-category-target"] = self["account"].auto_id
        if not self.instance.pk and not self.is_bound:
            fund = Fund.default()
            self.initial.setdefault("fund", fund.pk if fund else None)
            if fund and fund.default_income_account_id:
                self.initial.setdefault("account", fund.default_income_account_id)
        self.batch = batch

    def clean_date(self):
        return self.cleaned_data.get("date") or (self.batch.date if self.batch else today())


class CampaignForm(StyledModelForm):
    class Meta:
        model = Campaign
        fields = ["name", "fund", "start_date", "end_date", "goal", "description", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)


class PledgeForm(StyledModelForm):
    donor = DonorChoiceField(queryset=Donor.objects.filter(is_active=True))

    class Meta:
        model = Pledge
        fields = ["donor", "campaign", "amount", "pledge_date", "frequency", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["pledge_date"].initial = today()


class StatementForm(StyledForm):
    year = forms.TypedChoiceField(coerce=int, required=False, label="Calendar year")
    start = forms.DateField(required=False, label="Or from")
    end = forms.DateField(required=False, label="To")
    donor = DonorChoiceField(queryset=Donor.objects.all(), required=False, empty_label="All donors who gave")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = today().year
        self.fields["year"].choices = [(y, str(y)) for y in range(current, current - 7, -1)]
        self.fields["year"].initial = current - 1 if today().month <= 3 else current

    def period(self):
        from datetime import date

        data = self.cleaned_data
        if data.get("start") and data.get("end"):
            return data["start"], data["end"]
        year = data.get("year") or today().year
        return date(year, 1, 1), date(year, 12, 31)


class DonorImportForm(StyledForm):
    file = forms.FileField(label="CSV file", help_text="UTF-8 CSV with a header row.")
