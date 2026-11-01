from django import forms

from core.forms import StyledForm, StyledModelForm
from ledger.models import Account, Fund

from .models import BankConnection

MAX_STATEMENT_BYTES = 5 * 1024 * 1024


class BankConnectionForm(StyledModelForm):
    class Meta:
        model = BankConnection
        fields = ["method", "shortcode", "auto_record_gifts", "default_fund", "default_income_account"]
        widgets = {"method": forms.RadioSelect}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_fund"].queryset = Fund.objects.filter(is_active=True)
        self.fields["default_income_account"].queryset = Account.objects.filter(type=Account.INCOME, is_active=True)

    def clean(self):
        data = super().clean()
        if data.get("method") == BankConnection.MPESA:
            code = (data.get("shortcode") or "").strip()
            if not code.isdigit() or not 5 <= len(code) <= 7:
                self.add_error("shortcode", "Enter the Paybill or Till number (5 to 7 digits).")
            data["shortcode"] = code
        return data


class StatementUploadForm(StyledForm):
    file = forms.FileField(help_text="CSV or OFX from online banking or the M-Pesa business portal, up to 5 MB.")

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > MAX_STATEMENT_BYTES:
            raise forms.ValidationError("The file is larger than 5 MB. Download a shorter period.")
        return f
