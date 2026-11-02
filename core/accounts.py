"""Signing in to the admin app, and each person's own password and profile."""

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from tenants.security import StaffPasswordResetForm, reset_allowed

from .forms import StaffAuthenticationForm, StyledModelForm
from .models import AccountProfile, ChurchProfile


class StaffLoginView(auth_views.LoginView):
    authentication_form = StaffAuthenticationForm
    redirect_authenticated_user = True


class StaffPasswordChangeView(auth_views.PasswordChangeView):
    template_name = "registration/password_change_form.html"
    success_url = reverse_lazy("profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        AccountProfile.password_set_by_someone_else(self.request.user, False)
        messages.success(self.request, "Your password was changed. Only you know it.")
        return response


def reset_email_context(app_name, url_name):
    return {"app_name": f"{ChurchProfile.cached().name} · {app_name}", "reset_url_name": url_name}


class ResetRequestMixin:
    """Shared by the admin and members apps' "Forgot password" pages."""

    app_label = settings.APP_NAME
    no_email_help = "Ask your church administrator to set a new password for you."

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "email_configured": settings.EMAIL_CONFIGURED, "no_email_help": self.no_email_help}

    def form_valid(self, form):
        # Same answer either way, so the page never reveals whether an address has a login.
        if not settings.EMAIL_CONFIGURED or not reset_allowed(self.request):
            return redirect(self.get_success_url())
        self.extra_email_context = reset_email_context(settings.APP_NAME, self.confirm_url_name)
        return super().form_valid(form)


class StaffPasswordResetView(ResetRequestMixin, auth_views.PasswordResetView):
    template_name = "registration/password_reset_form.html"
    form_class = StaffPasswordResetForm
    email_template_name = "emails/password_reset.txt"
    subject_template_name = "emails/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")
    confirm_url_name = "password_reset_confirm"


class StaffPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "registration/password_reset_confirm.html"
    success_url = reverse_lazy("password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        AccountProfile.password_set_by_someone_else(form.user, False)
        return response


class StaffProfileForm(StyledModelForm):
    phone = forms.CharField(max_length=40, required=False)

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]
        help_texts = {"email": "Password reset links are sent here."}

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another login already uses this email address.")
        return email


def profile(request):
    account = AccountProfile.for_user(request.user)
    form = StaffProfileForm(request.POST or None, instance=request.user, initial={"phone": account.phone})
    if request.method == "POST" and form.is_valid():
        form.save()
        account.phone = form.cleaned_data["phone"]
        account.save(update_fields=["phone"])
        member = getattr(request.user, "member_profile", None)
        if member and form.cleaned_data["email"] and member.email != form.cleaned_data["email"]:
            member.email = form.cleaned_data["email"]
            member.save(update_fields=["email"])
        messages.success(request, "Your details were saved.")
        return redirect("profile")
    return render(request, "core/profile.html", {"form": form, "account": account})
