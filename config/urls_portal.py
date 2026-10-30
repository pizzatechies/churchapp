"""URLs for Ecclesia Connect, the members app. No finance URLs exist here at all."""

from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.views import health
from portal import views

urlpatterns = [
    path("healthz/", health, name="health"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", include("portal.urls")),
]

handler403 = "portal.views.error_403"
handler404 = "portal.views.error_404"
