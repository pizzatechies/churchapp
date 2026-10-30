from contextvars import ContextVar

_current_user = ContextVar("current_user", default=None)
_audit_enabled = ContextVar("audit_enabled", default=True)


def get_current_user():
    user = _current_user.get()
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def audit_enabled():
    return _audit_enabled.get()


class audit_disabled:
    """Context manager used by bulk loaders (demo data) to skip audit logging."""

    def __enter__(self):
        self._token = _audit_enabled.set(False)

    def __exit__(self, *exc):
        _audit_enabled.reset(self._token)


class acting_as:
    """Attribute audit-log entries to a user outside of a request (management commands)."""

    def __init__(self, user):
        self.user = user

    def __enter__(self):
        self._token = _current_user.set(self.user)

    def __exit__(self, *exc):
        _current_user.reset(self._token)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current_user.set(getattr(request, "user", None))
        try:
            return self.get_response(request)
        finally:
            _current_user.reset(token)
