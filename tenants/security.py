"""
Sign-in protection and password reset, shared by the platform console, the admin app and the members app.

* After LOGIN_MAX_FAILURES wrong passwords for one login (or LOGIN_MAX_FAILURES_PER_IP from one
  address) sign-in pauses for LOGIN_LOCKOUT_MINUTES. A correct password clears the count.
* "Forgot password" emails a one-day link to the address on the login. It never says whether
  an address exists, and requests are limited per address.

Passwords themselves are never stored: Django keeps only a salted one-way hash (PBKDF2), so
nobody, including the platform owner, can read anyone's password. People can only set a new one.
"""

from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.db import connection
from django.utils import timezone

from .models import FailedLogin

RESET_REQUESTS_PER_HOUR = 5


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
    return ip or None


def _schema():
    return getattr(connection, "schema_name", "public")


def _since(minutes):
    return timezone.now() - timedelta(minutes=minutes)


def is_locked(username, ip):
    window = _since(settings.LOGIN_LOCKOUT_MINUTES)
    recent = FailedLogin.objects.filter(kind=FailedLogin.LOGIN, created_at__gte=window)
    if username and recent.filter(schema=_schema(), username__iexact=username).count() >= settings.LOGIN_MAX_FAILURES:
        return True
    return bool(ip and recent.filter(ip=ip).count() >= settings.LOGIN_MAX_FAILURES_PER_IP)


def record_failure(username, ip, kind=FailedLogin.LOGIN):
    FailedLogin.objects.create(schema=_schema(), username=(username or "")[:150], ip=ip, kind=kind)
    # Keep the table small.
    FailedLogin.objects.filter(created_at__lt=_since(24 * 60)).delete()


def clear_failures(username):
    FailedLogin.objects.filter(schema=_schema(), kind=FailedLogin.LOGIN, username__iexact=username).delete()


LOCKED_MESSAGE = ("Too many wrong passwords. For your security, sign-in is paused for {minutes} minutes. "
                  "If you've forgotten your password, use “Forgot password?”.")


class LockoutMixin:
    """For AuthenticationForm subclasses: pause sign-in after repeated wrong passwords."""

    def clean(self):
        username = self.cleaned_data.get("username") or self.data.get("username", "")
        ip = client_ip(self.request)
        if is_locked(username, ip):
            raise forms.ValidationError(LOCKED_MESSAGE.format(minutes=settings.LOGIN_LOCKOUT_MINUTES), code="locked")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            record_failure(username, ip)
            raise
        clear_failures(username)
        return cleaned


def reset_allowed(request):
    ip = client_ip(request)
    if not ip:
        return True
    return FailedLogin.objects.filter(kind=FailedLogin.RESET, ip=ip, created_at__gte=_since(60)).count() < RESET_REQUESTS_PER_HOUR


class AudiencePasswordResetForm(PasswordResetForm):
    """Password reset limited to the people who sign in to this app (staff, members or platform admins)."""

    audience = None  # callable(user) -> bool

    def get_users(self, email):
        users = User.objects.filter(email__iexact=email, is_active=True)
        return (u for u in users if u.has_usable_password() and (self.audience is None or self.audience(u)))

    def save(self, request=None, **kwargs):
        if request is not None:
            record_failure("", client_ip(request), kind=FailedLogin.RESET)
        return super().save(request=request, **kwargs)


def is_staff_login(user):
    return user.is_superuser or user.groups.exists()


def is_member_login(user):
    member = getattr(user, "member_profile", None)
    return member is not None and member.is_current


class StaffPasswordResetForm(AudiencePasswordResetForm):
    audience = staticmethod(is_staff_login)


class MemberPasswordResetForm(AudiencePasswordResetForm):
    audience = staticmethod(is_member_login)


class PlatformPasswordResetForm(AudiencePasswordResetForm):
    audience = staticmethod(lambda user: user.is_superuser)
