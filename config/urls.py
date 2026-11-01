from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from bankfeeds.urls import callback_urlpatterns as bank_feed_callbacks
from core.forms import StaffAuthenticationForm

admin.site.site_header = "Ecclesia – database administration"
admin.site.site_title = "Ecclesia"

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(redirect_authenticated_user=True, authentication_form=StaffAuthenticationForm), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password/", auth_views.PasswordChangeView.as_view(), name="password_change"),
    path("accounts/password/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("django-admin/", admin.site.urls),
    path("", include("core.urls")),
    path("ledger/", include("ledger.urls")),
    path("giving/", include("giving.urls")),
    path("expenses/", include("expenses.urls")),
    path("payroll/", include("payroll.urls")),
    path("assets/", include("fixedassets.urls")),
    path("reports/", include("reports.urls")),
    path("congregation/", include("members.urls")),
    path("ledger/banking/feeds/", include("bankfeeds.urls")),
    *bank_feed_callbacks,
]
