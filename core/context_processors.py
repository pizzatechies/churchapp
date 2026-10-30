from .models import ChurchProfile
from .permissions import capabilities_for, user_roles
from .utils import PERIOD_CHOICES


def church(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"church": ChurchProfile.cached()}
    return {
        "church": ChurchProfile.cached(),
        "caps": capabilities_for(user),
        "my_roles": sorted(user_roles(user)) or (["Superuser"] if user.is_superuser else []),
        "period_choices": PERIOD_CHOICES,
    }
