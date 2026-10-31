from django.conf import settings

from .models import ChurchProfile
from .permissions import capabilities_for, user_roles
from .utils import PERIOD_CHOICES


def brand():
    return {
        "product_name": settings.PRODUCT_NAME,
        "app_name": settings.APP_NAME,
        "app_tagline": settings.APP_TAGLINE,
        "vendor_name": settings.VENDOR_NAME,
    }


def church(request):
    user = getattr(request, "user", None)
    # The Android, iOS and desktop apps add "EcclesiaApp" to their user agent.
    native_app = "EcclesiaApp" in request.META.get("HTTP_USER_AGENT", "")
    if not user or not user.is_authenticated:
        return {"church": ChurchProfile.cached(), "brand": brand(), "native_app": native_app, "demo_mode": settings.DEMO_MODE}
    return {
        "brand": brand(),
        "native_app": native_app,
        "demo_mode": settings.DEMO_MODE,
        "media_is_temporary": settings.MEDIA_IS_TEMPORARY,
        "church": ChurchProfile.cached(),
        "caps": capabilities_for(user),
        "my_roles": sorted(user_roles(user)) or (["Superuser"] if user.is_superuser else []),
        "period_choices": PERIOD_CHOICES,
    }
