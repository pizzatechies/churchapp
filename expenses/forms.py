from django import forms
from django.forms import inlineformset_factory

from core.forms import StyledForm, StyledModelForm
from core.utils import today
from ledger.models import Account, Fund

from .models import Expense, ExpenseLine, ExpensePayment, Vendor


def expense_accounts():
    """Accounts an expense line may be charged to: expenses, plus assets/liabilities for purchases and remittances."""
    return (
        Account.objects.filter(is_active=True, type__in=[Account.EXPENSE, Account.ASSET, Account.LIABILITY])
        .exclude(subtype__in=list(Account.PAYMENT_SUBTYPES) + ["accumulated_depreciation"])
        .exclude(system_code=Account.SYS_AP)
    )


class VendorForm(StyledModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "contact_name", "email", "phone", "address", "tax_id", "is_1099", "default_account", "notes", "is_active"]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_account"].queryset = expense_accounts()


class ExpenseForm(StyledModelForm):
    class Meta:
        model = Expense
        fields = ["vendor", "expense_type", "date", "due_date", "reference", "description"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        vendors = Vendor.objects.filter(is_active=True)
        if self.instance.pk:
            vendors = vendors | Vendor.objects.filter(pk=self.instance.vendor_id)
        self.fields["vendor"].queryset = vendors.distinct()
        self.fields["description"].widget.attrs["placeholder"] = "What was purchased and why"

    def clean(self):
        data = super().clean()
        if data.get("due_date") and data.get("date") and data["due_date"] < data["date"]:
            self.add_error("due_date", "The due date is before the invoice date.")
        return data


class ExpenseLineForm(StyledModelForm):
    class Meta:
        model = ExpenseLine
        fields = ["account", "fund", "description", "amount"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = expense_accounts()
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)
        self.fields["fund"].initial = Fund.default
        self.fields["account"].widget.attrs["data-sticky"] = ""
        self.fields["fund"].widget.attrs["data-sticky"] = ""
        self.fields["amount"].widget.attrs["data-col"] = "amount"


ExpenseLineFormSet = inlineformset_factory(
    Expense, ExpenseLine, form=ExpenseLineForm, extra=0, min_num=1, validate_min=True, can_delete=True,
)


class PayNowForm(StyledForm):
    """Optional section on the new-expense form for purchases already paid."""

    paid = forms.BooleanField(required=False, label="This has already been paid")
    pay_from = forms.ModelChoiceField(queryset=Account.objects.none(), required=False, label="Paid from")
    method = forms.ChoiceField(choices=ExpensePayment.METHOD_CHOICES, required=False)
    payment_reference = forms.CharField(max_length=60, required=False, label="Cheque / M-Pesa ref")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pay_from"].queryset = Account.payment_accounts()
        self.fields["pay_from"].initial = Account.payment_accounts().filter(subtype="bank").first()

    def clean(self):
        data = super().clean()
        if data.get("paid") and not data.get("pay_from"):
            self.add_error("pay_from", "Choose the account it was paid from.")
        return data


class PaymentForm(StyledModelForm):
    class Meta:
        model = ExpensePayment
        fields = ["date", "amount", "pay_from", "method", "reference", "memo"]

    def __init__(self, *args, expense=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pay_from"].queryset = Account.payment_accounts()
        if not self.is_bound:
            self.fields["date"].initial = today()
            self.fields["pay_from"].initial = Account.payment_accounts().filter(subtype="bank").first()
            if expense is not None:
                self.fields["amount"].initial = expense.balance_due


class ReviewForm(StyledForm):
    note = forms.CharField(max_length=255, required=False, label="Note")


class VoidReasonForm(StyledForm):
    reason = forms.CharField(max_length=255, label="Reason")
