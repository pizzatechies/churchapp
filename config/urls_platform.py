"""Addresses outside any church on the admin app: the platform console and the church finder."""

from django.urls import include, path

from core.views import health
from tenants import views

urlpatterns = [
    path("healthz/", health, name="health"),
    path("platform/", include("tenants.urls")),
    path("", views.find_church, name="find_church"),
]
