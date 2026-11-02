from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from bankfeeds.urls import callback_urlpatterns as bank_feed_callbacks
from core import accounts

admin.site.site_header = "Ecclesia – database administration"
admin.site.site_title = "Ecclesia"

urlpatterns = [
    path("accounts/login/", accounts.StaffLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/profile/", accounts.profile, name="profile"),
    path("accounts/password/", accounts.StaffPasswordChangeView.as_view(), name="password_change"),
    path("accounts/password/done/", auth_views.PasswordChangeDoneView.as_view(), name="password_change_done"),
    path("accounts/password/reset/", accounts.StaffPasswordResetView.as_view(), name="password_reset"),
    path("accounts/password/reset/sent/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("accounts/password/reset/<uidb64>/<token>/", accounts.StaffPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("accounts/password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
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
