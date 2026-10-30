from django import forms
from django.forms import formset_factory

from core.forms import StyledForm, StyledModelForm
from core.utils import today

from .models import Account, Budget, Fund, JournalEntry


def account_field(queryset=None, **kwargs):
    return forms.ModelChoiceField(queryset=queryset if queryset is not None else Account.objects.filter(is_active=True), **kwargs)


def fund_field(**kwargs):
    kwargs.setdefault("initial", Fund.default)
    return forms.ModelChoiceField(queryset=Fund.objects.filter(is_active=True), **kwargs)


class AccountForm(StyledModelForm):
    class Meta:
        model = Account
        fields = ["number", "name", "type", "subtype", "function", "description", "bank_name", "bank_account_last4", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.has_activity:
            self.fields["type"].disabled = True
            self.fields["type"].help_text = "The type can't change once the account has transactions."
        if self.instance.system_code:
            self.fields["is_active"].disabled = True
            self.fields["is_active"].help_text = "System account used by the app; it can't be deactivated."

    def clean_is_active(self):
        active = self.cleaned_data["is_active"]
        if not active and self.instance.pk and self.instance.balance() != 0:
            raise forms.ValidationError("Only accounts with a zero balance can be deactivated.")
        return active


class FundForm(StyledModelForm):
    class Meta:
        model = Fund
        fields = ["code", "name", "restriction", "default_income_account", "description", "is_default", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_income_account"].queryset = Account.objects.filter(type=Account.INCOME, is_active=True)


class JournalEntryForm(StyledModelForm):
    class Meta:
        model = JournalEntry
        fields = ["date", "memo", "reference"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["date"].initial = today()


class JournalLineForm(StyledForm):
    account = account_field(required=False)
    fund = fund_field(required=False)
    description = forms.CharField(max_length=255, required=False)
    debit = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)
    credit = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].widget.attrs["data-sticky"] = ""
        self.fields["fund"].widget.attrs["data-sticky"] = ""
        self.fields["debit"].widget.attrs["data-col"] = "debit"
        self.fields["credit"].widget.attrs["data-col"] = "credit"

    def clean(self):
        data = super().clean()
        has_amount = bool(data.get("debit") or data.get("credit"))
        if has_amount and not data.get("account"):
            self.add_error("account", "Choose an account.")
        if has_amount and not data.get("fund"):
            self.add_error("fund", "Choose a fund.")
        return data


JournalLineFormSet = formset_factory(JournalLineForm, extra=0, can_delete=True, min_num=2)


class BankTransferForm(StyledForm):
    date = forms.DateField(initial=today)
    from_account = account_field(Account.deposit_accounts(), label="From")
    to_account = account_field(Account.deposit_accounts(), label="To")
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    fund = fund_field(help_text="The fund whose money is moving. Fund balances don't change.")
    reference = forms.CharField(max_length=60, required=False)
    memo = forms.CharField(max_length=255, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from_account"].queryset = Account.deposit_accounts()
        self.fields["to_account"].queryset = Account.deposit_accounts()


class FundTransferForm(StyledForm):
    date = forms.DateField(initial=today)
    from_fund = fund_field(label="From fund")
    to_fund = fund_field(label="To fund", initial=None)
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    cash_account = account_field(
        Account.deposit_accounts(), label="Bank account",
        help_text="The bank account where the money is held (it stays there; only its fund changes).",
    )
    memo = forms.CharField(max_length=255, required=False, help_text="e.g. “Board-approved transfer for missions”")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cash_account"].queryset = Account.deposit_accounts()


class IncomeForm(StyledForm):
    date = forms.DateField(initial=today)
    deposit_account = account_field(Account.deposit_accounts(), label="Deposited to")
    income_account = account_field(Account.objects.filter(type=Account.INCOME, is_active=True), label="Income category")
    fund = fund_field()
    amount = forms.DecimalField(max_digits=14, decimal_places=2, min_value=0.01)
    reference = forms.CharField(max_length=60, required=False, label="Reference / deposit slip")
    memo = forms.CharField(max_length=255, required=False, label="Received from / description")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deposit_account"].queryset = Account.deposit_accounts()
        self.fields["income_account"].queryset = Account.objects.filter(type=Account.INCOME, is_active=True)


class OpeningBalanceLineForm(StyledForm):
    account = account_field(required=False)
    fund = fund_field(required=False)
    balance = forms.DecimalField(max_digits=14, decimal_places=2, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.objects.filter(
            is_active=True, type__in=[Account.ASSET, Account.LIABILITY, Account.EQUITY],
        ).exclude(system_code__in=[Account.SYS_NET_ASSETS, Account.SYS_NET_ASSETS_RESTRICTED, Account.SYS_INTERFUND])
        self.fields["account"].widget.attrs["data-sticky"] = ""
        self.fields["fund"].widget.attrs["data-sticky"] = ""
        self.fields["balance"].widget.attrs["data-col"] = "amount"


OpeningBalanceFormSet = formset_factory(OpeningBalanceLineForm, extra=0, can_delete=True, min_num=1)


class OpeningBalanceForm(StyledForm):
    date = forms.DateField(help_text="Usually the day before you start recording transactions in this system.")


class VoidForm(StyledForm):
    reason = forms.CharField(max_length=255, label="Reason for voiding")


class ReconciliationStartForm(StyledForm):
    account = account_field(Account.payment_accounts(), label="Account")
    statement_date = forms.DateField(label="Statement ending date")
    statement_balance = forms.DecimalField(max_digits=14, decimal_places=2, label="Statement ending balance")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = Account.payment_accounts()


class BudgetForm(StyledModelForm):
    copy_from = forms.ModelChoiceField(
        queryset=Budget.objects.all(), required=False, label="Start from an existing budget",
        help_text="Copies its amounts. Leave blank to start from last year's actual figures.",
    )
    blank = forms.BooleanField(required=False, label="Start with an empty budget")

    class Meta:
        model = Budget
        fields = ["fiscal_year", "fund", "name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        from core.utils import fiscal_year_choices, fiscal_year_of

        super().__init__(*args, **kwargs)
        self.fields["fiscal_year"] = forms.TypedChoiceField(
            choices=fiscal_year_choices(span_back=2, span_forward=2), coerce=int, label="Fiscal year",
            initial=fiscal_year_of(today()) + (1 if today().month >= 10 else 0),
        )
        self.fields["fiscal_year"].widget.attrs["class"] = "form-select"
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)
        self.fields["fund"].initial = Fund.default

    def clean(self):
        data = super().clean()
        if data.get("fiscal_year") and data.get("fund"):
            if Budget.objects.filter(fiscal_year=data["fiscal_year"], fund=data["fund"]).exists():
                raise forms.ValidationError("A budget for this fund and fiscal year already exists.")
        return data
