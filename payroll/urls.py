from django.urls import path

from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.run_list, name="run_list"),
    path("runs/new/", views.run_create, name="run_create"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/post/", views.run_post, name="run_post"),
    path("runs/<int:pk>/void/", views.run_void, name="run_void"),
    path("runs/<int:pk>/delete/", views.run_delete, name="run_delete"),
    path("runs/<int:pk>/add/", views.paycheck_add, name="paycheck_add"),
    path("paychecks/<int:pk>/", views.paycheck_edit, name="paycheck_edit"),
    path("paychecks/<int:pk>/stub/", views.paycheck_stub, name="paycheck_stub"),
    path("employees/", views.employee_list, name="employee_list"),
    path("employees/new/", views.employee_edit, name="employee_create"),
    path("employees/<int:pk>/", views.employee_detail, name="employee_detail"),
    path("employees/<int:pk>/edit/", views.employee_edit, name="employee_edit"),
    path("items/", views.item_list, name="item_list"),
    path("items/new/", views.item_edit, name="item_create"),
    path("items/<int:pk>/", views.item_edit, name="item_edit"),
]
