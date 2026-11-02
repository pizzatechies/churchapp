from django import forms
from django.contrib.auth.forms import AuthenticationForm

from core.forms import StyledModelForm
from members.models import Member
from tenants.security import LockoutMixin


class PortalAuthenticationForm(LockoutMixin, AuthenticationForm):
    """Only people on the membership register (with a current status) can use the members app."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        member = getattr(user, "member_profile", None)
        if member is None or not member.is_current:
            raise forms.ValidationError(
                "This login isn't linked to a current member record. Please contact the church office.",
                code="not_member",
            )


class ProfileForm(StyledModelForm):
    """What members may update about themselves. Office-only fields are never exposed here."""

    class Meta:
        model = Member
        fields = ["phone", "email", "residence", "town", "county", "postal_address", "occupation",
                  "emergency_contact_name", "emergency_contact_phone"]
