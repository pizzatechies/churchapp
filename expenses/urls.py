from django.urls import path

from . import views

app_name = "expenses"

urlpatterns = [
    path("", views.expense_list, name="expense_list"),
    path("new/", views.expense_edit, name="expense_create"),
    path("approvals/", views.approvals, name="approvals"),
    path("e/<int:pk>/", views.expense_detail, name="expense_detail"),
    path("e/<int:pk>/edit/", views.expense_edit, name="expense_edit"),
    path("e/<int:pk>/submit/", views.expense_submit, name="expense_submit"),
    path("e/<int:pk>/approve/", views.expense_approve, name="expense_approve"),
    path("e/<int:pk>/reject/", views.expense_reject, name="expense_reject"),
    path("e/<int:pk>/void/", views.expense_void, name="expense_void"),
    path("e/<int:pk>/delete/", views.expense_delete, name="expense_delete"),
    path("e/<int:pk>/duplicate/", views.expense_duplicate, name="expense_duplicate"),
    path("e/<int:pk>/pay/", views.payment_create, name="payment_create"),
    path("payments/<int:pk>/void/", views.payment_void, name="payment_void"),
    path("vendors/", views.vendor_list, name="vendor_list"),
    path("vendors/new/", views.vendor_edit, name="vendor_create"),
    path("vendors/<int:pk>/", views.vendor_detail, name="vendor_detail"),
    path("vendors/<int:pk>/edit/", views.vendor_edit, name="vendor_edit"),
]
