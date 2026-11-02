"""Addresses outside any church on the members app: just the church finder."""

from django.urls import path

from core.views import health
from tenants import views

urlpatterns = [
    path("healthz/", health, name="health"),
    path("", views.find_church, name="find_church"),
]

handler403 = "tenants.views.error_403"
handler404 = "tenants.views.error_404"
handler500 = "tenants.views.error_500"
