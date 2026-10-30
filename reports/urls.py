from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.index, name="index"),
    path("balance-sheet/", views.balance_sheet, name="balance_sheet"),
    path("activities/", views.activities, name="activities"),
    path("budget-vs-actual/", views.budget_vs_actual, name="budget_vs_actual"),
    path("trial-balance/", views.trial_balance, name="trial_balance"),
    path("general-ledger/", views.general_ledger, name="general_ledger"),
    path("fund-activity/", views.fund_activity, name="fund_activity"),
    path("functional-expenses/", views.functional_expenses, name="functional_expenses"),
    path("monthly-trend/", views.monthly_trend, name="monthly_trend"),
    path("cash-summary/", views.cash_summary, name="cash_summary"),
    path("giving-summary/", views.giving_summary, name="giving_summary"),
    path("giving-by-donor/", views.donor_giving, name="donor_giving"),
    path("lapsed-donors/", views.lapsed_donors, name="lapsed_donors"),
    path("ap-aging/", views.ap_aging, name="ap_aging"),
    path("payments-by-payee/", views.payments_by_payee, name="payments_by_payee"),
    path("tax-form-payees/", views.tax_form_payees, name="tax_form_payees"),
    path("payroll-summary/", views.payroll_summary, name="payroll_summary"),
    path("payroll-liabilities/", views.payroll_liabilities, name="payroll_liabilities"),
]
