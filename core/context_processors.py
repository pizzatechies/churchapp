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
    if not user or not user.is_authenticated:
        return {"church": ChurchProfile.cached(), "brand": brand()}
    return {
        "brand": brand(),
        "church": ChurchProfile.cached(),
        "caps": capabilities_for(user),
        "my_roles": sorted(user_roles(user)) or (["Superuser"] if user.is_superuser else []),
        "period_choices": PERIOD_CHOICES,
    }
