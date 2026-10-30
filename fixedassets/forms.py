from datetime import timedelta

from django import forms

from core.forms import StyledForm, StyledModelForm
from core.utils import month_end, today
from ledger.models import Account, Fund

from .models import FixedAsset


class FixedAssetForm(StyledModelForm):
    useful_life_years = forms.DecimalField(
        max_digits=5, decimal_places=1, min_value=0, required=False, label="Useful life (years)",
        help_text="0 for land, which is never depreciated.",
    )

    class Meta:
        model = FixedAsset
        fields = [
            "name", "category", "tag_number", "serial_number", "location", "acquisition_date", "in_service_date",
            "cost", "salvage_value", "prior_depreciation", "prior_depreciation_through",
            "asset_account", "accumulated_account", "expense_account", "fund", "description", "notes",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["in_service_date"].required = False
        self.fields["asset_account"].queryset = Account.objects.filter(subtype="fixed_asset", is_active=True)
        self.fields["accumulated_account"].queryset = Account.objects.filter(subtype="accumulated_depreciation", is_active=True)
        self.fields["expense_account"].queryset = Account.objects.filter(type=Account.EXPENSE, is_active=True)
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)
        if self.instance.pk:
            self.fields["useful_life_years"].initial = self.instance.useful_life_months / 12
            if self.instance.depreciation_entries.filter(run__is_void=False).exists():
                for name in ("cost", "salvage_value", "useful_life_years", "in_service_date",
                             "prior_depreciation", "prior_depreciation_through"):
                    self.fields[name].disabled = True
                    self.fields[name].help_text = "Locked because depreciation has been recorded."
        else:
            self.fields["accumulated_account"].initial = Account.objects.filter(system_code=Account.SYS_ACCUM_DEPRECIATION).first()
            self.fields["expense_account"].initial = Account.objects.filter(system_code=Account.SYS_DEPRECIATION).first()
            self.fields["fund"].initial = Fund.default
            self.fields["useful_life_years"].initial = 5

    def clean(self):
        data = super().clean()
        if data.get("salvage_value") and data.get("cost") is not None and data["salvage_value"] > data["cost"]:
            self.add_error("salvage_value", "Salvage value can't exceed the cost.")
        if not data.get("in_service_date"):
            data["in_service_date"] = data.get("acquisition_date")
        if data.get("prior_depreciation") and not data.get("prior_depreciation_through"):
            self.add_error("prior_depreciation_through", "Enter the month-end the prior depreciation covers.")
        if data.get("prior_depreciation") and data.get("cost") is not None:
            if data["prior_depreciation"] > data["cost"] - (data.get("salvage_value") or 0):
                self.add_error("prior_depreciation", "Prior depreciation can't exceed cost minus salvage value.")
        return data

    def save(self, commit=True):
        asset = super().save(commit=False)
        years = self.cleaned_data.get("useful_life_years")
        if years is not None and not self.fields["useful_life_years"].disabled:
            asset.useful_life_months = int(round(years * 12))
        if commit:
            asset.save()
        return asset


class DepreciationRunForm(StyledForm):
    through = forms.DateField(label="Record depreciation through the end of")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        t = today()
        self.fields["through"].initial = month_end(t.replace(day=1) - timedelta(days=1))


class DisposalForm(StyledForm):
    date = forms.DateField(initial=today)
    proceeds = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False, label="Sale proceeds",
                                  help_text="Leave blank if the asset was scrapped, donated or lost.")
    deposit_account = forms.ModelChoiceField(queryset=Account.objects.none(), required=False, label="Proceeds deposited to")
    memo = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit_account"].queryset = Account.deposit_accounts()
