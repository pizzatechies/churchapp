"""Addresses outside any church on the members app: just the church finder."""

from django.urls import path

from core.views import health
from tenants import views

urlpatterns = [
    path("healthz/", health, name="health"),
    path("", views.find_church, name="find_church"),
]
