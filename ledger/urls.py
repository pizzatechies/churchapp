from django.urls import path

from . import views

app_name = "ledger"

urlpatterns = [
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_edit, name="account_create"),
    path("accounts/<int:pk>/", views.account_detail, name="account_detail"),
    path("accounts/<int:pk>/edit/", views.account_edit, name="account_edit"),
    path("funds/", views.fund_list, name="fund_list"),
    path("funds/new/", views.fund_edit, name="fund_create"),
    path("funds/<int:pk>/", views.fund_detail, name="fund_detail"),
    path("funds/<int:pk>/edit/", views.fund_edit, name="fund_edit"),
    path("banking/", views.banking, name="banking"),
    path("transfer/", views.bank_transfer, name="bank_transfer"),
    path("transfer/funds/", views.fund_transfer, name="fund_transfer"),
    path("income/", views.record_income, name="record_income"),
    path("journal/", views.entry_list, name="entry_list"),
    path("journal/new/", views.entry_edit, name="entry_create"),
    path("journal/<int:pk>/", views.entry_detail, name="entry_detail"),
    path("journal/<int:pk>/edit/", views.entry_edit, name="entry_edit"),
    path("journal/<int:pk>/post/", views.entry_post, name="entry_post"),
    path("journal/<int:pk>/void/", views.entry_void, name="entry_void"),
    path("journal/<int:pk>/delete/", views.entry_delete, name="entry_delete"),
    path("opening-balances/", views.opening_balances, name="opening_balances"),
    path("reconciliations/", views.reconciliation_list, name="reconciliation_list"),
    path("reconciliations/new/", views.reconciliation_start, name="reconciliation_start"),
    path("reconciliations/<int:pk>/", views.reconciliation_detail, name="reconciliation_detail"),
    path("reconciliations/<int:pk>/reopen/", views.reconciliation_reopen, name="reconciliation_reopen"),
    path("reconciliations/<int:pk>/delete/", views.reconciliation_delete, name="reconciliation_delete"),
    path("budgets/", views.budget_list, name="budget_list"),
    path("budgets/new/", views.budget_create, name="budget_create"),
    path("budgets/<int:pk>/", views.budget_detail, name="budget_detail"),
    path("budgets/<int:pk>/status/", views.budget_status, name="budget_status"),
]
