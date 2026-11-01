from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import Group, User

from .models import ChurchProfile, Document
from .permissions import ROLE_DESCRIPTIONS, ROLES


class StyledFormMixin:
    """Adds Bootstrap classes and native date pickers to every field."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateField) and not isinstance(field.widget, forms.HiddenInput):
                attrs = {**field.widget.attrs, "type": "date"}
                field.widget = forms.DateInput(attrs=attrs, format="%Y-%m-%d")
                field.widget.is_required = field.required
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            elif isinstance(widget, forms.HiddenInput):
                continue
            else:
                css = "form-control"
            existing = widget.attrs.get("class", "")
            if css not in existing:
                widget.attrs["class"] = f"{existing} {css}".strip()
            if isinstance(field, forms.DecimalField):
                widget.attrs.setdefault("step", "0.01")
                widget.attrs.setdefault("inputmode", "decimal")
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)


class StyledForm(StyledFormMixin, forms.Form):
    pass


class StyledModelForm(StyledFormMixin, forms.ModelForm):
    pass


class ChurchProfileForm(StyledModelForm):
    class Meta:
        model = ChurchProfile
        fields = [
            "name", "address", "phone", "email", "website", "tax_id", "country",
            "currency_code", "currency_symbol", "fiscal_year_start_month",
            "expense_approval_threshold", "require_separate_approver",
            "treasurer_name", "statement_footer",
            "members_see_own_giving", "members_see_finances", "member_finance_period",
        ]
        widgets = {"address": forms.Textarea(attrs={"rows": 3}), "statement_footer": forms.Textarea(attrs={"rows": 4})}


class LockDateForm(StyledModelForm):
    class Meta:
        model = ChurchProfile
        fields = ["lock_date"]


class UserForm(StyledModelForm):
    roles = forms.MultipleChoiceField(
        choices=[(r, r) for r in ROLES], widget=forms.CheckboxSelectMultiple, required=False,
        help_text="What this person is allowed to do.",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False), required=False,
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.role_descriptions = ROLE_DESCRIPTIONS
        if self.instance.pk:
            self.fields["roles"].initial = list(self.instance.groups.values_list("name", flat=True))
        else:
            self.fields["password"].required = True
            self.fields["password"].help_text = "At least 10 characters."

    def clean_password(self):
        password = self.cleaned_data.get("password")
        if password:
            from django.contrib.auth.password_validation import validate_password

            validate_password(password, self.instance if self.instance.pk else None)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("password"):
            user.set_password(self.cleaned_data["password"])
        user.save()
        groups = [Group.objects.get_or_create(name=name)[0] for name in self.cleaned_data["roles"]]
        user.groups.set(groups)
        return user


class DocumentForm(StyledForm):
    file = forms.FileField()
    description = forms.CharField(max_length=255, required=False)

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > settings.MAX_UPLOAD_SIZE:
            raise forms.ValidationError(f"Files must be smaller than {settings.MAX_UPLOAD_SIZE // (1024 * 1024)} MB.")
        return f

    def save(self, obj, user):
        f = self.cleaned_data["file"]
        from django.contrib.contenttypes.models import ContentType

        return Document.objects.create(
            content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk,
            file=f,
            original_name=f.name[:255],
            description=self.cleaned_data.get("description", ""),
            size=f.size,
            uploaded_by=user,
        )


class StaffAuthenticationForm(AuthenticationForm):
    """The admin app is for church staff and volunteers with a role; members use the members app."""

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not (user.is_superuser or user.groups.exists()):
            raise forms.ValidationError(
                f"This account is for {settings.PRODUCT_NAME} Connect, the members app. "
                "Ask the church office if you need staff access.",
                code="no_role",
            )
