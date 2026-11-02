from django.urls import path

from . import views

app_name = "platform"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("login/", views.PlatformLoginView.as_view(), name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("password/", views.PlatformPasswordChangeView.as_view(), name="password"),
    path("password/reset/", views.PlatformPasswordResetView.as_view(), name="password_reset"),
    path("password/reset/done/", views.PlatformPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.PlatformPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.PlatformPasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("account/", views.account, name="account"),
    path("churches/new/", views.church_create, name="church_create"),
    path("churches/<int:pk>/", views.church_detail, name="church_detail"),
    path("churches/<int:pk>/edit/", views.church_edit, name="church_edit"),
    path("churches/<int:pk>/payment/", views.payment_add, name="payment_add"),
    path("churches/<int:pk>/status/", views.church_status, name="church_status"),
    path("churches/<int:pk>/reset-admin/", views.church_reset_admin, name="church_reset_admin"),
    path("churches/<int:pk>/domain/", views.church_domain, name="church_domain"),
    path("churches/<int:pk>/enter/", views.church_enter, name="church_enter"),
    path("churches/<int:pk>/logins/", views.church_login_action, name="church_login_action"),
    path("people/", views.people, name="people"),
    path("announcements/", views.announcements, name="announcements"),
    path("support-log/", views.support_log, name="support_log"),
    path("payments/", views.payments, name="payments"),
    path("plans/", views.plans, name="plans"),
    path("team/", views.team, name="team"),
]
