from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Church settings"

    def ready(self):
        from . import audit  # noqa: F401  (connects audit-log signal handlers)
