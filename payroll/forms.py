from datetime import timedelta

from django import forms
from django.forms import inlineformset_factory

from core.forms import StyledForm, StyledModelForm
from core.utils import today
from ledger.models import Account, Fund

from .models import Employee, EmployeePayrollItem, PayrollItem


class EmployeeForm(StyledModelForm):
    class Meta:
        model = Employee
        fields = [
            "first_name", "last_name", "title", "employee_type", "email", "phone", "address", "tax_id_last4",
            "pay_type", "pay_frequency", "annual_salary", "hourly_rate", "default_hours", "annual_housing_allowance",
            "wage_account", "fund", "hire_date", "termination_date", "is_active", "notes",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 2}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["wage_account"].queryset = Account.objects.filter(type=Account.EXPENSE, subtype="personnel", is_active=True)
        self.fields["fund"].queryset = Fund.objects.filter(is_active=True)
        if not self.instance.pk:
            self.fields["fund"].initial = Fund.default
            self.fields["wage_account"].initial = Account.objects.filter(number="5010").first()

    def clean(self):
        data = super().clean()
        if data.get("pay_type") == Employee.SALARY and not data.get("annual_salary"):
            self.add_error("annual_salary", "Enter the annual salary.")
        if data.get("pay_type") == Employee.HOURLY and not data.get("hourly_rate"):
            self.add_error("hourly_rate", "Enter the hourly rate.")
        return data


class EmployeePayrollItemForm(StyledModelForm):
    class Meta:
        model = EmployeePayrollItem
        fields = ["item", "amount"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["item"].queryset = PayrollItem.objects.filter(is_active=True).exclude(kind=PayrollItem.EARNING)
        self.fields["item"].label_from_instance = lambda i: f"{i.name} ({ {'percent': '%', 'bands': 'tax bands'}.get(i.calculation, 'fixed') })"


EmployeeItemFormSet = inlineformset_factory(
    Employee, EmployeePayrollItem, form=EmployeePayrollItemForm, extra=0, can_delete=True,
)


class BandsField(forms.CharField):
    """Edit tax bands as text: one 'upper limit, rate' per line; leave the limit blank for the top band."""

    widget = forms.Textarea(attrs={"rows": 5, "placeholder": "24000, 10\n32333, 25\n500000, 30\n800000, 32.5\n, 35"})

    def prepare_value(self, value):
        if isinstance(value, list):
            return "\n".join(f"{'' if limit in (None, '') else limit}, {rate}" for limit, rate in value)
        return value

    def to_python(self, value):
        bands = []
        for n, line in enumerate((value or "").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            parts = [p.strip().replace(",", "") for p in line.replace("\t", ",").rsplit(",", 1)] if "," in line else line.split()
            if len(parts) != 2:
                raise forms.ValidationError(f"Line {n}: write 'upper limit, rate' (e.g. 24000, 10).")
            limit, rate = parts
            try:
                rate = float(rate.rstrip("%"))
                limit = float(limit) if limit not in ("", "above", "-") else None
            except ValueError:
                raise forms.ValidationError(f"Line {n}: numbers only, e.g. 24000, 10.")
            bands.append([limit, rate])
        limits = [b[0] for b in bands if b[0] is not None]
        if limits != sorted(limits):
            raise forms.ValidationError("List the bands from lowest to highest.")
        return bands


class PayrollItemForm(StyledModelForm):
    bands = BandsField(required=False, label="Tax bands (monthly)",
                       help_text="One band per line: upper limit, rate %. Leave the limit empty on the last line for 'and above'.")

    class Meta:
        model = PayrollItem
        fields = ["name", "kind", "calculation", "default_amount", "min_amount", "max_amount", "bands", "relief",
                  "reduces_taxable_pay", "expense_account", "liability_account", "in_wage_base", "sort_order", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expense_account"].queryset = Account.objects.filter(type=Account.EXPENSE, is_active=True)
        self.fields["liability_account"].queryset = Account.objects.filter(type=Account.LIABILITY, is_active=True)
        if self.instance.code:
            self.fields["kind"].disabled = True
            self.fields["calculation"].disabled = True


class PayrollRunForm(StyledForm):
    period_start = forms.DateField()
    period_end = forms.DateField()
    pay_date = forms.DateField()
    bank_account = forms.ModelChoiceField(queryset=Account.objects.none(), label="Pay from")
    memo = forms.CharField(max_length=255, required=False)
    employees = forms.ModelMultipleChoiceField(
        queryset=Employee.objects.none(), widget=forms.CheckboxSelectMultiple, required=False,
        help_text="Paychecks are generated from each person's pay setup. You can adjust them before posting.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_account"].queryset = Account.deposit_accounts()
        self.fields["bank_account"].initial = Account.deposit_accounts().filter(subtype="bank").first()
        self.fields["employees"].queryset = Employee.objects.filter(is_active=True)
        self.fields["employees"].initial = list(Employee.objects.filter(is_active=True).values_list("pk", flat=True))
        t = today()
        if t.day <= 15:
            start, end = t.replace(day=1), t.replace(day=15)
        else:
            start = t.replace(day=16)
            end = (t.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        self.fields["period_start"].initial = start
        self.fields["period_end"].initial = end
        self.fields["pay_date"].initial = end

    def clean(self):
        data = super().clean()
        if data.get("period_start") and data.get("period_end") and data["period_end"] < data["period_start"]:
            self.add_error("period_end", "The period ends before it starts.")
        if not data.get("employees"):
            self.add_error("employees", "Choose at least one person.")
        return data


class PaycheckForm(StyledForm):
    """Built dynamically: one amount field per payroll item."""

    hours = forms.DecimalField(max_digits=7, decimal_places=2, required=False)
    check_number = forms.CharField(max_length=40, required=False, label="Cheque / M-Pesa ref")

    def __init__(self, *args, paycheck=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.items = list(PayrollItem.objects.filter(is_active=True) | PayrollItem.objects.filter(
            pk__in=paycheck.lines.values("item")))
        self.items = sorted(set(self.items), key=lambda i: (i.sort_order, i.name))
        current = {l.item_id: l.amount for l in paycheck.lines.all()}
        for item in self.items:
            self.fields[f"item_{item.pk}"] = forms.DecimalField(
                max_digits=14, decimal_places=2, required=False, min_value=0, label=item.name,
                initial=current.get(item.pk),
            )
            self.fields[f"item_{item.pk}"].widget.attrs.update({"step": "0.01", "class": "form-control"})
        self.fields["hours"].initial = paycheck.hours
        self.fields["check_number"].initial = paycheck.check_number

    def grouped(self):
        groups = {PayrollItem.EARNING: [], PayrollItem.DEDUCTION: [], PayrollItem.EMPLOYER: []}
        for item in self.items:
            groups[item.kind].append((item, self[f"item_{item.pk}"]))
        return [
            ("Earnings", groups[PayrollItem.EARNING]),
            ("Employee deductions", groups[PayrollItem.DEDUCTION]),
            ("Employer contributions", groups[PayrollItem.EMPLOYER]),
        ]

    def amounts(self):
        return {item: self.cleaned_data.get(f"item_{item.pk}") or 0 for item in self.items}
